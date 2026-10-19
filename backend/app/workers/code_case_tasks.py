"""arq 任务：代码用例批量执行器

将代码用例批量执行任务提交到 arq 队列，实现异步执行。
按创建顺序（即前端勾选顺序）逐个顺序执行，避免并发打满机器。
"""
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import AsyncSessionLocal
from app.modules.code_case.executor import execute_case
from app.modules.code_case.repository import CodeCaseExecutionRepository, CodeTestCaseRepository

logger = get_logger(__name__)

CODE_CASE_QUEUE = "qa.code_case"


def code_case_redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.arq_redis_url)


async def run_code_case_batch_task(ctx: dict, batch_id: str) -> str:
    """arq 任务入口：按创建顺序逐个执行批次内所有用例。

    Args:
        ctx: arq 上下文
        batch_id: 执行批次 ID

    Returns:
        结果状态
    """
    async with AsyncSessionLocal() as db:
        exec_repo = CodeCaseExecutionRepository(db)
        case_repo = CodeTestCaseRepository(db)

        executions = await exec_repo.list_by_batch(batch_id)
        if not executions:
            logger.warning("Code case batch %s has no executions", batch_id)
            return "skipped"

        logger.info("Starting code case batch %s with %d cases", batch_id, len(executions))

        for execution in executions:
            case = await case_repo.get(execution.case_id)
            if not case or case.is_deleted:
                await exec_repo.update(
                    execution,
                    status="error",
                    message=f"用例不存在或已删除",
                    finished_at=_now(),
                )
                await db.commit()
                continue

            await exec_repo.update(execution, status="running", started_at=_now())
            await db.commit()

            abs_path = str(_get_code_testcases_dir() / case.file_path)

            try:
                result = await execute_case(
                    abs_path,
                    case.function_name,
                    timeout=60,
                )
            except Exception as e:
                logger.exception("Code case execution %s failed", execution.id)
                result = {
                    "status": "error",
                    "message": f"执行异常: {type(e).__name__}: {e}",
                    "logs": "",
                    "traceback": "",
                    "duration_ms": 0,
                }

            finished_at = _now()
            await exec_repo.update(
                execution,
                status=result["status"],
                message=result.get("message"),
                logs=result.get("logs"),
                traceback=result.get("traceback"),
                duration_ms=result.get("duration_ms"),
                finished_at=finished_at,
            )

            await case_repo.update(case, status=result["status"], last_run_at=finished_at)
            await db.commit()

            logger.info(
                "Code case exec=%s finished: status=%s, duration=%sms",
                execution.id, result["status"], result.get("duration_ms"),
            )

        logger.info("Code case batch %s finished", batch_id)
        return "success"


async def run_code_case_execution_task(ctx: dict, execution_id: int) -> str:
    """arq 任务入口：执行单个代码用例（用于测试计划混合执行，按计划顺序逐个投递）。

    与 run_code_case_batch_task 的区别：本任务只执行一条 execution，由测试计划
    调度器（mixed_dispatcher）在顺序执行时逐个投递，便于和手工用例穿插、统一
    失败策略与状态同步。

    Args:
        ctx: arq 上下文
        execution_id: code_case_executions.id

    Returns:
        结果状态
    """
    async with AsyncSessionLocal() as db:
        exec_repo = CodeCaseExecutionRepository(db)
        case_repo = CodeTestCaseRepository(db)

        execution = await exec_repo.get(execution_id)
        if not execution:
            logger.warning("Code case execution %s not found", execution_id)
            return "not_found"
        # 已结束的不再重复执行（调度器可能重复投递）
        if execution.status in ("passed", "failed", "error", "timeout"):
            return "skipped"

        case = await case_repo.get(execution.case_id)
        if not case or case.is_deleted:
            await exec_repo.update(
                execution,
                status="error",
                message="用例不存在或已删除",
                finished_at=_now(),
            )
            await db.commit()
            return "error"

        await exec_repo.update(execution, status="running", started_at=_now())
        await db.commit()

        abs_path = str(_get_code_testcases_dir() / case.file_path)
        try:
            result = await execute_case(abs_path, case.function_name, timeout=60)
        except Exception as e:
            logger.exception("Code case execution %s failed", execution.id)
            result = {
                "status": "error",
                "message": f"执行异常: {type(e).__name__}: {e}",
                "logs": "",
                "traceback": "",
                "duration_ms": 0,
            }

        finished_at = _now()
        await exec_repo.update(
            execution,
            status=result["status"],
            message=result.get("message"),
            logs=result.get("logs"),
            traceback=result.get("traceback"),
            duration_ms=result.get("duration_ms"),
            finished_at=finished_at,
        )
        await case_repo.update(case, status=result["status"], last_run_at=finished_at)
        await db.commit()

        logger.info(
            "Code case exec=%s finished: status=%s, duration=%sms",
            execution.id, result["status"], result.get("duration_ms"),
        )

        # 推进所属测试计划运行：找到关联的 PlanRunItem 并触发调度器投递下一条用例。
        # 与 run_execution_task 调用 advance_plan_for_execution 对齐，保证顺序执行
        # 的代码用例能被逐个投递，而不依赖前端轮询 get_run。
        await _advance_plan_for_code_execution(db, execution.id)

        return result["status"]


_pool: ArqRedis | None = None


async def get_code_case_pool() -> ArqRedis:
    """获取（并缓存）arq Redis 连接池"""
    global _pool
    if _pool is None:
        _pool = await create_pool(code_case_redis_settings())
    return _pool


async def enqueue_code_case_batch(batch_id: str) -> str | None:
    """
    将代码用例批次执行任务投递到 arq 队列。

    Args:
        batch_id: 批次 ID

    Returns:
        arq job_id
    """
    pool = await get_code_case_pool()
    job = await pool.enqueue_job(
        "run_code_case_batch_task",
        batch_id,
        _job_id=f"code-batch-{batch_id}",
        _queue_name=CODE_CASE_QUEUE,
    )
    logger.info("Code case batch %s enqueued", batch_id)
    return job.job_id if job else None


async def enqueue_code_case_execution(execution_id: int) -> str | None:
    """
    将单个代码用例执行任务投递到 arq 队列（用于测试计划混合执行）。

    测试计划调度器（mixed_dispatcher）按顺序逐个投递用例：手工用例走
    enqueue_execution，代码用例走本函数。worker 侧由 run_code_case_execution_task
    消费，执行完毕后回写 code_case_executions，调度器下次轮询时同步到 PlanRunItem。

    Args:
        execution_id: code_case_executions.id

    Returns:
        arq job_id
    """
    pool = await get_code_case_pool()
    job = await pool.enqueue_job(
        "run_code_case_execution_task",
        execution_id,
        _job_id=f"code-exec-{execution_id}",
        _queue_name=CODE_CASE_QUEUE,
    )
    logger.info("Code case execution %s enqueued", execution_id)
    return job.job_id if job else None


def _get_code_testcases_dir():
    # 复用 service 层的解析逻辑，保证 web / worker 定位到同一目录
    from app.modules.code_case.service import get_code_testcases_dir
    return get_code_testcases_dir()


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _advance_plan_for_code_execution(db, code_execution_id: int) -> None:
    """代码用例执行完成后，推进所属测试计划运行（投递下一条用例）。

    通过 code_case_executions.id 反查 PlanRunItem.code_execution_id，找到 plan_run_id
    后调用 dispatch_mixed_plan_run。与 run_execution_task 中的 advance_plan_for_execution
    对齐，保证混合计划中代码用例顺序执行时能被逐个投递。
    """
    try:
        from sqlalchemy import select
        from app.db.models.test_plan import PlanRunItem
        from app.modules.test_plan.mixed_dispatcher import dispatch_mixed_plan_run

        plan_run_id = (await db.execute(
            select(PlanRunItem.plan_run_id)
            .where(PlanRunItem.code_execution_id == code_execution_id)
        )).scalar_one_or_none()
        if plan_run_id is not None:
            await dispatch_mixed_plan_run(db, plan_run_id)
            logger.info(
                "Advanced plan run %s after code case execution %s",
                plan_run_id, code_execution_id,
            )
    except Exception:
        logger.exception(
            "Failed to advance plan run for code case execution %s",
            code_execution_id,
        )
