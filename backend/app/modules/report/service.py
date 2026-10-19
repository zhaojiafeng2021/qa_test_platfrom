"""WP-08 报告与通知的业务逻辑层。"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from app.core.logging import get_logger
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ResourceNotFoundError, ValidationError
from app.core.minio_client import get_minio_client
from app.db.models.code_case import CodeTestCase, CodeCaseExecution
from app.db.models.environment import Environment as EnvironmentModel
from app.db.models.project import Project
from app.db.models.test_plan import PlanRun, PlanRunItem, TestPlan
from app.modules.report.repository import (
    NotificationLogRepository,
    NotificationRuleRepository,
    ReportFileRepository,
)
from app.modules.test_plan.repository import TestPlanRepository
from app.schemas.report import (
    NotificationLogInfo,
    NotificationRuleCreate,
    NotificationRuleInfo,
    NotificationRuleUpdate,
    ReportFileInfo,
)

# Jinja2环境初始化
TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# MinIO 不可用时的本地存储根目录（开发环境 fallback）
LOCAL_REPORTS_DIR = Path(__file__).parent.parent.parent.parent / "temp_reports"

logger = get_logger(__name__)


class ReportService:
    """报告文件服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ReportFileRepository(db)
        self.minio_client = get_minio_client()

    async def create_report(
        self,
        project_id: int,
        report_type: str,
        user_id: int,
        plan_run_id: int,
    ) -> ReportFileInfo:
        """
        创建报告文件记录（占位，实际生成在后台任务）。

        Args:
            project_id: 项目ID
            report_type: 报告类型（html/pdf）
            user_id: 创建者ID
            plan_run_id: 计划运行ID（计划报告）

        Returns:
            报告文件信息
        """
        # 先创建记录拿到 report.id，再用 id 组装唯一文件路径，
        # 避免同一 plan_run 的多份报告共用同一路径而相互覆盖/误删。
        report = await self.repo.create(
            project_id=project_id,
            report_type=report_type,
            file_path="",
            created_by=user_id,
            plan_run_id=plan_run_id,
        )
        await self.db.flush()
        report.file_path = f"reports/plan_runs/{plan_run_id}/report_{report.id}.{report_type}"
        await self.db.commit()
        await self.db.refresh(report)

        # 同步生成报告：报告生成为轻量操作（DB查询 + 模板渲染），
        # 不需要 arq 异步队列，直接在请求内完成，规避 worker 消费问题。
        await self.generate_and_store(report.id)
        await self.db.refresh(report)

        return await self._to_info(report)

    async def generate_and_store(self, report_id: int) -> str:
        """
        生成报告内容并存储（MinIO 优先，失败 fallback 到本地文件系统）。

        同步执行，供 create_report 直接调用，也可供后台任务复用。
        任何异常都会被捕获并记入报告的 failed 状态，不向上抛出。

        Args:
            report_id: 报告文件ID

        Returns:
            "success" 或 "failed"
        """
        report = await self.repo.get(report_id)
        if not report:
            logger.error(f"Report not found: {report_id}")
            return "failed"

        try:
            # 目前仅支持 plan_run 的 HTML 报告；PDF/execution 报告为后续 Phase
            if report.report_type != "html":
                await self.repo.update_status(
                    report_id, "failed", error_message=f"暂不支持的报告类型: {report.report_type}"
                )
                await self.db.commit()
                return "failed"

            if not report.plan_run_id:
                await self.repo.update_status(
                    report_id, "failed", error_message="单用例执行报告暂未实现"
                )
                await self.db.commit()
                return "failed"

            # 生成 HTML 内容
            html_bytes = await self.generate_html_report(report.project_id, report.plan_run_id)

            # 存储：MinIO 优先，失败 fallback 到本地
            try:
                self.minio_client.upload_file(
                    object_name=report.file_path,
                    file_data=html_bytes,
                    content_type="text/html; charset=utf-8",
                )
                logger.info(f"Report uploaded to MinIO: {report.file_path}")
            except Exception as minio_err:
                logger.warning(f"MinIO upload failed, saving locally: {minio_err}")
                local_path = LOCAL_REPORTS_DIR / report.file_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(html_bytes)
                logger.info(f"Report saved locally: {local_path}")

            await self.repo.update_status(
                report_id, status="generated", file_size=len(html_bytes)
            )
            await self.db.commit()
            logger.info(f"Report generated successfully: {report_id}, size={len(html_bytes)}")
            return "success"

        except Exception as e:
            await self.db.rollback()
            logger.exception(f"generate_and_store failed report_id={report_id}")
            # 用独立事务写入失败状态，避免被回滚吞掉
            try:
                await self.repo.update_status(report_id, "failed", error_message=str(e))
                await self.db.commit()
            except Exception:
                await self.db.rollback()
            return "failed"

    async def get_report(self, project_id: int, report_id: int) -> ReportFileInfo:
        """获取报告文件信息。"""
        report = await self.repo.get(report_id)
        if not report or report.project_id != project_id:
            raise ResourceNotFoundError("报告文件不存在")
        return await self._to_info(report)

    async def list_reports(
        self,
        project_id: int,
        page: int = 1,
        page_size: int = 20,
        report_type: str | None = None,
        started_from: str | None = None,
        started_to: str | None = None,
    ) -> dict:
        """分页列出项目的报告文件（支持筛选）。"""
        total, reports = await self.repo.list_by_project(
            project_id, page, page_size, report_type, started_from, started_to
        )
        # Performance optimization: skip download_url generation in list view
        # download_url will be generated only when accessing individual report
        items = [await self._to_info(r, include_download_url=False) for r in reports]
        return {"total": total, "items": items}

    async def list_reports_by_plan_run(self, project_id: int, plan_run_id: int) -> list[ReportFileInfo]:
        """列出某个计划运行的所有报告。"""
        reports = await self.repo.list_by_plan_run(plan_run_id)
        # 验证project_id
        for report in reports:
            if report.project_id != project_id:
                raise ResourceNotFoundError("报告文件不存在")
        # Performance optimization: skip download_url generation in list view
        return [await self._to_info(r, include_download_url=False) for r in reports]

    async def get_report_content(self, project_id: int, report_id: int) -> tuple[bytes, str, str]:
        """
        读取报告文件内容（MinIO 优先，fallback 本地）。

        Returns:
            (文件字节内容, content_type, 文件名)
        """
        report = await self.repo.get(report_id)
        if not report or report.project_id != project_id:
            raise ResourceNotFoundError("报告文件不存在")
        if report.status != "generated":
            raise ValidationError("报告尚未生成完成")

        content: bytes | None = None
        try:
            content = self.minio_client.download_file(report.file_path)
        except Exception:
            local_path = LOCAL_REPORTS_DIR / report.file_path
            if local_path.exists():
                content = local_path.read_bytes()

        if content is None:
            raise ResourceNotFoundError("报告文件内容不存在")

        content_type = "text/html; charset=utf-8" if report.report_type == "html" else "application/pdf"
        filename = os.path.basename(report.file_path)
        return content, content_type, filename

    async def delete_report(self, project_id: int, report_id: int):
        """删除报告记录及其存储文件。"""
        report = await self.repo.get(report_id)
        if not report or report.project_id != project_id:
            raise ResourceNotFoundError("报告文件不存在")

        # 尝试删除存储文件（MinIO + 本地），失败不阻断记录删除
        try:
            self.minio_client.delete_file(report.file_path)
        except Exception:
            pass
        try:
            local_path = LOCAL_REPORTS_DIR / report.file_path
            if local_path.exists():
                local_path.unlink()
        except Exception:
            pass

        await self.repo.delete(report_id)
        await self.db.commit()

    async def gather_plan_run_data(self, project_id: int, plan_run_id: int) -> dict:
        """
        聚合计划运行报告数据。

        Args:
            project_id: 项目ID
            plan_run_id: 计划运行ID

        Returns:
            报告数据字典（用于模板渲染）
        """
        # 获取计划运行（直接查询PlanRun表）
        result = await self.db.execute(
            select(PlanRun).where(
                PlanRun.id == plan_run_id,
                PlanRun.project_id == project_id
            )
        )
        plan_run = result.scalar_one_or_none()
        if not plan_run:
            raise ResourceNotFoundError("计划运行不存在")

        # 计算通过率
        pass_rate = 0.0
        if plan_run.total_items > 0:
            pass_rate = (plan_run.passed_items / plan_run.total_items) * 100

        # 计算执行耗时
        duration = "-"
        if plan_run.started_at and plan_run.finished_at:
            delta = plan_run.finished_at - plan_run.started_at
            total_seconds = int(delta.total_seconds())
            if total_seconds < 60:
                duration = f"{total_seconds}秒"
            else:
                minutes = total_seconds // 60
                seconds = total_seconds % 60
                duration = f"{minutes}分{seconds}秒"

        # 查询运行项
        result = await self.db.execute(
            select(PlanRunItem)
            .where(PlanRunItem.plan_run_id == plan_run_id)
            .order_by(PlanRunItem.sort_order, PlanRunItem.id)
        )
        plan_run_items = result.scalars().all()

        # 关联查询：计划名称
        plan_name = f"计划 #{plan_run.plan_id}"
        plan_result = await self.db.execute(
            select(TestPlan.name).where(TestPlan.id == plan_run.plan_id)
        )
        plan_name_row = plan_result.scalar_one_or_none()
        if plan_name_row:
            plan_name = plan_name_row

        # 关联查询：项目名称
        project_name = None
        proj_result = await self.db.execute(
            select(Project.name).where(Project.id == plan_run.project_id)
        )
        project_name = proj_result.scalar_one_or_none()

        # 关联查询：环境名称
        environment_name = None
        if plan_run.environment_id:
            env_result = await self.db.execute(
                select(EnvironmentModel.display_name).where(EnvironmentModel.id == plan_run.environment_id)
            )
            environment_name = env_result.scalar_one_or_none()

        # 批量关联查询：用例名称+等级（CodeTestCase）
        case_ids = list({item.case_id for item in plan_run_items})
        case_map: dict[int, CodeTestCase] = {}
        if case_ids:
            case_result = await self.db.execute(
                select(CodeTestCase).where(CodeTestCase.id.in_(case_ids))
            )
            case_map = {c.id: c for c in case_result.scalars().all()}

        # 批量关联查询：执行详情（CodeCaseExecution）
        execution_ids = list({item.code_execution_id for item in plan_run_items if item.code_execution_id})
        exec_map: dict[int, CodeCaseExecution] = {}
        if execution_ids:
            exec_result = await self.db.execute(
                select(CodeCaseExecution).where(CodeCaseExecution.id.in_(execution_ids))
            )
            exec_map = {e.id: e for e in exec_result.scalars().all()}

        items = []
        for item in plan_run_items:
            case = case_map.get(item.case_id)
            execution = exec_map.get(item.code_execution_id) if item.code_execution_id else None
            passed_steps = 1 if execution and execution.status == "passed" else 0
            failed_steps = 1 if execution and execution.status in ("failed", "error", "timeout") else 0
            items.append({
                "case_id": item.case_id,
                "case_name": case.name if case else f"用例 #{item.case_id}",
                "priority": case.level if case else "-",
                "status": item.status,
                "passed_steps": passed_steps,
                "failed_steps": failed_steps,
                "total_steps": 1,
                "duration_ms": execution.duration_ms if execution and execution.duration_ms is not None else 0,
                "error_message": execution.message if execution else None,
            })

        # 组装数据
        return {
            "plan_run": {
                "id": plan_run.id,
                "plan_id": plan_run.plan_id,
                "plan_name": plan_name,
                "project_id": plan_run.project_id,
                "project_name": project_name,
                "environment_id": plan_run.environment_id,
                "environment_name": environment_name,
                "status": plan_run.status,
                "trigger_type": plan_run.trigger_type,
                "concurrency": plan_run.concurrency,
                "failure_strategy": plan_run.failure_strategy,
                "total_items": plan_run.total_items,
                "passed_items": plan_run.passed_items,
                "failed_items": plan_run.failed_items,
                "started_at": plan_run.started_at.strftime("%Y-%m-%d %H:%M:%S") if plan_run.started_at else None,
                "finished_at": plan_run.finished_at.strftime("%Y-%m-%d %H:%M:%S") if plan_run.finished_at else None,
            },
            "pass_rate": pass_rate,
            "duration": duration,
            "items": items,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    async def generate_html_report(self, project_id: int, plan_run_id: int) -> bytes:
        """
        生成HTML报告。

        Args:
            project_id: 项目ID
            plan_run_id: 计划运行ID

        Returns:
            HTML内容（bytes）
        """
        # 聚合数据
        data = await self.gather_plan_run_data(project_id, plan_run_id)

        # 渲染模板
        template = jinja_env.get_template("report_plan_run.html")
        html_content = template.render(**data)

        return html_content.encode("utf-8")

    async def _to_info(self, report, include_download_url: bool = True) -> ReportFileInfo:
        """转换为Info模型，并生成下载URL。

        优先返回 MinIO 预签名URL；MinIO 不可用时，若本地存在文件，
        返回后端本地文件服务接口的相对URL。

        Args:
            report: ReportFile 模型实例
            include_download_url: 是否生成 download_url（列表接口设为 False 以提升性能）
        """
        info = ReportFileInfo.model_validate(report)
        if include_download_url and report.status == "generated":
            download_url = None
            try:
                download_url = self.minio_client.get_presigned_url(
                    report.file_path, expires=timedelta(days=7)
                )
            except Exception:
                # MinIO 不可用，检查本地文件
                local_path = LOCAL_REPORTS_DIR / report.file_path
                if local_path.exists():
                    # 指向后端本地文件服务接口（见 api/v1/report.py）
                    download_url = f"/api/v1/projects/{report.project_id}/reports/{report.id}/download"
            info.download_url = download_url
        return info


class NotificationService:
    """通知规则服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.rule_repo = NotificationRuleRepository(db)
        self.log_repo = NotificationLogRepository(db)

    async def create_rule(
        self, project_id: int, data: NotificationRuleCreate, user_id: int
    ) -> NotificationRuleInfo:
        """创建通知规则。"""
        rule = await self.rule_repo.create(
            project_id=project_id,
            name=data.name,
            trigger_type=data.trigger_type,
            conditions_json=data.conditions_json,
            webhook_url=data.webhook_url,
            enabled=data.enabled,
            created_by=user_id,
        )
        await self.db.commit()
        await self.db.refresh(rule)
        return NotificationRuleInfo.model_validate(rule)

    async def get_rule(self, project_id: int, rule_id: int) -> NotificationRuleInfo:
        """获取通知规则。"""
        rule = await self.rule_repo.get(rule_id)
        if not rule or rule.project_id != project_id:
            raise ResourceNotFoundError("通知规则不存在")
        return NotificationRuleInfo.model_validate(rule)

    async def list_rules(self, project_id: int) -> list[NotificationRuleInfo]:
        """列出项目的所有通知规则。"""
        rules = await self.rule_repo.list_by_project(project_id)
        return [NotificationRuleInfo.model_validate(r) for r in rules]

    async def update_rule(
        self, project_id: int, rule_id: int, data: NotificationRuleUpdate, user_id: int
    ) -> NotificationRuleInfo:
        """更新通知规则。"""
        rule = await self.rule_repo.get(rule_id)
        if not rule or rule.project_id != project_id:
            raise ResourceNotFoundError("通知规则不存在")

        values = data.model_dump(exclude_unset=True)
        updated_rule = await self.rule_repo.update(rule_id, user_id, **values)
        await self.db.commit()
        await self.db.refresh(updated_rule)
        return NotificationRuleInfo.model_validate(updated_rule)

    async def delete_rule(self, project_id: int, rule_id: int):
        """删除通知规则。"""
        rule = await self.rule_repo.get(rule_id)
        if not rule or rule.project_id != project_id:
            raise ResourceNotFoundError("通知规则不存在")
        await self.rule_repo.delete(rule_id)
        await self.db.commit()

    async def list_logs(
        self, project_id: int, rule_id: int, page: int = 1, page_size: int = 20
    ) -> dict:
        """分页列出通知日志。"""
        # 验证规则属于该项目
        rule = await self.rule_repo.get(rule_id)
        if not rule or rule.project_id != project_id:
            raise ResourceNotFoundError("通知规则不存在")

        total, logs = await self.log_repo.list_by_rule(rule_id, page, page_size)
        items = [NotificationLogInfo.model_validate(log) for log in logs]
        return {"total": total, "items": items}

    # ---- 通知触发与发送 ----

    @staticmethod
    def _match_conditions(conditions: dict | None, run_status: str) -> bool:
        """判断计划运行是否命中规则触发条件。

        约定 conditions_json 结构（皆为可选，缺省=不限制）：
          {"on_status": ["failed", "error", "passed", ...]}
        - on_status 为空列表或缺省 → 任意终态都触发；
        - 否则仅当 run_status 在 on_status 内才触发。
        """
        if not conditions:
            return True
        on_status = conditions.get("on_status")
        if not on_status:
            return True
        return run_status in on_status

    @staticmethod
    def _build_feishu_card(data: dict) -> dict:
        """构造飞书自定义机器人交互式卡片消息体。

        data 来自 ReportService.gather_plan_run_data 的 plan_run 段 + 汇总字段。
        """
        run = data["plan_run"]
        status = run["status"]
        status_color = {
            "passed": "green",
            "failed": "red",
            "error": "red",
            "timeout": "orange",
            "cancelled": "grey",
        }.get(status, "blue")
        pass_rate = data.get("pass_rate", 0.0)

        lines = [
            f"**测试计划**: {run.get('plan_name')}",
            f"**项目**: {run.get('project_name')}",
            f"**环境**: {run.get('environment_name') or '-'}",
            f"**状态**: {status}",
            f"**用例统计**: 通过 {run.get('passed_items')} / 失败 {run.get('failed_items')} / 总计 {run.get('total_items')}",
            f"**通过率**: {pass_rate:.1f}%",
            f"**耗时**: {data.get('duration', '-')}",
            f"**开始时间**: {run.get('started_at') or '-'}",
            f"**结束时间**: {run.get('finished_at') or '-'}",
        ]
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"测试计划执行完成 #{run.get('id')}",
                    },
                    "template": status_color,
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": "\n".join(lines)},
                    }
                ],
            },
        }

    @staticmethod
    async def _post_webhook(webhook_url: str, payload: dict) -> dict:
        """向飞书自定义机器人 webhook 发送消息，返回响应 JSON。

        飞书成功响应为 {"code": 0, ...} 或 {"StatusCode": 0, ...}；
        非 0 视为发送失败并抛出异常。
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            body = resp.json()
        code = body.get("code", body.get("StatusCode", 0))
        if code not in (0, None):
            raise RuntimeError(f"飞书返回错误: {body}")
        return body

    async def dispatch_plan_run_notifications(self, project_id: int, plan_run_id: int) -> int:
        """计划运行结束后触发通知：查规则 → 匹配 → 发送 → 记日志。

        新架构：从 TestPlan 读取 notification_channel_id 和 notification_template_code，
        调用新的通知服务发送。

        旧架构（向后兼容）：如果 TestPlan 未配置，则查询 NotificationRule 表。

        - 每条命中的规则独立发送并记录一条 notification_log；
        - 单条发送失败不影响其它规则；
        - 全流程异常被吞掉（返回已发送数），绝不影响调用方（计划运行）的事务。

        Returns:
            成功发送的通知条数。
        """
        sent = 0
        try:
            # 1. 查询 PlanRun → TestPlan 获取通知配置
            plan_run = (await self.db.execute(
                select(PlanRun).where(PlanRun.id == plan_run_id)
            )).scalar_one_or_none()
            if not plan_run:
                logger.warning("plan_run not found: %s", plan_run_id)
                return 0

            test_plan = (await self.db.execute(
                select(TestPlan).where(TestPlan.id == plan_run.plan_id)
            )).scalar_one_or_none()

            # 2. 新架构：使用 TestPlan 的通知配置
            if test_plan and test_plan.notification_channel_id:
                from app.modules.notification.service import NotificationService as NotificationSvc
                from app.modules.notification.repository import NotificationRepository

                # 判断事件类型
                event_type = f"execution.{plan_run.status}"  # execution.completed / execution.failed 等

                try:
                    # 获取通知渠道
                    repo = NotificationRepository(self.db)
                    channel = await repo.get_channel(test_plan.notification_channel_id)

                    if not channel or not channel.enabled:
                        logger.warning("Notification channel %s not found or disabled", test_plan.notification_channel_id)
                        return sent

                    # 计算通过率
                    pass_rate = (plan_run.passed_items / plan_run.total_items * 100) if plan_run.total_items > 0 else 0

                    # 构建通知上下文
                    context = {
                        "plan_run_id": plan_run_id,
                        "plan_id": test_plan.id,
                        "plan_name": test_plan.name,
                        "status": plan_run.status,
                        "project_id": project_id,
                        "total_items": plan_run.total_items,
                        "passed_items": plan_run.passed_items,
                        "failed_items": plan_run.failed_items,
                        "pass_rate": round(pass_rate, 2),
                    }

                    # 使用配置的模板代码
                    template_code = test_plan.notification_template_code or "execution_summary"
                    summary = f"测试计划 [{test_plan.name}] 执行{'失败' if plan_run.status == 'failed' else '完成'}，通过率 {pass_rate:.1f}%"

                    # 构建通知卡片
                    notification_svc = NotificationSvc(self.db)
                    card, recipient_meta = await notification_svc._build_card_with_recipients(
                        project_id,
                        template_code,
                        summary,
                        context,
                        "all_members",  # 默认通知所有项目成员
                        {}
                    )

                    # 创建投递记录
                    delivery = await repo.create_delivery_idempotent(
                        project_id=project_id,
                        rule_id=None,  # 直接通知，不关联规则
                        channel_id=channel.id,
                        event_id=f"plan_run:{plan_run_id}",
                        event_type=event_type,
                        status="pending",
                        attempt_count=0,
                        max_attempts=5,
                        next_attempt_at=datetime.now(timezone.utc),
                        payload_json={
                            "webhook_payload": card,
                            "recipient_meta": recipient_meta,
                            "context": context,
                            "recipient_type": "all_members",
                            "recipient_config": {},
                            "template_code": template_code,
                        },
                        error_message=None,
                        message_summary=summary[:300],
                    )

                    if delivery:
                        sent += 1
                        logger.info("plan_run notification created via new architecture: plan_run_id=%s, delivery_id=%s", plan_run_id, delivery.id)
                except Exception as exc:
                    logger.warning("plan_run notification failed via new architecture: %s", exc, exc_info=True)

                return sent

            # 3. 旧架构（向后兼容）：查询 NotificationRule
            rules = await self.rule_repo.list_enabled_by_trigger(project_id, "plan_run")
            if not rules:
                return 0

            # 聚合一次运行数据供所有规则复用
            report_service = ReportService(self.db)
            data = await report_service.gather_plan_run_data(project_id, plan_run_id)
            run_status = data["plan_run"]["status"]
            payload = self._build_feishu_card(data)

            for rule in rules:
                if not self._match_conditions(rule.conditions_json, run_status):
                    await self.log_repo.create(
                        rule_id=rule.id,
                        project_id=project_id,
                        plan_run_id=plan_run_id,
                        status="skipped",
                        request_json=None,
                        response_json=None,
                        error_message="未命中触发条件",
                    )
                    continue
                try:
                    response = await self._post_webhook(rule.webhook_url, payload)
                    await self.log_repo.create(
                        rule_id=rule.id,
                        project_id=project_id,
                        plan_run_id=plan_run_id,
                        status="sent",
                        request_json=payload,
                        response_json=response,
                    )
                    sent += 1
                except Exception as exc:
                    logger.warning("通知发送失败 rule_id=%s: %s", rule.id, exc)
                    await self.log_repo.create(
                        rule_id=rule.id,
                        project_id=project_id,
                        plan_run_id=plan_run_id,
                        status="failed",
                        request_json=payload,
                        error_message=str(exc),
                    )
            await self.db.commit()
        except Exception:
            logger.exception("dispatch_plan_run_notifications failed plan_run_id=%s", plan_run_id)
            try:
                await self.db.rollback()
            except Exception:
                pass
        return sent
