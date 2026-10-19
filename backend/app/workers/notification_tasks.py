"""arq tasks and wake-up helpers for durable notification deliveries."""
from __future__ import annotations

from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal


logger = get_logger(__name__)


async def process_notification_delivery_task(ctx: dict, delivery_id: int) -> str:
    async with AsyncSessionLocal() as db:
        try:
            from app.modules.notification.service import NotificationService

            return await NotificationService(db).process_delivery(delivery_id)
        except Exception:
            await db.rollback()
            logger.exception("notification delivery task failed delivery_id=%s", delivery_id)
            raise


async def notification_recovery_task(ctx: dict) -> int:
    """Wake due and stale database deliveries; row locking prevents double processing."""
    async with AsyncSessionLocal() as db:
        try:
            from app.modules.notification.service import NotificationService

            ids = await NotificationService(db).due_delivery_ids(limit=100)
        except Exception:
            logger.exception("notification recovery scan failed")
            return 0
    for delivery_id in ids:
        try:
            await enqueue_notification_delivery(delivery_id)
        except Exception:
            logger.warning("failed to wake notification delivery_id=%s", delivery_id)
    return len(ids)


async def enqueue_notification_delivery(delivery_id: int) -> str | None:
    from app.workers.tasks import EXECUTION_QUEUE, get_arq_redis

    pool = await get_arq_redis()
    job = await pool.enqueue_job(
        "process_notification_delivery_task",
        delivery_id,
        _queue_name=EXECUTION_QUEUE,
    )
    return job.job_id if job else None
