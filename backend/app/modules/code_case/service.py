"""
代码用例 Service 层

核心逻辑：
1. 扫描 code_testcases 目录，按 @case(module="A-B-C") 自动建立模块层级树
2. 用例落库（按 文件路径+函数名 幂等），文件消失走软删除、重现则恢复
"""
import asyncio
import logging
import uuid
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ResourceNotFoundError, ValidationError
from app.db.models.code_case import CodeCaseModule, CodeTestCase
from app.modules.code_case.decorators import parse_module_path, MODULE_SEPARATOR
from app.modules.code_case.executor import execute_case
from app.modules.code_case.repository import (
    CodeCaseExecutionRepository, CodeCaseModuleRepository, CodeTestCaseRepository,
)
from app.modules.code_case.scanner import scan_code_testcases
from app.schemas.code_case import (
    BatchResult, BatchSummary, CodeCaseDetail, CodeCaseListItem, CodeCasePage,
    CodeCaseStats, CodeModuleCreate, CodeModuleInfo, CodeModuleTreeNode,
    CodeModuleUpdate, ExecuteRequest, ExecutionDetail, ExecutionInfo,
    ExecutionPage, ScanResult,
)

logger = logging.getLogger(__name__)


def get_code_testcases_dir() -> Path:
    """
    code_testcases 目录：与 app 同级
    backend/
    ├── app/
    └── code_testcases/   <- 扫描目标
    """
    configured = getattr(settings, "code_testcases_dir", None)
    if configured:
        return Path(configured)
    return _resolve_code_testcases_dir()


def _resolve_code_testcases_dir() -> Path:
    """定位 code_testcases 目录，兼容三种运行方式：

    1. pip 安装 wheel（生产镜像）：code_testcases 作为顶层包与 app 同级安装在
       site-packages 下，通过 import 拿到其真实路径，不依赖进程 cwd。
    2. 源码运行（本地开发 / COPY 全量代码的镜像）：回退到仓库根下的 code_testcases。
    3. 均不存在时回退到 cwd/code_testcases（保持旧行为，便于日志提示）。
    """
    try:
        import code_testcases as _ctc
        pkg_path = getattr(_ctc, "__path__", None)
        if pkg_path:
            return Path(list(pkg_path)[0])
        if getattr(_ctc, "__file__", None):
            return Path(_ctc.__file__).parent
    except Exception:
        pass
    # 源码布局：service.py 位于 app/modules/code_case/ 下，向上 4 级到 backend 根
    repo_root = Path(__file__).resolve().parents[3]
    candidate = repo_root / "code_testcases"
    if candidate.is_dir():
        return candidate
    return Path.cwd() / "code_testcases"


class CodeCaseModuleService:
    """用例模块管理"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CodeCaseModuleRepository(db)

    async def ensure_module_path(self, module_str: str,
                                 user_id: Optional[int] = None,
                                 project_id: Optional[int] = None) -> tuple[Optional[int], int]:
        """
        按 "支付中心-支付渠道-支付宝" 逐级 get-or-create，返回 (最小层级模块ID, 新建数量)

        已存在的层级直接复用；只补齐缺失的层级。project_id 传入时模块与项目绑定。
        """
        segments = parse_module_path(module_str)
        if not segments:
            return None, 0

        parent_id: Optional[int] = None
        created = 0
        for depth, name in enumerate(segments, start=1):
            existing = await self.repo.find_by_parent_and_name(parent_id, name, project_id=project_id)
            if existing:
                parent_id = existing.id
                continue
            full_path = MODULE_SEPARATOR.join(segments[:depth])
            obj = await self.repo.create(
                name=name, parent_id=parent_id, level=depth,
                full_path=full_path, user_id=user_id,
                project_id=project_id,
            )
            created += 1
            parent_id = obj.id

        return parent_id, created

    async def create(self, data: CodeModuleCreate,
                     user_id: Optional[int] = None,
                     project_id: Optional[int] = None) -> CodeModuleInfo:
        """手工新增模块（页面「新增用例模块」）"""
        level = 1
        full_path = data.name
        if data.parent_id is not None:
            parent = await self.repo.get(data.parent_id)
            if not parent:
                raise ValidationError("父模块不存在")
            level = parent.level + 1
            full_path = f"{parent.full_path}{MODULE_SEPARATOR}{data.name}"

        dup = await self.repo.find_by_parent_and_name(data.parent_id, data.name, project_id=project_id)
        if dup:
            raise ValidationError(f"同级下已存在同名模块: {data.name}")

        obj = await self.repo.create(
            name=data.name, parent_id=data.parent_id, level=level,
            full_path=full_path, user_id=user_id, sort_order=data.sort_order,
            project_id=project_id,
        )
        await self.db.commit()
        return CodeModuleInfo.model_validate(obj)

    async def update(self, module_id: int, data: CodeModuleUpdate,
                     user_id: Optional[int] = None) -> CodeModuleInfo:
        """更新模块（支持名称编辑，改名会级联刷新子孙的 full_path）"""
        obj = await self.repo.get(module_id)
        if not obj:
            raise ResourceNotFoundError("模块不存在")

        updates: dict = {"updated_by": user_id}
        renamed = data.name is not None and data.name != obj.name
        if renamed:
            dup = await self.repo.find_by_parent_and_name(obj.parent_id, data.name)
            if dup and dup.id != module_id:
                raise ValidationError(f"同级下已存在同名模块: {data.name}")
            updates["name"] = data.name
            segs = parse_module_path(obj.full_path)
            segs[-1] = data.name
            updates["full_path"] = MODULE_SEPARATOR.join(segs)
        if data.sort_order is not None:
            updates["sort_order"] = data.sort_order

        obj = await self.repo.update(obj, **updates)
        if renamed:
            await self._refresh_descendants(obj)
            await self._resync_case_module_str(obj)
        await self.db.commit()
        return CodeModuleInfo.model_validate(obj)

    async def _refresh_descendants(self, parent: CodeCaseModule) -> None:
        """父模块改名后，递归刷新所有子孙的 full_path"""
        children = await self.repo.list_children(parent.id)
        for child in children:
            new_path = f"{parent.full_path}{MODULE_SEPARATOR}{child.name}"
            if child.full_path != new_path:
                await self.repo.update(child, full_path=new_path)
            await self._refresh_descendants(child)
            await self._resync_case_module_str(child)

    async def _resync_case_module_str(self, module: CodeCaseModule) -> None:
        """模块 full_path 变化后，同步该模块下用例的 module 字段"""
        case_repo = CodeTestCaseRepository(self.db)
        _, cases = await case_repo.paginate(module_id=module.id, page_size=9999)
        for c in cases:
            if c.module != module.full_path:
                await case_repo.update(c, module=module.full_path)

    async def delete(self, module_id: int, cascade: bool = False) -> None:
        """
        删除模块层级

        cascade=False: 存在子模块或用例时拒绝删除（安全默认）
        cascade=True:  连带删除所有子孙模块，并解除其下用例的模块归属
        """
        obj = await self.repo.get(module_id)
        if not obj:
            raise ResourceNotFoundError("模块不存在")

        children = await self.repo.list_children(module_id)
        case_count = await self.repo.count_cases(module_id, include_deleted=True)

        if not cascade and (children or case_count):
            raise ValidationError(
                f"模块下存在 {len(children)} 个子模块、{case_count} 个用例，"
                f"如需一并删除请传 cascade=true"
            )

        await self._delete_recursive(obj)
        await self.db.commit()

    async def _delete_recursive(self, obj: CodeCaseModule) -> None:
        for child in await self.repo.list_children(obj.id):
            await self._delete_recursive(child)
        case_repo = CodeTestCaseRepository(self.db)
        _, cases = await case_repo.paginate(module_id=obj.id, page_size=9999)
        for c in cases:
            await case_repo.update(c, module_id=None)
        await self.repo.delete(obj)

    async def get_tree(self, project_id: Optional[int] = None) -> list[CodeModuleTreeNode]:
        """构建模块树（含用例数量，父级累计子级）。project_id 有值时只返回该项目的模块，用例数也按项目统计。"""
        modules = await self.repo.list_all(project_id=project_id)
        nodes: dict[int, CodeModuleTreeNode] = {}
        for m in modules:
            direct = await self.repo.count_cases(m.id, project_id=project_id)
            nodes[m.id] = CodeModuleTreeNode(
                id=m.id, parent_id=m.parent_id, name=m.name, level=m.level,
                full_path=m.full_path, sort_order=m.sort_order,
                case_count=direct, total_case_count=direct, children=[],
            )

        roots: list[CodeModuleTreeNode] = []
        for m in modules:
            node = nodes[m.id]
            if m.parent_id and m.parent_id in nodes:
                nodes[m.parent_id].children.append(node)
            else:
                roots.append(node)

        def accumulate(n: CodeModuleTreeNode) -> int:
            n.total_case_count = n.case_count + sum(accumulate(c) for c in n.children)
            return n.total_case_count

        for r in roots:
            accumulate(r)
        return roots

    async def collect_subtree_ids(self, module_id: int) -> list[int]:
        """取模块自身 + 所有子孙的ID（用于按模块过滤用例，含子级）"""
        ids = [module_id]
        for child in await self.repo.list_children(module_id):
            ids.extend(await self.collect_subtree_ids(child.id))
        return ids


class CodeCaseService:
    """代码用例查询"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = CodeTestCaseRepository(db)
        self.module_svc = CodeCaseModuleService(db)

    @staticmethod
    def _to_item(obj: CodeTestCase, last_exec=None) -> CodeCaseListItem:
        return CodeCaseListItem(
            id=obj.id, module_id=obj.module_id, module=obj.module,
            module_path=parse_module_path(obj.module),
            name=obj.name, level=obj.level, description=obj.description,
            file_path=obj.file_path, function_name=obj.function_name,
            line_number=obj.line_number, status=obj.status,
            last_run_at=obj.last_run_at,
            created_at=obj.created_at, updated_at=obj.updated_at,
            last_execution_id=last_exec.id if last_exec else None,
            last_duration_ms=last_exec.duration_ms if last_exec else None,
            last_message=last_exec.message if last_exec else None,
        )

    async def paginate(self, module_id: Optional[int] = None,
                       include_children: bool = True,
                       level: Optional[str] = None,
                       keyword: Optional[str] = None,
                       project_id: Optional[int] = None,
                       page: int = 1, page_size: int = 20) -> CodeCasePage:
        module_ids = None
        if module_id is not None and include_children:
            module_ids = await self.module_svc.collect_subtree_ids(module_id)
            module_id = None

        total, rows = await self.repo.paginate(
            module_id=module_id, module_ids=module_ids, level=level,
            keyword=keyword, project_id=project_id, page=page, page_size=page_size,
        )
        exec_repo = CodeCaseExecutionRepository(self.db)
        latest = await exec_repo.latest_for_cases([r.id for r in rows])
        return CodeCasePage(
            total=total, page=page, page_size=page_size,
            items=[self._to_item(r, latest.get(r.id)) for r in rows],
        )

    async def get_detail(self, case_id: int) -> CodeCaseDetail:
        obj = await self.repo.get(case_id)
        if not obj or obj.is_deleted:
            raise ResourceNotFoundError("用例不存在")
        exec_repo = CodeCaseExecutionRepository(self.db)
        latest = await exec_repo.latest_for_cases([obj.id])
        item = self._to_item(obj, latest.get(obj.id))
        return CodeCaseDetail(**item.model_dump(), code_snippet=obj.code_snippet)

    async def stats(self, project_id: Optional[int] = None) -> CodeCaseStats:
        raw = await self.repo.stats(project_id=project_id)
        return CodeCaseStats(**raw)


class CodeCaseScanService:
    """扫描代码用例并同步到库"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.case_repo = CodeTestCaseRepository(db)
        self.module_svc = CodeCaseModuleService(db)

    async def scan(self, user_id: Optional[int] = None,
                   project_id: Optional[int] = None) -> ScanResult:
        """
        扫描 code_testcases 目录并同步：
        - 新用例入库，模块层级不存在则自动逐级新增
        - 已有用例更新元信息（含模块变更）
        - 磁盘上已消失的用例标记软删除；重新出现则恢复
        - 项目归属完全由 @case(project="项目名") 决定，扫描器自动查库解析；
          找不到匹配项目名则 project_id 留 NULL（全局可见）
        - 已有记录的 project_id 若因 @case 修改而变化，会自动更新

        project_id 有值时只同步该项目：
        - 只处理 @case(project=) 解析到该项目的用例，以及库里原本属于该项目的用例
          （后者 @case 改成别的项目时会随之迁出）
        - 其他项目和全局用例跳过，计入 skipped
        - 只软删除该项目下磁盘上已不存在的用例
        """
        if project_id is not None:
            from app.db.models.project import Project
            if await self.db.get(Project, project_id) is None:
                raise ResourceNotFoundError(f"项目不存在: {project_id}")

        root = get_code_testcases_dir()
        report = scan_code_testcases(root)

        result = ScanResult(
            scanned_files=report.scanned_files,
            scanned_cases=len(report.cases),
            errors=list(report.errors),
            project_id=project_id,
        )

        # 缓存：项目名 -> project_id（避免重复查库）
        _project_id_cache: dict[str, Optional[int]] = {}

        async def _resolve_project_id(project_name: str) -> Optional[int]:
            """按项目名查询 project_id，找不到则返回 None（全局可见）"""
            if not project_name:
                return None
            if project_name in _project_id_cache:
                return _project_id_cache[project_name]
            from app.db.models.project import Project
            from sqlalchemy import select as sa_select
            r = await self.db.execute(
                sa_select(Project).where(Project.name == project_name)
            )
            proj = r.scalars().first()
            pid = proj.id if proj else None
            _project_id_cache[project_name] = pid
            if pid is None and project_name:
                logger.warning("@case(project=%r) 找不到对应项目，将作为全局用例入库", project_name)
            return pid

        # 磁盘上存在的全部用例（含按项目扫描时跳过的），用于判断软删除
        seen: set[tuple[str, str]] = set()

        for sc in report.cases:
            key = (sc.file_path, sc.function_name)
            if key in seen:
                result.errors.append(
                    f"{sc.file_path}: 函数 {sc.function_name} 重复，已跳过"
                )
                continue
            seen.add(key)

            # 项目归属完全由 @case(project=) 决定
            case_project_id = await _resolve_project_id(sc.project)

            existing = await self.case_repo.find_by_identity(
                sc.file_path, sc.function_name
            )
            if project_id is not None and case_project_id != project_id and (
                existing is None or existing.project_id != project_id
            ):
                result.skipped += 1
                continue

            module_id, created_cnt = await self.module_svc.ensure_module_path(
                sc.module, user_id, project_id=case_project_id
            )
            result.modules_created += created_cnt

            if existing is None:
                await self.case_repo.create(
                    module_id=module_id, module=sc.module, name=sc.name,
                    level=sc.level, description=sc.description,
                    file_path=sc.file_path, function_name=sc.function_name,
                    code_snippet=sc.code_snippet, line_number=sc.line_number,
                    status="idle", is_deleted=False, project_id=case_project_id,
                    created_by=user_id, updated_by=user_id,
                )
                result.created += 1
                continue

            updates = {
                "module_id": module_id, "module": sc.module, "name": sc.name,
                "level": sc.level, "description": sc.description,
                "code_snippet": sc.code_snippet, "line_number": sc.line_number,
                "project_id": case_project_id,
                "updated_by": user_id,
            }
            if existing.is_deleted:
                updates.update({"is_deleted": False, "deleted_at": None})
                result.restored += 1
            else:
                result.updated += 1
            await self.case_repo.update(existing, **updates)

        # 磁盘上不存在的用例 -> 软删除
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for obj in await self.case_repo.list_all(include_deleted=False, project_id=project_id):
            if (obj.file_path, obj.function_name) not in seen:
                await self.case_repo.update(
                    obj, is_deleted=True, deleted_at=now, updated_by=user_id
                )
                result.deleted += 1

        # 更新所有模块的 is_used：模块下有活跃用例则 True，否则 False
        for module in await self.module_svc.repo.list_all(used_only=False):
            has_cases = await self.module_svc.repo.count_cases(module.id) > 0
            if module.is_used != has_cases:
                await self.module_svc.repo.update(module, is_used=has_cases)

        await self.db.commit()
        logger.info(
            "代码用例扫描完成: 项目=%s 文件=%d 用例=%d 新增=%d 更新=%d 恢复=%d 删除=%d 跳过=%d 模块新增=%d",
            project_id if project_id is not None else "全部",
            result.scanned_files, result.scanned_cases, result.created,
            result.updated, result.restored, result.deleted, result.skipped,
            result.modules_created,
        )
        return result


# 后台执行任务的强引用，防止 asyncio.create_task 的任务被 GC 提前回收
_BACKGROUND_TASKS: set = set()

# pending/running 超过该秒数视为中断（服务重启等），由 reap 自愈
STALE_AFTER_SECONDS = 3600


class CodeCaseExecutionService:
    """代码用例执行"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.exec_repo = CodeCaseExecutionRepository(db)
        self.case_repo = CodeTestCaseRepository(db)
        self.module_svc = CodeCaseModuleService(db)

    async def _resolve_cases(self, req: ExecuteRequest) -> list[CodeTestCase]:
        """按请求解析出要执行的用例集合"""
        if req.case_ids:
            cases = await self.case_repo.list_by_ids(req.case_ids)
            found = {c.id for c in cases}
            missing = [i for i in req.case_ids if i not in found]
            if missing:
                raise ValidationError(f"用例不存在或已失效: {missing}")
            return cases

        if req.module_id is not None:
            module_ids = await self.module_svc.collect_subtree_ids(req.module_id)
            return await self.case_repo.list_by_module_ids(module_ids)

        if req.all_cases:
            return await self.case_repo.list_all(include_deleted=False)

        raise ValidationError("需指定 case_ids、module_id 或 all_cases 之一")

    async def start(self, req: ExecuteRequest,
                    user_id: Optional[int] = None) -> BatchResult:
        """
        发起执行：建 pending 记录后立即返回 batch_id，通过 arq 异步执行。
        前端拿 batch_id 轮询结果。

        批量执行时按传入的 case_ids 顺序逐个执行（前端勾选顺序即执行顺序）。
        """
        from sqlalchemy import update as sa_update

        await self.exec_repo.reap_stale(STALE_AFTER_SECONDS)

        cases = await self._resolve_cases(req)
        if not cases:
            raise ValidationError("没有可执行的用例")

        batch_id = uuid.uuid4().hex

        created: list = []
        for c in cases:
            obj = await self.exec_repo.create(
                batch_id=batch_id, case_id=c.id, case_name=c.name,
                module=c.module, level=c.level, file_path=c.file_path,
                function_name=c.function_name, status="pending",
                trigger_by=user_id,
            )
            created.append(obj)

        await self.db.commit()

        from app.workers.code_case_tasks import enqueue_code_case_batch

        try:
            job_id = await enqueue_code_case_batch(batch_id)
            logger.info("Code case batch %s enqueued to arq, job_id=%s, cases=%d",
                        batch_id, job_id, len(created))
        except Exception as e:
            logger.exception("Failed to enqueue code case batch %s", batch_id)
            from app.db.models.code_case import CodeCaseExecution
            await self.db.execute(
                sa_update(CodeCaseExecution)
                .where(CodeCaseExecution.batch_id == batch_id,
                       CodeCaseExecution.status == "pending")
                .values(status="error", message=f"投递失败: {str(e)}",
                         finished_at=_utcnow())
            )
            await self.db.commit()

        logger.info("代码用例执行已提交: batch=%s 用例数=%d", batch_id, len(created))
        return await self.get_batch(batch_id)

    async def get_batch(self, batch_id: str) -> BatchResult:
        """批次结果（汇总 + 明细），供前端轮询"""
        rows = await self.exec_repo.list_by_batch(batch_id)
        if not rows:
            raise ResourceNotFoundError("执行批次不存在")

        summary = BatchSummary(batch_id=batch_id, total=len(rows))
        for r in rows:
            if hasattr(summary, r.status):
                setattr(summary, r.status, getattr(summary, r.status) + 1)
            summary.duration_ms += r.duration_ms or 0

        done = summary.passed + summary.failed + summary.error + summary.timeout
        summary.finished = done == summary.total
        summary.pass_rate = round(summary.passed / done * 100, 1) if done else 0.0

        return BatchResult(
            summary=summary,
            items=[ExecutionInfo.model_validate(r) for r in rows],
        )

    async def get_execution(self, exec_id: int) -> ExecutionDetail:
        """单条执行详情（含完整日志和堆栈）"""
        obj = await self.exec_repo.get(exec_id)
        if not obj:
            raise ResourceNotFoundError("执行记录不存在")
        return ExecutionDetail.model_validate(obj)

    async def list_executions(self, case_id: Optional[int] = None,
                              batch_id: Optional[str] = None,
                              status: Optional[str] = None,
                              page: int = 1, page_size: int = 20) -> ExecutionPage:
        """执行历史列表"""
        total, rows = await self.exec_repo.paginate(
            case_id=case_id, batch_id=batch_id, status=status,
            page=page, page_size=page_size,
        )
        return ExecutionPage(
            total=total, page=page, page_size=page_size,
            items=[ExecutionInfo.model_validate(r) for r in rows],
        )


async def _run_batch(batch_id: str, payload: list[dict], timeout: int) -> None:
    """
    后台顺序执行一个批次

    用独立会话：请求的会话在响应返回后就关了，不能带到后台任务里。
    顺序执行而非并发，避免一次点"执行全部"就打满机器。
    """
    from app.db.base import AsyncSessionLocal

    for item in payload:
        try:
            async with AsyncSessionLocal() as db:
                repo = CodeCaseExecutionRepository(db)
                obj = await repo.get(item["exec_id"])
                if obj is None or obj.status not in ("pending",):
                    continue
                await repo.update(obj, status="running", started_at=_utcnow())
                await db.commit()

            result = await execute_case(
                item["abs_path"], item["function_name"], timeout=timeout
            )

            async with AsyncSessionLocal() as db:
                repo = CodeCaseExecutionRepository(db)
                case_repo = CodeTestCaseRepository(db)
                obj = await repo.get(item["exec_id"])
                if obj is not None:
                    finished = _utcnow()
                    await repo.update(
                        obj,
                        status=result["status"],
                        message=result.get("message") or None,
                        logs=result.get("logs") or None,
                        traceback=result.get("traceback") or None,
                        duration_ms=result.get("duration_ms"),
                        finished_at=finished,
                    )
                    case = await case_repo.get(item["case_id"])
                    if case is not None:
                        await case_repo.update(
                            case, status=result["status"], last_run_at=finished
                        )
                await db.commit()

        except Exception:
            logger.exception("执行用例失败: exec_id=%s", item.get("exec_id"))
            try:
                async with AsyncSessionLocal() as db:
                    repo = CodeCaseExecutionRepository(db)
                    obj = await repo.get(item["exec_id"])
                    if obj is not None:
                        await repo.update(
                            obj, status="error", finished_at=_utcnow(),
                            message="执行调度异常，详见服务日志",
                        )
                    await db.commit()
            except Exception:
                logger.exception("回写执行失败状态时再次异常")

    logger.info("代码用例批次执行结束: batch=%s", batch_id)


def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)
