"""
测试计划服务层扩展 - 支持代码用例

包含支持手工用例和代码用例混合的服务方法
"""
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.modules.code_case.repository import CodeTestCaseRepository


async def normalize_mixed_items(
    db: AsyncSession,
    project_id: int,
    items: list,
) -> list[dict]:
    """
    标准化混合用例项（手工用例 + 代码用例）

    Args:
        db: 数据库会话
        project_id: 项目ID
        items: 用例项输入列表（PlanItemInput）

    Returns:
        list[dict]: 标准化后的用例项列表

    Raises:
        ValidationError: 用例不存在、重复或不可执行
    """
    code_case_repo = CodeTestCaseRepository(db)

    normalized = []
    seen_code = set()

    for index, item in enumerate(items):
        case_type = item.case_type or "code"

        if case_type == "code":
            # 代码用例校验
            if item.case_id in seen_code:
                raise ValidationError(f"Duplicate code case: {item.case_id}")
            seen_code.add(item.case_id)

            code_case = await code_case_repo.get(item.case_id)
            if not code_case or code_case.is_deleted:
                raise ValidationError(
                    f"Code case {item.case_id} not found or deleted"
                )

            # 代码用例使用固定版本 1（因为代码用例没有版本快照机制）
            normalized.append({
                "case_id": code_case.id,
                "case_type": "code",
                "case_version": 1,
                "sort_order": item.sort_order if item.sort_order is not None else index,
                "enabled": item.enabled,
            })

        else:
            raise ValidationError(f"Unsupported case type: {case_type}")

    return normalized


async def build_mixed_plan_item_info(
    db: AsyncSession,
    item,
    project_id: int,
):
    """
    构建混合用例项信息（用于测试计划详情）

    Args:
        db: 数据库会话
        item: PlanItem 对象
        project_id: 项目ID

    Returns:
        PlanItemInfo: 用例项信息
    """
    from app.schemas.test_plan import PlanItemInfo

    item_info = PlanItemInfo.model_validate(item)

    if item.case_type == "code":
        code_case_repo = CodeTestCaseRepository(db)
        code_case = await code_case_repo.get(item.case_id)

        if code_case and not code_case.is_deleted:
            item_info.case_name = code_case.name
            item_info.module = code_case.module
            item_info.level = code_case.level
            item_info.priority = code_case.level
            item_info.step_count = 1

    return item_info


async def build_mixed_run_item_info(
    db: AsyncSession,
    item,
    project_id: int,
):
    """
    构建混合执行项信息（用于测试计划运行详情）

    Args:
        db: 数据库会话
        item: PlanRunItem 对象
        project_id: 项目ID

    Returns:
        PlanRunItemInfo: 执行项信息
    """
    from app.schemas.test_plan import PlanRunItemInfo
    from app.db.models.code_case import CodeCaseExecution

    item_info = PlanRunItemInfo.model_validate(item)

    if item.case_type == "code":
        # 代码用例执行信息
        code_case_repo = CodeTestCaseRepository(db)
        from app.modules.code_case.repository import CodeCaseExecutionRepository

        code_exec_repo = CodeCaseExecutionRepository(db)

        code_case = await code_case_repo.get(item.case_id)
        if code_case:
            item_info.case_name = code_case.name
            item_info.module = code_case.module
            item_info.level = code_case.level
            item_info.priority = code_case.level

        if item.code_execution_id:
            from sqlalchemy import select
            code_execution = (await db.execute(
                select(CodeCaseExecution)
                .where(CodeCaseExecution.id == item.code_execution_id)
            )).scalar_one_or_none()

            if code_execution:
                item_info.duration_ms = code_execution.duration_ms
                item_info.error_message = code_execution.message
                item_info.logs = code_execution.logs
                item_info.started_at = code_execution.started_at
                item_info.finished_at = code_execution.finished_at
                # 代码用例只有 1 步
                item_info.total_steps = 1
                item_info.passed_steps = 1 if code_execution.status == "passed" else 0
                item_info.failed_steps = 1 if code_execution.status in ("failed", "error") else 0

    return item_info
