"""JaCoCo 覆盖率采集编排服务

对外暴露：
- trigger()       API 层调用：创建 run + 占位 reports → arq 投递 → 返回 run_id
- cancel()        API 层调用：标记 run 为 cancelled（worker 侧轮询检测）
- run_collection() arq worker 调用：顺序执行 N 个服务的 build→report→parse→upload→写库

进度推送通过注入的 progress_callback 完成（worker 侧绑定到 Redis pub/sub）。
"""
from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ErrorCode
from app.core.logging import get_logger
from app.db.models.coverage_java import CoverageTask, JavaCoverageReport, JavaCoverageRun
from app.modules.coverage_java.build_service import BuildError, JavaBuildService
from app.modules.coverage_java.report_service import (
    JaCoCoReportService,
    ReportGenerateError,
)
from app.modules.coverage_java.repository import (
    CoverageTaskRepository,
    JavaCoverageReportRepository,
    JavaCoverageRunRepository,
)
from app.modules.coverage_java.diff_service import DiffCoverageService
from app.modules.coverage_java.runtime_service import DEFAULT_AGENT_PORT, RuntimeDumpService

logger = get_logger(__name__)


def _resolve_runtime_target(task: CoverageTask, service: dict) -> tuple[str, int, bool]:
    """运行时模式的 dump 目标：service 级 agent_host/agent_port 优先，否则用 task.runtime_config"""
    cfg = task.runtime_config or {}
    host = service.get("agent_host") or cfg.get("host")
    port = service.get("agent_port") or cfg.get("port") or DEFAULT_AGENT_PORT
    if not host:
        raise BuildError("test", f"服务 {service['name']} 未配置 JaCoCo agent 地址（runtime_config.host / agent_host）")
    return host, int(port), bool(cfg.get("reset", False))

ProgressCallback = Callable[[dict], Awaitable[None]]


def _now() -> datetime:
    return datetime.utcnow()


async def _noop_callback(_msg: dict) -> None:
    """默认空 callback（单测 / 不需要广播时使用）"""
    return None


class CoverageJavaService:
    """覆盖率任务编排服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.task_repo = CoverageTaskRepository(db)
        self.run_repo = JavaCoverageRunRepository(db)
        self.report_repo = JavaCoverageReportRepository(db)
        self.build_service = JavaBuildService()
        self.report_service = JaCoCoReportService()
        self.runtime_service = RuntimeDumpService()

    # ──────────────────────────────────────────────
    # Task CRUD（API 层调用）
    # ──────────────────────────────────────────────

    async def create_task(
        self,
        project_id: int,
        data: dict,
        owner_id: int,
    ) -> CoverageTask:
        await self._apply_code_repo(project_id, data)
        task = await self.task_repo.create(
            project_id=project_id,
            name=data["name"],
            repo_id=data.get("repo_id"),
            repo_url=data["repo_url"],
            services=[s if isinstance(s, dict) else s.model_dump() for s in data["services"]],
            branch=data.get("branch") or "main",
            diff_base_branch=data.get("diff_base_branch"),
            requirement_ref=data.get("requirement_ref"),
            cron_expr=data.get("cron_expr"),
            threshold_line_rate=data.get("threshold_line_rate"),
            threshold_branch_rate=data.get("threshold_branch_rate"),
            collection_mode=data.get("collection_mode") or "unittest",
            runtime_config=data.get("runtime_config"),
            owner_id=owner_id,
            status="draft",
        )
        await self.db.commit()
        return task

    async def _apply_code_repo(self, project_id: int, data: dict) -> None:
        """选了代码源时，以代码源的 repo_url 为准（同时校验代码源属于本项目）"""
        if not data.get("repo_id"):
            return
        from app.modules.code_repository.service import CodeRepositoryService
        repo = await CodeRepositoryService(self.db).get(project_id, data["repo_id"])
        data["repo_url"] = repo.repo_url

    async def get_task(self, project_id: int, task_id: int) -> CoverageTask:
        task = await self.task_repo.get(task_id)
        if not task or task.project_id != project_id:
            raise AppException(
                message=f"覆盖率任务不存在: {task_id}",
                code=ErrorCode.RESOURCE_NOT_FOUND,
                http_status=404,
            )
        return task

    async def list_tasks(
        self,
        project_id: int,
        page: int,
        page_size: int,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> dict:
        total, items = await self.task_repo.list_by_project(
            project_id, keyword=keyword, status=status, branch=branch,
            page=page, page_size=page_size,
        )
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    async def update_task(
        self,
        project_id: int,
        task_id: int,
        data: dict,
        user_id: int,
    ) -> CoverageTask:
        task = await self.get_task(project_id, task_id)
        await self._apply_code_repo(project_id, data)
        services = data.get("services")
        if services is not None:
            data["services"] = [s if isinstance(s, dict) else s.model_dump() for s in services]

        # 合并 patch 与现有配置后校验运行时模式
        mode = data.get("collection_mode") or task.collection_mode
        if mode == "runtime":
            cfg = data.get("runtime_config") or task.runtime_config or {}
            merged_services = data.get("services") or task.services or []
            missing = [s["name"] for s in merged_services if not (s.get("agent_host") or cfg.get("host"))]
            if missing:
                raise AppException(
                    message=f"运行时模式需配置 agent 地址（缺失: {', '.join(missing)}）",
                    code=ErrorCode.VALIDATION_ERROR,
                    http_status=422,
                )
        data["updated_by"] = user_id
        await self.task_repo.update(task, **data)
        await self.db.commit()
        return task

    async def delete_task(self, project_id: int, task_id: int, user_id: int) -> None:
        task = await self.get_task(project_id, task_id)
        await self.task_repo.soft_delete(task, user_id)
        await self.db.commit()

    # ──────────────────────────────────────────────
    # 触发 / 取消（API 层调用）
    # ──────────────────────────────────────────────

    async def trigger(
        self,
        project_id: int,
        task_id: int,
        user_id: int,
        trigger_type: str = "manual",
    ) -> tuple[JavaCoverageRun, list[JavaCoverageReport]]:
        """触发采集：创建 run + 各服务占位 report，状态均为 queued。

        调用方负责投递 arq 任务；本方法只写库不投递，便于事务边界清晰。
        """
        task = await self.get_task(project_id, task_id)

        # 409 冲突：已有任务在 queued/running 状态
        if task.status in ("queued", "running"):
            raise AppException(
                message=f"任务 {task_id} 已有进行中的采集，请先等待完成或取消",
                code=ErrorCode.REVISION_CONFLICT,
                http_status=409,
            )

        services = task.services or []
        if not services:
            raise AppException(
                message="任务未配置任何服务",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            )

        # 创建 run
        run = await self.run_repo.create(
            task_id=task.id,
            trigger_type=trigger_type,
            overall_status="queued",
            services_total=len(services),
            services_completed=0,
            services_failed=0,
        )

        # 为每个服务创建占位 report
        reports: list[JavaCoverageReport] = []
        for svc in services:
            r = await self.report_repo.create(
                run_id=run.id,
                task_id=task.id,
                service_name=svc["name"],
                status="queued",
                progress=0,
                stage="pending",
            )
            reports.append(r)

        # 更新任务状态
        await self.task_repo.update_status(
            task.id, status="queued", current_run_id=run.id,
        )
        await self.db.commit()

        logger.info(f"Triggered coverage task {task_id}: run_id={run.id}, services={len(services)}")
        return run, reports

    async def cancel(self, project_id: int, task_id: int, user_id: int) -> JavaCoverageRun:
        """取消当前 run：标记 cancelled（arq worker 侧轮询该状态会中断）"""
        task = await self.get_task(project_id, task_id)
        if not task.current_run_id:
            raise AppException(
                message="任务当前没有进行中的采集",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            )

        run = await self.run_repo.get(task.current_run_id)
        if not run or run.overall_status not in ("queued", "running"):
            raise AppException(
                message=f"run {task.current_run_id} 已结束，无法取消",
                code=ErrorCode.REVISION_CONFLICT,
                http_status=409,
            )

        await self.run_repo.update_status(run.id, overall_status="cancelled", finished_at=_now())
        await self.task_repo.update_status(task.id, status="cancelled")
        await self.db.commit()

        logger.info(f"Cancelled coverage task {task_id}: run_id={run.id}")
        return run

    # ──────────────────────────────────────────────
    # Run / Report 查询（API 层调用）
    # ──────────────────────────────────────────────

    async def list_runs(self, project_id: int, task_id: int, page: int, page_size: int) -> dict:
        await self.get_task(project_id, task_id)
        total, items = await self.run_repo.list_by_task(task_id, page=page, page_size=page_size)
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    async def list_run_reports(self, run_id: int) -> list[JavaCoverageReport]:
        return await self.report_repo.list_by_run(run_id)

    async def get_report(self, report_id: int) -> JavaCoverageReport:
        report = await self.report_repo.get(report_id)
        if not report:
            raise AppException(
                message=f"报告不存在: {report_id}",
                code=ErrorCode.RESOURCE_NOT_FOUND,
                http_status=404,
            )
        return report

    async def list_report_files(self, report_id: int) -> list[dict]:
        """从 line_coverage_json 提取文件列表汇总"""
        report = await self.get_report(report_id)
        coverage = report.line_coverage_json or {}
        files = []
        for file_path, file_data in coverage.items():
            files.append({
                "file_path": file_path,
                "package": file_data.get("package"),
                "class_name": file_data.get("class_name") or file_data.get("file_name"),
                "lines_total": file_data.get("lines_total", 0),
                "lines_covered": file_data.get("lines_covered", 0),
                "line_rate": file_data.get("line_rate", 0.0),
            })
        return files

    async def get_file_content(self, report_id: int, file_path: str) -> dict:
        """读取单文件源码（MinIO 源码快照）+ 行级覆盖标记

        快照缺失（历史报告 / 上传失败）时 source 为空、source_available=False，
        前端按行号兜底展示覆盖标记。
        """
        report = await self.get_report(report_id)
        coverage = (report.line_coverage_json or {}).get(file_path)
        if coverage is None:
            raise AppException(
                message=f"文件 {file_path} 不在该报告中",
                code=ErrorCode.RESOURCE_NOT_FOUND,
                http_status=404,
            )

        source: Optional[str] = None
        if report.source_snapshot_path:
            try:
                source = self.report_service.read_source_from_snapshot(
                    report.source_snapshot_path, file_path,
                )
            except Exception as e:
                logger.error(f"Failed to read source snapshot for report {report_id}: {e}")

        return {
            "file_path": file_path,
            "source": source or "",
            "source_available": source is not None,
            "line_coverage": coverage.get("lines", []),
        }

    async def get_build_log(self, report_id: int) -> str:
        """从 MinIO 拉取构建日志"""
        report = await self.get_report(report_id)
        if not report.build_log_path:
            raise AppException(
                message="该报告没有构建日志",
                code=ErrorCode.RESOURCE_NOT_FOUND,
                http_status=404,
            )
        try:
            content = self.report_service.minio.download_file(report.build_log_path)
            return content.decode("utf-8", errors="replace")
        except Exception as e:
            logger.error(f"Failed to download build log for report {report_id}: {e}")
            raise AppException(
                message=f"构建日志下载失败: {e}",
                code=ErrorCode.INTERNAL_ERROR,
                http_status=500,
            )

    async def get_diff_coverage(self, report_id: int) -> dict:
        """计算增量覆盖率（基于 git diff merge-base）

        前置条件：
        - report 所在的 task 配置了 diff_base_branch
        - workspace 中还保留着该 run 的 clone(当前 MVP 不清理)

        Returns:
            DiffCoverageResponse 结构

        Raises:
            AppException: 404=报告不存在 / 422=无 diff_base_branch / 500=git 命令失败
        """
        report = await self.get_report(report_id)
        task = await self.task_repo.get(report.task_id)
        if not task:
            raise AppException(
                message=f"任务 {report.task_id} 不存在",
                code=ErrorCode.RESOURCE_NOT_FOUND,
                http_status=404,
            )

        diff_base = task.diff_base_branch
        if not diff_base:
            raise AppException(
                message="该任务未配置 diff_base_branch，无法计算增量覆盖率",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            )

        if report.status != "completed" or not report.line_coverage_json:
            raise AppException(
                message="报告尚未成功生成，无法计算增量覆盖率",
                code=ErrorCode.VALIDATION_ERROR,
                http_status=422,
            )

        # 与 JavaBuildService 保持一致: {workspace_root}/{task_id}/{run_id}/{service_name}/repo
        repo_path = (
            self.build_service._service_workspace(report.task_id, report.run_id, report.service_name)
            / "repo"
        )
        if not (repo_path / ".git").exists():
            raise AppException(
                message=f"采集 workspace 已被清理（{repo_path}），请重新触发采集",
                code=ErrorCode.RESOURCE_NOT_FOUND,
                http_status=404,
            )

        try:
            merge_base, changed_lines = await asyncio.to_thread(
                DiffCoverageService.get_changed_lines, repo_path, diff_base, "HEAD"
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            logger.error(f"git failed for report {report_id}: {e.cmd} -> {stderr}")
            raise AppException(
                message=f"git 命令执行失败: {stderr or e}",
                code=ErrorCode.INTERNAL_ERROR,
                http_status=500,
            )
        except subprocess.TimeoutExpired as e:
            raise AppException(
                message=f"git 命令超时: {e.cmd}",
                code=ErrorCode.INTERNAL_ERROR,
                http_status=500,
            )

        result = DiffCoverageService.calculate_diff_coverage(
            changed_lines=changed_lines,
            line_coverage=report.line_coverage_json,
        )
        result.update(
            base_branch=diff_base,
            merge_base=merge_base,
            head_commit=report.commit_sha,
        )
        return result

    # ──────────────────────────────────────────────
    # 采集执行（arq worker 调用）
    # ──────────────────────────────────────────────

    async def run_collection(
        self,
        task_id: int,
        run_id: int,
        repo_url: str,
        progress_callback: ProgressCallback = _noop_callback,
    ) -> dict:
        """执行整个 run 的采集：对每个 service 顺序执行。

        Args:
            task_id: 任务 ID
            run_id:  run ID
            repo_url: 仓库 URL（API 层在投递 arq 时从 project 表读出）
            progress_callback: 进度回调，签名 async def cb(msg: dict)
                               worker 侧通常绑定到 Redis pub/sub

        Returns:
            {"success": bool, "completed": int, "failed": int, "cancelled": bool}
        """
        run = await self.run_repo.get(run_id)
        if not run:
            logger.error(f"run {run_id} not found")
            return {"success": False, "completed": 0, "failed": 0, "cancelled": False}

        task = await self.task_repo.get(task_id)
        if not task:
            logger.error(f"task {task_id} not found")
            return {"success": False, "completed": 0, "failed": 0, "cancelled": False}

        # 标记 run / task running
        await self.run_repo.update_status(run_id, overall_status="running", started_at=_now())
        await self.task_repo.update_status(task_id, status="running")
        await self.db.commit()

        services = task.services or []
        completed = 0
        failed = 0
        cancelled = False

        for svc in services:
            # 检查外部 cancel 信号
            await self.db.refresh(run)
            if run.overall_status == "cancelled":
                logger.info(f"run {run_id} cancelled externally, aborting")
                cancelled = True
                # 剩余 service 标记 skipped
                remaining = await self.report_repo.list_by_run(run_id)
                for r in remaining:
                    if r.status in ("queued", "running"):
                        await self.report_repo.update_result(r.id, status="skipped")
                await self.db.commit()
                break

            # 找到该 service 对应的 report 记录
            reports = await self.report_repo.list_by_run(run_id)
            svc_report = next((r for r in reports if r.service_name == svc["name"]), None)
            if not svc_report:
                logger.warning(f"report not found for service {svc['name']} in run {run_id}")
                continue

            try:
                await self._run_one_service(
                    task=task, run=run, service=svc, report=svc_report,
                    repo_url=repo_url, progress_callback=progress_callback,
                )
                completed += 1
            except (BuildError, ReportGenerateError) as e:
                failed += 1
                logger.error(f"[{svc['name']}] collection failed: {e}")
                await self._mark_service_failed(svc_report, e, progress_callback)
            except Exception as e:
                failed += 1
                logger.exception(f"[{svc['name']}] unexpected error")
                await self._mark_service_failed(svc_report, e, progress_callback)

            # 更新 run 的进度计数
            await self.run_repo.update_status(
                run_id,
                overall_status="running",
                services_completed=completed,
                services_failed=failed,
            )
            await self.db.commit()

        # 汇总最终状态
        if cancelled:
            final_status = "cancelled"
        elif failed == 0 and completed == len(services):
            final_status = "completed"
        elif completed == 0:
            final_status = "failed"
        else:
            final_status = "partial"

        await self.run_repo.update_status(
            run_id, overall_status=final_status, finished_at=_now(),
        )
        task_final = "completed" if final_status == "completed" else (
            "cancelled" if final_status == "cancelled" else "failed"
        )
        await self.task_repo.update_status(
            task_id,
            status=task_final,
            last_completed_at=_now() if final_status == "completed" else None,
            last_failed_at=_now() if final_status in ("failed", "partial") else None,
        )
        await self.db.commit()

        # 广播 task_done
        await progress_callback({
            "type": "task_done",
            "task_id": task_id,
            "run_id": run_id,
            "success": True if final_status == "completed" else (False if final_status == "failed" else None),
            "partial": final_status == "partial",
        })

        return {
            "success": final_status == "completed",
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
        }

    async def _run_one_service(
        self,
        task: CoverageTask,
        run: JavaCoverageRun,
        service: dict,
        report: JavaCoverageReport,
        repo_url: str,
        progress_callback: ProgressCallback,
    ) -> None:
        """单服务采集流程"""
        service_name = service["name"]
        report_id = report.id

        async def _progress(progress: int, stage: str, detail: Optional[str] = None):
            await self.report_repo.update_progress(report_id, progress, stage, detail)
            await self.db.commit()
            await progress_callback({
                "type": "progress",
                "report_id": report_id,
                "service_name": service_name,
                "progress": progress,
                "stage": stage,
                "stage_detail": detail,
            })

        await self.report_repo.update_progress(report_id, 0, "pending", status="running")

        if (task.collection_mode or "unittest") == "runtime":
            # 运行时模式：clone + compile（拿 class/源码）→ tcpserver dump .exec
            host, port, reset = _resolve_runtime_target(task, service)
            await _progress(5, "clone", "克隆代码仓库...")
            build_result = await self.build_service.run_compile(
                task_id=task.id, run_id=run.id, service=service,
                repo_url=repo_url, branch=task.branch,
            )
            await _progress(50, "test", f"从 {host}:{port} dump 运行时覆盖率...")
            dump_log = await self.runtime_service.dump_coverage(
                host=host, port=port, output_exec_file=build_result.exec_file, reset=reset,
            )
            build_result.build_log += f"\n\n===== DUMP =====\n\n{dump_log}"
            await _progress(60, "report", "dump 完成，生成 JaCoCo 报告...")
        else:
            # 1. clone + build (progress 5 → 60)
            await _progress(5, "clone", "克隆代码仓库...")
            build_result = await self.build_service.run_build(
                task_id=task.id, run_id=run.id, service=service,
                repo_url=repo_url, branch=task.branch,
            )
            await _progress(60, "build", "构建完成，生成 JaCoCo 报告...")

        # 2. 生成报告 (progress 60 → 85)
        output_dir = build_result.exec_file.parent
        xml_path, html_dir = await self.report_service.generate_xml_html(
            exec_file=build_result.exec_file,
            classfiles_dir=build_result.classfiles_dir,
            sourcefiles_dir=build_result.sourcefiles_dir,
            output_dir=output_dir / "report",
        )
        await _progress(85, "report", "解析报告数据...")

        # 3. 解析 XML (progress 85 → 95)
        parsed = self.report_service.parse_xml(xml_path)
        overall = parsed["overall"]
        await _progress(95, "report", "上传产物...")

        # 4. 上传产物 (progress 95 → 100)
        artifact_paths = self.report_service.upload_artifacts(
            task_id=task.id, run_id=run.id, service_name=service_name,
            xml_path=xml_path, html_dir=html_dir,
            exec_file=build_result.exec_file, build_log=build_result.build_log,
        )
        # 源码快照：失败不影响覆盖率结果，代码页降级为“源码不可用”
        try:
            snapshot_path = self.report_service.upload_source_snapshot(
                task_id=task.id, run_id=run.id, service_name=service_name,
                sourcefiles_dir=build_result.sourcefiles_dir,
                file_paths=list(parsed["files"].keys()),
            )
        except Exception as e:
            logger.warning(f"[{service_name}] source snapshot upload failed: {e}")
            snapshot_path = None

        # 5. 写库
        await self.report_repo.update_result(
            report_id,
            status="completed",
            progress=100,
            stage="done",
            stage_detail="完成",
            commit_sha=build_result.commit_sha,
            line_rate=overall.get("line_rate"),
            branch_rate=overall.get("branch_rate"),
            lines_covered=overall.get("lines_covered"),
            lines_total=overall.get("lines_total"),
            branches_covered=overall.get("branches_covered"),
            branches_total=overall.get("branches_total"),
            line_coverage_json=parsed["files"],
            source_snapshot_path=snapshot_path,
            **artifact_paths,
        )
        await self.db.commit()

        # 6. 广播 service_done
        await progress_callback({
            "type": "service_done",
            "report_id": report_id,
            "service_name": service_name,
            "success": True,
            "progress": 100,
            "stage": "done",
            "coverage": {
                "line_rate": overall.get("line_rate"),
                "branch_rate": overall.get("branch_rate"),
                "lines_covered": overall.get("lines_covered"),
                "lines_total": overall.get("lines_total"),
            },
        })

    async def _mark_service_failed(
        self,
        report: JavaCoverageReport,
        error: Exception,
        progress_callback: ProgressCallback,
    ) -> None:
        """标记单服务失败 + 广播"""
        stage = getattr(error, "stage", report.stage) or "build"
        message = getattr(error, "message", str(error)) or "unknown error"
        build_log = getattr(error, "build_log", "")

        # 尝试上传 build_log（如果有）
        build_log_path = None
        if build_log:
            try:
                build_log_path = f"coverage/{report.task_id}/{report.run_id}/{report.service_name}/build.log"
                self.report_service.minio.upload_file(
                    build_log_path, build_log.encode("utf-8"), content_type="text/plain",
                )
            except Exception as upload_err:
                logger.warning(f"Failed to upload build log for {report.service_name}: {upload_err}")
                build_log_path = None

        await self.report_repo.update_result(
            report.id,
            status="failed",
            error_message=message,
            build_log_path=build_log_path,
        )
        await self.db.commit()

        await progress_callback({
            "type": "service_error",
            "report_id": report.id,
            "service_name": report.service_name,
            "progress": report.progress,
            "stage": stage,
            "message": message,
            "build_log_url": f"/api/v1/coverage/reports/{report.id}/build-log" if build_log_path else None,
        })
