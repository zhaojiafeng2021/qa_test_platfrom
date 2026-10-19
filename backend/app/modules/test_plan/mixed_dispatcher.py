"""
测试计划混合执行调度器

支持手工用例和代码用例的顺序执行（不支持并发）
"""
from datetime import datetime, timezone
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.code_case import CodeCaseExecution
from app.db.models.test_plan import PlanRun, PlanRunItem, TestPlan
from app.modules.test_plan.mixed_executor import execute_plan_item

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"passed", "failed", "error", "cancelled", "timeout"}
FAILED_STATUSES = {"failed", "error", "timeout"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def dispatch_mixed_plan_run(db: AsyncSession, run_id: int) -> dict:
    """
    调度混合测试计划运行（顺序执行，异步任务）

    手工用例和代码用例都通过 Celery 异步执行，调度器负责投递任务和同步状态

    Args:
        db: 数据库会话
        run_id: 计划运行ID

    Returns:
        dict: 调度结果 {status, enqueued_count, message}
    """
    logger.info(f"dispatch_mixed_plan_run called for run_id={run_id}")

    # 获取计划运行记录（加锁）
    run = (await db.execute(
        select(PlanRun).where(PlanRun.id == run_id).with_for_update()
    )).scalar_one_or_none()

    if not run or run.status in TERMINAL_STATUSES:
        logger.info(f"Run {run_id} skipped: status={run.status if run else 'not found'}")
        return {"status": "skipped", "enqueued_count": 0, "message": "Run already finished"}

    # 获取所有用例项（按顺序）
    items = list((await db.execute(
        select(PlanRunItem)
        .where(PlanRunItem.plan_run_id == run_id)
        .order_by(PlanRunItem.sort_order, PlanRunItem.id)
    )).scalars().all())

    if not items:
        run.status = "passed"
        run.finished_at = _now()
        await db.commit()
        return {"status": "passed", "enqueued_count": 0, "message": "No items to execute"}

    # 同步已完成的用例状态
    await _sync_item_statuses(db, items)

    # 统计当前状态
    statuses = [item.status for item in items]
    run.passed_items = sum(s == "passed" for s in statuses)
    run.failed_items = sum(s in FAILED_STATUSES for s in statuses)
    has_failure = run.failed_items > 0

    # 如果策略是"失败停止"且已有失败，取消剩余用例
    if run.failure_strategy == "stop" and has_failure:
        await _cancel_remaining_items(db, items)
        statuses = [item.status for item in items]

    # 检查是否全部完成
    if all(s in TERMINAL_STATUSES for s in statuses):
        run.status = "failed" if has_failure else (
            "cancelled" if any(s == "cancelled" for s in statuses) else "passed"
        )
        run.finished_at = _now()
        await db.commit()

        # 触发测试计划通知
        await _trigger_plan_notification(db, run)

        return {
            "status": run.status,
            "enqueued_count": 0,
            "message": "All items finished"
        }

    # 顺序执行：找到第一个 pending 的用例并投递到队列
    enqueued_count = 0
    for item in items:
        if item.status != "pending":
            continue

        # 投递用例到执行队列（异步）
        try:
            await _enqueue_plan_item(db, item)
            enqueued_count += 1
            run.status = "running"
            if run.started_at is None:
                run.started_at = _now()
            await db.commit()

            # 顺序执行：只投递第一个 pending 的用例
            break

        except Exception as e:
            logger.exception(f"Failed to enqueue plan item {item.id}")
            item.status = "error"
            await db.commit()

            # 如果失败且策略是停止，跳出循环
            if run.failure_strategy == "stop":
                break

    # 更新统计
    await _sync_item_statuses(db, items)
    statuses = [item.status for item in items]
    run.passed_items = sum(s == "passed" for s in statuses)
    run.failed_items = sum(s in FAILED_STATUSES for s in statuses)

    # 再次检查是否全部完成
    if all(s in TERMINAL_STATUSES for s in statuses):
        run.status = "failed" if run.failed_items > 0 else (
            "cancelled" if any(s == "cancelled" for s in statuses) else "passed"
        )
        run.finished_at = _now()

        await db.commit()

        # 触发测试计划通知
        await _trigger_plan_notification(db, run)

    else:
        await db.commit()

    return {
        "status": run.status,
        "enqueued_count": enqueued_count,
        "message": f"Enqueued {enqueued_count} items"
    }


async def _enqueue_plan_item(db: AsyncSession, item: PlanRunItem) -> None:
    """投递单个测试计划用例项到执行队列"""
    if item.case_type == "code":
        # 代码用例：投递到代码用例执行队列
        from app.workers.code_case_tasks import enqueue_code_case_execution
        if item.code_execution_id:
            await enqueue_code_case_execution(item.code_execution_id)
            item.status = "running"
            logger.info(f"Code case execution {item.code_execution_id} enqueued")


async def _sync_item_statuses(db: AsyncSession, items: list[PlanRunItem]) -> None:
    """同步用例项的执行状态"""
    # 代码用例执行状态
    code_exec_ids = [item.code_execution_id for item in items
                     if item.case_type == "code" and item.code_execution_id]
    if code_exec_ids:
        code_executions = list((await db.execute(
            select(CodeCaseExecution)
            .where(CodeCaseExecution.id.in_(code_exec_ids))
        )).scalars().all())
        code_exec_by_id = {e.id: e for e in code_executions}

        for item in items:
            if item.case_type == "code" and item.code_execution_id:
                execution = code_exec_by_id.get(item.code_execution_id)
                if execution and execution.status in TERMINAL_STATUSES:
                    item.status = execution.status


async def _cancel_remaining_items(db: AsyncSession, items: list[PlanRunItem]) -> None:
    """取消剩余未执行的用例项"""
    now = _now()
    for item in items:
        if item.status == "pending":
            item.status = "cancelled"

            # 取消对应的执行记录
            if item.case_type == "code" and item.code_execution_id:
                await db.execute(
                    update(CodeCaseExecution)
                    .where(CodeCaseExecution.id == item.code_execution_id)
                    .values(status="cancelled", finished_at=now)
                )


async def _trigger_plan_notification(db: AsyncSession, run: PlanRun) -> None:
    """触发测试计划完成通知 - 优先使用通知规则，其次使用测试计划直接配置"""
    try:
        logger.info(f"_trigger_plan_notification called for run {run.id}, status={run.status}")

        # 查询测试计划配置
        plan = (await db.execute(
            select(TestPlan).where(TestPlan.id == run.plan_id)
        )).scalar_one_or_none()

        if not plan:
            logger.warning(f"Plan {run.plan_id} not found for notification")
            return

        # 计算通过率
        pass_rate = 0.0
        if run.total_items > 0:
            pass_rate = (run.passed_items / run.total_items) * 100

        # 确定事件类型
        event_type = "execution.failed" if run.status == "failed" else "execution.completed"

        # 构建通知上下文
        context = {
            "project_id": run.project_id,
            "plan_id": run.plan_id,
            "plan_name": plan.name,
            "run_id": run.id,
            "status": run.status,
            "trigger_type": run.trigger_type,
            "total_items": run.total_items,
            "passed_items": run.passed_items,
            "failed_items": run.failed_items,
            "pass_rate": round(pass_rate, 2),
            "duration": _calculate_duration(run.started_at, run.finished_at),
            "owner_id": plan.owner_id,  # 添加负责人ID，用于 event_owner 接收人类型
        }

        event_id = f"plan_run:{run.id}"
        summary = f"测试计划 [{plan.name}] 执行{'失败' if run.status == 'failed' else '完成'}，通过率 {pass_rate:.1f}%"

        from app.modules.notification.service import NotificationService
        notification_service = NotificationService(db)

        # 方式1: 如果测试计划关联了通知规则，只触发这些规则
        if plan.notification_rule_ids:
            logger.info(f"Plan run {run.id} has selected rules: {plan.notification_rule_ids}")
            delivery_ids = await notification_service.emit_event(
                project_id=run.project_id,
                event_id=event_id,
                event_type=event_type,
                context=context,
                summary=summary,
                rule_ids=plan.notification_rule_ids,  # 只触发指定的规则
            )

            if delivery_ids:
                await db.commit()
                await NotificationService.wake_deliveries(delivery_ids)
                logger.info(f"Plan run {run.id} triggered {len(delivery_ids)} notification(s) via selected rules, delivery_ids={delivery_ids}")
            else:
                logger.info(f"Plan run {run.id} selected rules did not match (disabled or condition not met)")
            return

        # 方式2: 如果没有选择规则，尝试匹配项目全局规则（支持接收人配置、启用状态、触发条件）
        delivery_ids = await notification_service.emit_event(
            project_id=run.project_id,
            event_id=event_id,
            event_type=event_type,
            context=context,
            summary=summary,
        )

        if delivery_ids:
            await db.commit()
            await NotificationService.wake_deliveries(delivery_ids)
            logger.info(f"Plan run {run.id} triggered {len(delivery_ids)} notification(s) via global rules, delivery_ids={delivery_ids}")
            return

        # 方式3: 如果没有匹配的规则，且测试计划配置了直接通知，则使用直接通知（向后兼容）
        if not plan.notification_channel_id:
            logger.debug(f"Plan run {run.id} has no notification rules and no direct channel config")
            return

        from app.modules.notification.repository import NotificationRepository

        repo = NotificationRepository(db)
        channel = await repo.get_channel(plan.notification_channel_id)

        if not channel or not channel.enabled:
            logger.warning(f"Plan run {run.id} direct channel {plan.notification_channel_id} not found or disabled")
            return

        # 使用配置的模板代码（如果有），否则根据状态选择默认模板
        template_code = plan.notification_template_code or (
            "failure_alert" if run.status == "failed" else "execution_summary"
        )

        # 直接通知模式：默认通知所有项目成员
        card, recipient_meta = await notification_service._build_card_with_recipients(
            run.project_id,
            template_code,
            summary,
            context,
            "all_members",
            {}
        )

        # 创建投递记录
        delivery = await repo.create_delivery_idempotent(
            project_id=run.project_id,
            rule_id=None,  # 直接通知，不关联规则
            channel_id=channel.id,
            event_id=event_id,
            event_type=event_type,
            status="pending",
            attempt_count=0,
            max_attempts=5,
            next_attempt_at=_now(),
            payload_json={
                "webhook_payload": card,
                "recipient_meta": recipient_meta,
                "context": context,
                "recipient_type": "all_members",
                "recipient_config": {},
                "template_code": template_code,
            },
            message_summary=summary,
        )

        if delivery:
            await db.commit()
            await NotificationService.wake_deliveries([delivery.id])
            logger.info(f"Plan run {run.id} triggered direct notification, delivery_id={delivery.id}")
        else:
            logger.warning(f"Plan run {run.id} failed to create delivery (duplicate event_id)")

    except Exception as e:
        logger.exception(f"Failed to trigger notification for plan run {run.id}: {e}")
        # 通知失败不应影响测试计划执行流程，仅记录日志


def _calculate_duration(started_at: datetime | None, finished_at: datetime | None) -> str:
    """计算执行时长"""
    if not started_at or not finished_at:
        return "N/A"

    delta = finished_at - started_at
    total_seconds = int(delta.total_seconds())

    if total_seconds < 60:
        return f"{total_seconds}秒"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}分{seconds}秒"
    else:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}小时{minutes}分"

