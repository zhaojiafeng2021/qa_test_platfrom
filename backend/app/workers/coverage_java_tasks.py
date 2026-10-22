"""JaCoCo 覆盖率采集 arq 任务定义与投递辅助。

独立队列 qa.coverage_java，独立 worker 进程消费：

    cd backend && PYTHONUTF8=1 python -m arq app.workers.settings.CoverageJavaWorkerSettings

进度推送：worker 侧通过 redis_client.publish 到频道 coverage:task:{task_id}，
FastAPI WS 进程订阅该频道并转发给 WebSocket 客户端（跨进程桥接）。
"""
from __future__ import annotations

import json
from typing import Optional

from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis_client import redis_client
from app.db.base import AsyncSessionLocal
from app.workers.tasks import get_arq_redis, redis_settings

logger = get_logger(__name__)

COVERAGE_JAVA_QUEUE = "qa.coverage_java"


def coverage_progress_channel(task_id: int) -> str:
    """覆盖率任务进度推送的 Redis pub/sub 频道名（worker 发布 / WS 订阅）。"""
    return f"coverage:task:{task_id}"


def coverage_redis_settings() -> RedisSettings:
    """Coverage worker 与通用 worker 共享同一个 arq Redis 实例（不同 queue_name 隔离）。"""
    return redis_settings()


async def _publish_progress(task_id: int, msg: dict) -> None:
    """worker 侧 progress_callback 实现：序列化后 publish 到 coverage:task:{task_id}。"""
    try:
        await redis_client.publish(coverage_progress_channel(task_id), json.dumps(msg, ensure_ascii=False))
    except Exception as e:
        # 推送失败不阻塞采集主流程
        logger.warning(f"coverage progress publish failed (task={task_id}): {e}")


async def run_coverage_collection_task(
    ctx: dict,
    task_id: int,
    run_id: int,
    repo_url: str,
) -> dict:
    """arq 任务入口：执行一次覆盖率采集（顺序处理 N 个 service）。

    Args:
        task_id:  覆盖率任务 ID
        run_id:   本次 run ID
        repo_url: 仓库 URL（API 层在投递时从 project 表读出）

    Returns:
        {"success": bool, "completed": int, "failed": int, "cancelled": bool}
    """
    from app.modules.coverage_java.service import CoverageJavaService

    async def progress_callback(msg: dict) -> None:
        await _publish_progress(task_id, msg)

    async with AsyncSessionLocal() as db:
        service = CoverageJavaService(db)
        try:
            result = await service.run_collection(
                task_id=task_id,
                run_id=run_id,
                repo_url=repo_url,
                progress_callback=progress_callback,
            )
            logger.info(
                f"coverage collection done task={task_id} run={run_id} "
                f"completed={result['completed']} failed={result['failed']} cancelled={result['cancelled']}"
            )
            return result
        except Exception:
            logger.exception(f"coverage collection crashed task={task_id} run={run_id}")
            # 尽力标记 run 失败，避免任务永远卡在 running
            try:
                from app.modules.coverage_java.repository import (
                    CoverageTaskRepository,
                    JavaCoverageRunRepository,
                )
                from datetime import datetime
                run_repo = JavaCoverageRunRepository(db)
                task_repo = CoverageTaskRepository(db)
                await run_repo.update_status(
                    run_id, overall_status="failed", finished_at=datetime.utcnow(),
                )
                await task_repo.update_status(task_id, status="failed")
                await db.commit()
            except Exception:
                logger.exception("failed to mark run as failed after crash")
            raise


# ---- API 侧投递 ----


async def enqueue_coverage_collection(
    task_id: int,
    run_id: int,
    repo_url: str,
) -> Optional[str]:
    """投递覆盖率采集任务到 qa.coverage_java 队列，返回 arq job_id。

    job_id 固定为 coverage-{run_id}，便于 cancel 时定位（arq 重复 job_id 会去重）。
    """
    pool: ArqRedis = await get_arq_redis()
    job = await pool.enqueue_job(
        "run_coverage_collection_task",
        task_id,
        run_id,
        repo_url,
        _queue_name=COVERAGE_JAVA_QUEUE,
        _job_id=f"coverage-{run_id}",
    )
    return job.job_id if job else None


async def abort_coverage_collection(run_id: int) -> bool:
    """尽力取消正在执行的 arq job（配合 DB 状态标记，worker 循环时也会检测）。"""
    pool: ArqRedis = await get_arq_redis()
    try:
        job = await pool.job(f"coverage-{run_id}")
        if job is None:
            return False
        return await job.abort()
    except Exception as e:
        logger.warning(f"abort coverage job coverage-{run_id} failed: {e}")
        return False
