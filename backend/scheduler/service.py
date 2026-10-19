"""Due-schedule scanning and idempotent plan triggering."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis_client import redis_client
from app.db.base import AsyncSessionLocal
from app.db.models.test_plan import Schedule
from app.modules.test_plan.service import TestPlanService
from app.schemas.test_plan import PlanRunCreate


logger = get_logger(__name__)
SCHEDULER_LOCK_KEY = "qa:scheduler:scan"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_fire_after(schedule: Schedule, fire_at: datetime) -> datetime:
    """Return the next UTC-naive fire time after a recorded scheduled fire."""
    tz = ZoneInfo(schedule.timezone)
    trigger = CronTrigger.from_crontab(schedule.cron_expression, timezone=tz)
    previous = fire_at.replace(tzinfo=timezone.utc).astimezone(tz)
    next_fire = trigger.get_next_fire_time(previous, previous + timedelta(microseconds=1))
    if next_fire is None:
        raise ValueError(f"Schedule {schedule.id} has no next fire time")
    return next_fire.astimezone(timezone.utc).replace(tzinfo=None)


async def scan_once(now: datetime | None = None) -> int:
    """Trigger due schedules once; return the number of newly created runs."""
    token = await redis_client.acquire_token_lock(
        SCHEDULER_LOCK_KEY, settings.scheduler_lock_expire_seconds
    )
    if token is None:
        return 0

    created_count = 0
    scan_time = now or _now()
    grace_start = scan_time - timedelta(seconds=settings.scheduler_misfire_grace_seconds)
    try:
        async with AsyncSessionLocal() as db:
            schedules = list((await db.execute(
                select(Schedule)
                .where(Schedule.enabled.is_(True), Schedule.next_run_at <= scan_time)
                .order_by(Schedule.next_run_at, Schedule.id)
            )).scalars().all())

            for schedule in schedules:
                schedule_id = schedule.id
                fire_at = schedule.next_run_at
                if fire_at is None:
                    continue
                next_run_at = next_fire_after(schedule, fire_at)
                if fire_at < grace_start:
                    schedule.next_run_at = next_run_at
                    schedule.last_run_at = fire_at
                    schedule.last_status = "missed"
                    await db.commit()
                    continue

                key = f"schedule:{schedule_id}:{fire_at.isoformat(timespec='seconds')}"
                last_status = "triggered"
                try:
                    _, created = await TestPlanService(db).run(
                        schedule.project_id,
                        schedule.plan_id,
                        PlanRunCreate(),
                        schedule.created_by or 0,
                        key,
                        trigger_type="schedule",
                    )
                    created_count += int(created)
                except Exception:
                    await db.rollback()
                    last_status = "failed"
                    logger.exception("Schedule trigger failed schedule_id=%s", schedule_id)

                refreshed = (await db.execute(
                    select(Schedule).where(Schedule.id == schedule_id)
                )).scalar_one_or_none()
                if refreshed is None:
                    continue
                refreshed.next_run_at = fire_at if last_status == "failed" else next_run_at
                refreshed.last_run_at = fire_at
                refreshed.last_status = last_status
                await db.commit()
    finally:
        await redis_client.release_token_lock(SCHEDULER_LOCK_KEY, token)
    return created_count
