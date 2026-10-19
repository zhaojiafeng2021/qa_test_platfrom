"""arq WorkerSettings。

项目有两个独立队列，需分别启动各自的 worker（各开一个终端）：

1. 通用 worker（消费 qa.execution 队列：报告生成、通知投递、定时清理/调度）：
   cd backend && PYTHONUTF8=1 python -m arq app.workers.settings.WorkerSettings

2. 代码用例 worker（消费 qa.code_case 队列，代码用例执行必需）：
   cd backend && PYTHONUTF8=1 python -m arq app.workers.settings.CodeCaseWorkerSettings

不启动代码用例 worker，/api/v1/code-cases/execute 会一直卡在 pending。
"""
from arq import cron

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.redis_client import redis_client
from app.workers.code_case_tasks import (
    CODE_CASE_QUEUE,
    code_case_redis_settings,
    run_code_case_batch_task,
    run_code_case_execution_task,
)
from app.workers.tasks import (
    EXECUTION_QUEUE,
    REPORT_QUEUE,
    cleanup_old_data_task,
    redis_settings,
    generate_report_task,
    scheduler_scan_task,
)
from app.workers.notification_tasks import (
    notification_recovery_task,
    process_notification_delivery_task,
)


async def startup(ctx: dict) -> None:
    setup_logging()
    await redis_client.connect()

    from app.db.base import AsyncSessionLocal
    import logging
    logger = logging.getLogger(__name__)

    try:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import text
            result = await db.execute(text("SELECT 1"))
            result.scalar()
            logger.info("Worker database connection verified")
    except Exception as e:
        logger.error(f"Worker database connection failed on startup: {e}")


async def shutdown(ctx: dict) -> None:
    await redis_client.disconnect()


class WorkerSettings:
    functions = [
        generate_report_task,
        cleanup_old_data_task,
        process_notification_delivery_task,
        run_code_case_batch_task,
        run_code_case_execution_task,
    ]
    queue_name = EXECUTION_QUEUE
    redis_settings = redis_settings()
    cron_jobs = [
        cron(scheduler_scan_task, second=0, run_at_startup=False),
        cron(notification_recovery_task, second=17, run_at_startup=False),
        cron(cleanup_old_data_task, hour=3, minute=17, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = 7200  # 2小时
    max_jobs = 5  # 减少并发数，避免资源耗尽
    keep_result = 3600


class CodeCaseWorkerSettings:
    """代码用例专用 Worker（独立队列，避免大批量用例阻塞执行引擎）"""
    functions = [run_code_case_batch_task, run_code_case_execution_task]
    queue_name = CODE_CASE_QUEUE
    redis_settings = code_case_redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = 1800
    max_jobs = 2
    keep_result = 3600
