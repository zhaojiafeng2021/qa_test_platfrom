"""
测试计划混合执行器（支持手工用例和代码用例）

负责：
1. 按用例类型调用不同的执行器
2. 顺序执行（不支持并发）
3. 统一返回格式，兼容报告展示
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.db.models.code_case import CodeCaseExecution
from app.db.models.test_plan import PlanRunItem
from app.modules.code_case.executor import execute_case as execute_code_case
from app.modules.code_case.service import get_code_testcases_dir
from app.modules.code_case.repository import CodeTestCaseRepository

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def execute_plan_item(
    db: AsyncSession,
    item: PlanRunItem,
    timeout: int = 60
) -> dict:
    """
    执行单个测试计划用例项

    Args:
        db: 数据库会话
        item: 计划运行用例项
        timeout: 代码用例超时时间（秒）

    Returns:
        dict: 执行结果统计 {status, duration_ms, error_message}
    """
    if item.case_type == "code":
        # 代码用例：直接调用代码用例执行器
        return await _execute_code_case(db, item, timeout)
    else:
        raise ValueError(f"Unsupported case type: {item.case_type}")


async def _execute_code_case(
    db: AsyncSession,
    item: PlanRunItem,
    timeout: int
) -> dict:
    """
    执行代码用例（异步）

    通过 Celery 队列异步执行，立即返回，由调度器轮询状态
    """
    from app.modules.code_case.repository import CodeCaseExecutionRepository
    from app.workers.code_case_tasks import enqueue_code_case_execution

    # 获取代码用例信息
    case_repo = CodeTestCaseRepository(db)
    case = await case_repo.get(item.case_id)

    if not case or case.is_deleted:
        return {
            "status": "error",
            "duration_ms": 0,
            "error_message": f"Code case {item.case_id} not found or deleted"
        }

    # 创建代码用例执行记录
    code_exec_repo = CodeCaseExecutionRepository(db)
    execution = await code_exec_repo.create(
        batch_id=f"plan_run_{item.plan_run_id}",
        case_id=case.id,
        case_name=case.name,
        module=case.module,
        level=case.level,
        file_path=case.file_path,
        function_name=case.function_name,
        status="pending",
        trigger_by=None,  # 从 plan_run 获取
    )
    await db.flush()

    # 关联到 plan_run_item
    await db.execute(
        update(PlanRunItem)
        .where(PlanRunItem.id == item.id)
        .values(code_execution_id=execution.id)
    )
    await db.commit()

    # 投递到 Celery 队列异步执行
    try:
        await enqueue_code_case_execution(execution.id)
        logger.info(f"Code case execution {execution.id} enqueued to Celery")
    except Exception as e:
        logger.exception(f"Failed to enqueue code case execution {execution.id}")
        # 标记为错误
        await code_exec_repo.update(
            execution,
            status="error",
            message=f"Failed to enqueue: {str(e)}",
            finished_at=_now()
        )
        await db.commit()
        return {
            "status": "error",
            "duration_ms": 0,
            "error_message": f"Failed to enqueue: {str(e)}"
        }

    # 立即返回 pending 状态，由调度器轮询
    return {
        "status": "pending",
        "duration_ms": 0,
        "error_message": None
    }
