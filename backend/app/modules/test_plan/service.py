"""WP-07 test plan application services."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ResourceNotFoundError, ValidationError
from app.db.models.test_plan import PlanRun, PlanRunItem, Schedule, TestPlan
from app.modules.test_plan.repository import ScheduleRepository, TestPlanRepository
from app.schemas.test_plan import (
    PlanRunCreate,
    PlanRunInfo,
    PlanRunItemInfo,
    PlanItemInfo,
    ScheduleCreate,
    ScheduleInfo,
    ScheduleUpdate,
    TestPlanCreate,
    TestPlanInfo,
    TestPlanUpdate,
)
from app.modules.test_plan.dispatcher import TERMINAL_STATUSES
from app.modules.test_plan.mixed_dispatcher import dispatch_mixed_plan_run


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _plan_run_key(project_id: int, plan_id: int, key: str) -> str:
    raw = f"plan:{project_id}:{plan_id}:{key}"
    return raw if len(raw) <= 100 else f"plan:{hashlib.sha256(raw.encode()).hexdigest()}"


def _execution_key(plan_run_id: int, case_id: int) -> str:
    return hashlib.sha256(f"plan-run:{plan_run_id}:case:{case_id}".encode()).hexdigest()


def _step_count(compiled_json: dict | None) -> int:
    if not compiled_json:
        return 0
    nodes = compiled_json.get("nodes") or {}
    order = compiled_json.get("order") or list(nodes)
    return sum(
        1 for node_id in order
        if (nodes.get(node_id) or {}).get("type") not in {"start", "end"}
    )


def _next_run(cron_expression: str, timezone_name: str) -> datetime:
    try:
        tz = ZoneInfo(timezone_name)
        trigger = CronTrigger.from_crontab(cron_expression, timezone=tz)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValidationError(f"Invalid cron expression or timezone: {exc}") from exc
    next_run = trigger.get_next_fire_time(None, datetime.now(tz))
    if next_run is None:
        raise ValidationError("Cron expression has no next run time")
    return next_run.astimezone(timezone.utc).replace(tzinfo=None)


class TestPlanService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = TestPlanRepository(db)

    async def _validate_notification_channel(self, project_id: int, channel_id: int | None):
        """验证通知渠道是否属于当前项目"""
        if channel_id is None:
            return None
        from app.modules.notification.repository import NotificationRepository
        channel = await NotificationRepository(self.db).get_channel(channel_id)
        if not channel or channel.project_id != project_id:
            raise ValidationError("Notification channel does not belong to this project")
        return channel

    async def _normalize_items(self, project_id: int, items) -> list[dict]:
        """标准化混合用例项（支持手工用例和代码用例）"""
        from app.modules.test_plan.service_extended import normalize_mixed_items
        return await normalize_mixed_items(self.db, project_id, items)

    async def _to_info(self, plan: TestPlan) -> TestPlanInfo:
        """构建测试计划详情（支持混合用例类型）"""
        from app.modules.test_plan.service_extended import build_mixed_plan_item_info

        info = TestPlanInfo.model_validate(plan)
        info.items = []
        for item in await self.repo.list_items(plan.id):
            item_info = await build_mixed_plan_item_info(self.db, item, plan.project_id)
            info.items.append(item_info)
        return info

    async def create(self, project_id: int, data: TestPlanCreate, user_id: int) -> TestPlanInfo:
        await self._validate_notification_channel(project_id, data.notification_channel_id)
        items = await self._normalize_items(project_id, data.items)
        plan = TestPlan(
            project_id=project_id,
            **data.model_dump(exclude={"items"}),
            created_by=user_id,
            updated_by=user_id,
        )
        self.db.add(plan)
        await self.db.flush()
        await self.repo.replace_items(plan.id, project_id, items)
        await self.db.commit()
        await self.db.refresh(plan)
        return await self._to_info(plan)

    async def get(self, project_id: int, plan_id: int) -> TestPlanInfo:
        plan = await self.repo.get(plan_id)
        if not plan or plan.project_id != project_id:
            raise ResourceNotFoundError("Test plan not found")
        return await self._to_info(plan)

    async def list(self, project_id: int, status: str | None, page: int, page_size: int) -> dict:
        total, plans = await self.repo.list(project_id, status, page, page_size)
        return {"total": total, "items": await self._to_info_batch(plans)}

    async def _to_info_batch(self, plans: list[TestPlan]) -> list[TestPlanInfo]:
        """批量组装多个计划的详情（支持混合用例类型）"""
        from app.modules.test_plan.service_extended import build_mixed_plan_item_info

        if not plans:
            return []

        plan_ids = [plan.id for plan in plans]
        items = await self.repo.list_items_for_plans(plan_ids)

        infos = []
        for plan in plans:
            info = TestPlanInfo.model_validate(plan)
            info.items = []
            plan_items = [item for item in items if item.plan_id == plan.id]
            for item in plan_items:
                item_info = await build_mixed_plan_item_info(self.db, item, plan.project_id)
                info.items.append(item_info)
            infos.append(info)

        from app.core.user_utils import populate_user_names
        await populate_user_names(self.db, infos)
        return infos

    async def update(self, project_id: int, plan_id: int, data: TestPlanUpdate,
                     user_id: int) -> TestPlanInfo:
        plan = await self.repo.get(plan_id)
        if not plan or plan.project_id != project_id:
            raise ResourceNotFoundError("Test plan not found")
        values = data.model_dump(exclude_unset=True, exclude={"items"})
        if "notification_channel_id" in values:
            await self._validate_notification_channel(project_id, values["notification_channel_id"])
        for name, value in values.items():
            setattr(plan, name, value)
        plan.updated_by = user_id
        if data.items is not None:
            items = await self._normalize_items(project_id, data.items)
            await self.repo.replace_items(plan.id, project_id, items)
        await self.db.commit()
        await self.db.refresh(plan)
        return await self._to_info(plan)

    async def delete(self, project_id: int, plan_id: int, user_id: int) -> None:
        plan = await self.repo.get(plan_id)
        if not plan or plan.project_id != project_id:
            raise ResourceNotFoundError("Test plan not found")
        if await self.repo.list_items(plan_id):
            await self.repo.replace_items(plan_id, project_id, [])
        plan.soft_delete(user_id)
        await self.db.commit()

    async def sync_case_versions(self, project_id: int, plan_id: int, case_ids: list[int] | None = None) -> TestPlanInfo:
        """同步用例到最新版本（代码用例不支持版本同步）"""
        raise ValidationError("Code cases do not support version sync")

    async def run(self, project_id: int, plan_id: int, data: PlanRunCreate,
                  user_id: int, idempotency_key: str | None,
                  trigger_type: str = "manual") -> tuple[PlanRunInfo, bool]:
        plan = await self.repo.get(plan_id)
        if not plan or plan.project_id != project_id:
            raise ResourceNotFoundError("Test plan not found")
        normalized_key = _plan_run_key(project_id, plan_id, idempotency_key) if idempotency_key else None
        if normalized_key:
            existing = await self.repo.get_run_by_key(normalized_key)
            if existing:
                if existing.project_id != project_id or existing.plan_id != plan_id:
                    raise ValidationError("Idempotency key belongs to another plan run")
                await dispatch_mixed_plan_run(self.db, existing.id)
                return await self.get_run(project_id, existing.id), False

        items = [item for item in await self.repo.list_items(plan_id) if item.enabled]
        if not items:
            raise ValidationError("Test plan has no enabled automation cases")

        run = PlanRun(
            project_id=project_id,
            plan_id=plan_id,
            trigger_type=trigger_type,
            trigger_by=user_id,
            failure_strategy=data.failure_strategy or plan.failure_strategy,
            idempotency_key=normalized_key,
            total_items=len(items),
            status="pending",
            started_at=_now(),
        )
        self.db.add(run)
        await self.db.flush()

        for item in items:
            case_type = getattr(item, "case_type", "manual")

            if case_type == "code":
                from app.modules.code_case.repository import CodeTestCaseRepository, CodeCaseExecutionRepository
                code_case_repo = CodeTestCaseRepository(self.db)
                code_exec_repo = CodeCaseExecutionRepository(self.db)

                code_case = await code_case_repo.get(item.case_id)
                if not code_case or code_case.is_deleted:
                    raise ValidationError(f"Code case {item.case_id} not found or deleted")

                code_execution = await code_exec_repo.create(
                    batch_id=f"plan_run_{run.id}",
                    case_id=code_case.id,
                    case_name=code_case.name,
                    module=code_case.module,
                    level=code_case.level,
                    file_path=code_case.file_path,
                    function_name=code_case.function_name,
                    status="pending",
                    trigger_by=user_id,
                )

                self.db.add(PlanRunItem(
                    plan_run_id=run.id,
                    project_id=project_id,
                    case_id=item.case_id,
                    case_type="code",
                    case_version=item.case_version,
                    execution_id=None,
                    code_execution_id=code_execution.id,
                    sort_order=item.sort_order,
                    status="pending",
                ))
            else:
                raise ValidationError(f"Unsupported case type: {case_type}, only 'code' is supported")
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            if not normalized_key:
                raise
            existing = await self.repo.get_run_by_key(normalized_key)
            if not existing or existing.project_id != project_id or existing.plan_id != plan_id:
                raise
            await dispatch_mixed_plan_run(self.db, existing.id)
            return await self.get_run(project_id, existing.id), False
        await dispatch_mixed_plan_run(self.db, run.id)
        return await self.get_run(project_id, run.id), True

    async def get_run(self, project_id: int, run_id: int) -> PlanRunInfo:
        """获取运行详情（支持混合用例类型）"""
        run = await self.repo.get_run(run_id)
        if not run or run.project_id != project_id:
            raise ResourceNotFoundError("Plan run not found")
        if run.status not in TERMINAL_STATUSES:
            await dispatch_mixed_plan_run(self.db, run.id)
            run = await self.repo.get_run(run.id)
        await self.repo.sync_run(run)
        await self.db.commit()

        info = PlanRunInfo.model_validate(run)
        info.items = []
        items = await self.repo.list_run_items(run.id)

        for item in items:
            item_info = await self._build_run_item_info(self.db, item, project_id)
            info.items.append(item_info)

        return info

    async def list_runs(self, project_id: int, plan_id: int | None, status: str | None,
                        page: int, page_size: int,
                        trigger_type: str | None = None,
                        started_from=None, started_to=None) -> dict:
        """列表查询运行记录（支持混合用例类型）"""
        total, runs = await self.repo.list_runs(
            project_id, plan_id, status, page, page_size,
            trigger_type=trigger_type, started_from=started_from, started_to=started_to,
        )
        if not runs:
            return {"total": total, "items": []}

        # 对非终态 PlanRun 做轻量级 sync（检查 execution 是否已完成）
        stale_runs = [r for r in runs if r.status not in TERMINAL_STATUSES]
        if stale_runs:
            for run in stale_runs:
                await self.repo.sync_run(run)
            await self.db.commit()

        run_ids = [run.id for run in runs]
        items = await self.repo.list_run_items_for_runs(run_ids)

        # 批量组装运行详情
        result = []
        for run in runs:
            info = PlanRunInfo.model_validate(run)
            info.items = []
            run_items = [item for item in items if item.plan_run_id == run.id]
            for item in run_items:
                item_info = await self._build_run_item_info(self.db, item, project_id)
                info.items.append(item_info)
            result.append(info)

        return {"total": total, "items": result}

    @staticmethod
    async def _build_run_item_info(db: AsyncSession, item, project_id: int) -> PlanRunItemInfo:
        """构建执行项信息（支持混合用例类型）"""
        from app.modules.test_plan.service_extended import build_mixed_run_item_info
        return await build_mixed_run_item_info(db, item, project_id)

    async def cancel_run(self, project_id: int, run_id: int) -> PlanRunInfo:
        run = await self.repo.get_run(run_id)
        if not run or run.project_id != project_id:
            raise ResourceNotFoundError("Plan run not found")

        items = await self.repo.list_run_items(run.id)

        # 取消代码用例执行
        from sqlalchemy import update
        from app.db.models.code_case import CodeCaseExecution
        code_exec_ids = [item.code_execution_id for item in items
                        if item.code_execution_id is not None]
        if code_exec_ids:
            await self.db.execute(
                update(CodeCaseExecution)
                .where(CodeCaseExecution.id.in_(code_exec_ids))
                .values(status="cancelled", finished_at=_now())
            )

        # 对于没有execution的pending item，直接标记为cancelled
        for item in items:
            if (item.execution_id is None and item.code_execution_id is None
                and item.status in ("pending", "queued")):
                item.status = "cancelled"

        await self.db.commit()
        await self.repo.sync_run(run)
        await self.db.commit()
        return await self.get_run(project_id, run.id)


class ScheduleService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ScheduleRepository(db)
        self.plan_repo = TestPlanRepository(db)

    async def _plan(self, project_id: int, plan_id: int) -> TestPlan:
        plan = await self.plan_repo.get(plan_id)
        if not plan or plan.project_id != project_id:
            raise ResourceNotFoundError("Test plan not found")
        return plan

    async def create(self, project_id: int, plan_id: int, data: ScheduleCreate,
                     user_id: int) -> ScheduleInfo:
        await self._plan(project_id, plan_id)
        schedule = Schedule(
            project_id=project_id,
            plan_id=plan_id,
            **data.model_dump(),
            next_run_at=_next_run(data.cron_expression, data.timezone) if data.enabled else None,
            created_by=user_id,
            updated_by=user_id,
        )
        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        return ScheduleInfo.model_validate(schedule)

    async def list(self, project_id: int) -> list[ScheduleInfo]:
        return [ScheduleInfo.model_validate(item) for item in await self.repo.list(project_id)]

    async def update(self, project_id: int, schedule_id: int, data: ScheduleUpdate,
                     user_id: int) -> ScheduleInfo:
        schedule = await self.repo.get(schedule_id)
        if not schedule or schedule.project_id != project_id:
            raise ResourceNotFoundError("Schedule not found")
        values = data.model_dump(exclude_unset=True)
        if "plan_id" in values:
            await self._plan(project_id, values["plan_id"])
        cron = values.get("cron_expression", schedule.cron_expression)
        timezone_name = values.get("timezone", schedule.timezone)
        enabled = values.get("enabled", schedule.enabled)
        for name, value in values.items():
            setattr(schedule, name, value)
        schedule.next_run_at = _next_run(cron, timezone_name) if enabled else None
        schedule.updated_by = user_id
        await self.db.commit()
        await self.db.refresh(schedule)
        return ScheduleInfo.model_validate(schedule)

    async def delete(self, project_id: int, schedule_id: int, user_id: int) -> None:
        schedule = await self.repo.get(schedule_id)
        if not schedule or schedule.project_id != project_id:
            raise ResourceNotFoundError("Schedule not found")
        schedule.soft_delete(user_id)
        await self.db.commit()