"""Plan-run orchestration on top of the WP-06 execution queue."""
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.test_plan import PlanRun, PlanRunItem
from app.workers.tasks import enqueue_execution


TERMINAL_STATUSES = {"passed", "failed", "error", "cancelled", "timeout"}
FAILED_STATUSES = {"failed", "error", "timeout"}
logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def dispatch_plan_run(db: AsyncSession, run_id: int) -> list[int]:
    """
    调度测试计划运行（支持混合用例类型）

    代码用例通过混合调度器顺序执行，手工用例保持原有并发逻辑
    """
    from app.modules.test_plan.mixed_dispatcher import dispatch_mixed_plan_run

    # 使用混合调度器
    result = await dispatch_mixed_plan_run(db, run_id)
    return [result.get("enqueued_count", 0)]


async def _notify_plan_run_finished(db: AsyncSession, project_id: int, run_id: int) -> None:
    """计划运行落终态后触发通知发送。绝不向上抛异常，避免影响调用方。"""
    try:
        from app.modules.report.service import NotificationService

        await NotificationService(db).dispatch_plan_run_notifications(project_id, run_id)
    except Exception:
        logger.exception("plan run notification dispatch failed run_id=%s", run_id)


async def advance_plan_for_execution(db: AsyncSession, execution_id: int) -> None:
    """Advance the owning plan run after an execution reaches a terminal state."""
    run_id = (await db.execute(
        select(PlanRunItem.plan_run_id)
        .where(PlanRunItem.execution_id == execution_id)
    )).scalar_one_or_none()
    if run_id is not None:
        await dispatch_plan_run(db, run_id)