"""arq 任务定义与投递辅助。

- generate_report_task: worker 侧任务，生成HTML/PDF报告并上传MinIO。
- get_arq_redis / enqueue_execution / enqueue_report: API 侧投递辅助。
"""
import socket
from datetime import datetime
from typing import Optional

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal

logger = get_logger(__name__)

EXECUTION_QUEUE = "qa.execution"
REPORT_QUEUE = "qa.report"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.arq_redis_url)


async def enqueue_execution(execution_id: int) -> Optional[str]:
    """投递执行任务到 qa.execution 队列，返回 arq job_id。"""
    pool = await get_arq_redis()
    job = await pool.enqueue_job(
        "run_execution_task", execution_id,
        _queue_name=EXECUTION_QUEUE,
        _job_id=f"exec-{execution_id}",
    )
    return job.job_id if job else None


async def generate_report_task(ctx: dict, report_id: int) -> str:
    """arq 任务入口：生成报告（复用 ReportService.generate_and_store）。"""
    async with AsyncSessionLocal() as db:
        from app.modules.report.service import ReportService

        service = ReportService(db)
        return await service.generate_and_store(report_id)


async def cleanup_old_data_task(ctx: dict) -> dict:
    """arq cron 任务：清理超期报告数据。"""
    if not settings.cleanup_enabled:
        logger.info("cleanup_old_data_task skipped (cleanup_enabled=False)")
        return {"skipped": True}

    from app.modules.ops.cleanup import cleanup_reports

    result: dict = {}
    async with AsyncSessionLocal() as db:
        try:
            result["reports"] = await cleanup_reports(
                db,
                retention_days=settings.report_retention_days,
                protected_run_ids=settings.cleanup_protected_run_ids,
                batch_size=settings.cleanup_batch_size,
                dry_run=settings.cleanup_dry_run,
            )
        except Exception:
            logger.exception("cleanup_old_data_task reports failed")
            result["reports"] = {"error": True}

    logger.info("cleanup_old_data_task done result=%s", result)
    return result


async def scheduler_scan_task(ctx: dict) -> int:
    """arq cron 任务：扫描到期定时任务并触发计划运行。"""
    from scheduler.service import scan_once

    try:
        created = await scan_once()
        if created:
            logger.info("scheduler_scan_task triggered %s run(s)", created)
        return created
    except Exception as e:
        logger.warning(f"scheduler_scan_task skipped due to error (will retry next round): {e}")
        return 0


# ---- API 侧投递 ----

_pool: Optional[ArqRedis] = None


async def get_arq_redis() -> ArqRedis:
    """获取（并缓存）arq Redis 连接池，供 FastAPI 投递任务。"""
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def enqueue_report(report_id: int) -> Optional[str]:
    """投递报告生成任务到执行队列，返回 arq job_id。"""
    pool = await get_arq_redis()
    job = await pool.enqueue_job(
        "generate_report_task", report_id,
        _queue_name=EXECUTION_QUEUE,
        _job_id=f"report-{report_id}",
    )
    return job.job_id if job else None
