"""arq WorkerSettings。

项目有三个独立队列，需分别启动各自的 worker（各开一个终端）：

1. 通用 worker（消费 qa.execution 队列：报告生成、通知投递、定时清理/调度）：
   cd backend && PYTHONUTF8=1 python -m arq app.workers.settings.WorkerSettings

2. 代码用例 worker（消费 qa.code_case 队列，代码用例执行必需）：
   cd backend && PYTHONUTF8=1 python -m arq app.workers.settings.CodeCaseWorkerSettings

3. JaCoCo 覆盖率 worker（消费 qa.coverage_java 队列，跑 Java 构建，耗时长）：
   cd backend && PYTHONUTF8=1 python -m arq app.workers.settings.CoverageJavaWorkerSettings

不启动代码用例 worker，/api/v1/code-cases/execute 会一直卡在 pending。
不启动覆盖率 worker，/api/v1/projects/{pid}/coverage-tasks/{tid}/trigger 会一直 queued。
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
from app.workers.coverage_java_tasks import (
    COVERAGE_JAVA_QUEUE,
    coverage_redis_settings,
    run_coverage_collection_task,
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


class CoverageJavaWorkerSettings:
    """JaCoCo 覆盖率采集专用 Worker（独立队列）。

    - max_jobs=1：JVM 构建占用内存高，MVP 保守起步；后续可按机器规格调大
    - job_timeout=3600：多服务 monorepo 顺序采集，单 run 最长 1 小时
    """
    functions = [run_coverage_collection_task]
    queue_name = COVERAGE_JAVA_QUEUE
    redis_settings = coverage_redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    job_timeout = 3600
    max_jobs = 1
    keep_result = 3600
