"""Persistence operations for WP-07 test plans."""
from __future__ import annotations
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.test_plan import PlanItem, PlanRun, PlanRunItem, Schedule, TestPlan
from app.db.models.code_case import CodeCaseExecution


class TestPlanRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, plan_id: int) -> Optional[TestPlan]:
        return (await self.db.execute(select(TestPlan).where(TestPlan.id == plan_id, TestPlan.is_deleted == False))).scalar_one_or_none()

    async def list(self, project_id: int, status: str | None, page: int, page_size: int):
        stmt = select(TestPlan).where(TestPlan.project_id == project_id, TestPlan.is_deleted == False)
        if status:
            stmt = stmt.where(TestPlan.status == status)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.db.execute(
            stmt.order_by(TestPlan.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        return total, list(rows)

    async def list_items(self, plan_id: int) -> list[PlanItem]:
        rows = await self.db.execute(
            select(PlanItem).where(PlanItem.plan_id == plan_id).order_by(PlanItem.sort_order, PlanItem.id)
        )
        return list(rows.scalars().all())

    async def list_items_for_plans(self, plan_ids: list[int]) -> list[PlanItem]:
        """批量取多个计划的 items（消除按计划逐个查询的 N+1）。"""
        if not plan_ids:
            return []
        rows = await self.db.execute(
            select(PlanItem).where(PlanItem.plan_id.in_(plan_ids))
            .order_by(PlanItem.sort_order, PlanItem.id)
        )
        return list(rows.scalars().all())

    async def list_run_items_for_runs(self, run_ids: list[int]) -> list[PlanRunItem]:
        """批量取多个 plan-run 的 items（消除执行队列列表的 N+1）。"""
        if not run_ids:
            return []
        rows = await self.db.execute(
            select(PlanRunItem).where(PlanRunItem.plan_run_id.in_(run_ids))
            .order_by(PlanRunItem.sort_order, PlanRunItem.id)
        )
        return list(rows.scalars().all())

    async def replace_items(self, plan_id: int, project_id: int, items: list[dict]) -> list[PlanItem]:
        await self.db.execute(delete(PlanItem).where(PlanItem.plan_id == plan_id))
        result = []
        for item in items:
            obj = PlanItem(plan_id=plan_id, project_id=project_id, **item)
            self.db.add(obj)
            result.append(obj)
        await self.db.flush()
        return result

    async def get_run_by_key(self, key: str) -> Optional[PlanRun]:
        return (await self.db.execute(
            select(PlanRun).where(PlanRun.idempotency_key == key)
        )).scalar_one_or_none()

    async def get_run(self, run_id: int) -> Optional[PlanRun]:
        return (await self.db.execute(select(PlanRun).where(PlanRun.id == run_id))).scalar_one_or_none()

    async def list_run_items(self, run_id: int) -> list[PlanRunItem]:
        rows = await self.db.execute(
            select(PlanRunItem).where(PlanRunItem.plan_run_id == run_id)
            .order_by(PlanRunItem.sort_order, PlanRunItem.id)
        )
        return list(rows.scalars().all())

    async def list_runs(self, project_id: int, plan_id: int | None, status: str | None,
                        page: int, page_size: int,
                        trigger_type: str | None = None,
                        started_from=None, started_to=None):
        stmt = select(PlanRun).where(PlanRun.project_id == project_id)
        if plan_id is not None:
            stmt = stmt.where(PlanRun.plan_id == plan_id)
        if status:
            stmt = stmt.where(PlanRun.status == status)
        if trigger_type:
            stmt = stmt.where(PlanRun.trigger_type == trigger_type)
        if started_from is not None:
            stmt = stmt.where(PlanRun.created_at >= started_from)
        if started_to is not None:
            stmt = stmt.where(PlanRun.created_at <= started_to)
        total = (await self.db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        rows = (await self.db.execute(
            stmt.order_by(PlanRun.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )).scalars().all()
        return total, list(rows)

    async def sync_run(self, run: PlanRun) -> PlanRun:
        items = await self.list_run_items(run.id)
        if not items:
            return run
        execution_ids = [item.code_execution_id for item in items if item.code_execution_id]
        executions = []
        if execution_ids:
            executions = list((await self.db.execute(
                select(CodeCaseExecution).where(CodeCaseExecution.id.in_(execution_ids))
            )).scalars().all())
        by_id = {item.id: item for item in executions}
        terminal = {"passed", "failed", "error", "cancelled", "timeout"}
        for item in items:
            execution = by_id.get(item.code_execution_id)
            if execution:
                item.status = execution.status
        statuses = [item.status for item in items]
        run.passed_items = sum(value == "passed" for value in statuses)
        run.failed_items = sum(value in {"failed", "error", "timeout"} for value in statuses)
        if all(value in terminal for value in statuses):
            run.status = "failed" if run.failed_items else (
                "cancelled" if any(value == "cancelled" for value in statuses) else "passed"
            )
            run.finished_at = max((by_id[item.code_execution_id].finished_at for item in items
                                   if item.code_execution_id in by_id and by_id[item.code_execution_id].finished_at), default=None)
        elif any(value == "running" for value in statuses):
            run.status = "running"
        # 如果所有有execution的item已终态，但有item没有execution_id（未投递的）
        # 且run状态已非pending/running（被取消等），也标记这些item为cancelled
        elif run.status in terminal:
            pass  # run 已在终态，不需再改
        else:
            # 检查是否所有有execution的item都已终态（但整体还有pending item未投递）
            exec_items = [item for item in items if item.code_execution_id]
            non_exec_items = [item for item in items if not item.code_execution_id]
            if exec_items and all(by_id.get(item.code_execution_id) and by_id[item.code_execution_id].status in terminal for item in exec_items):
                # 所有已投递的execution都结束了，但还有未投递的pending item
                # 如果有失败且策略是stop，这些未投递item不会再被投递
                # 直接标记它们为cancelled
                for item in non_exec_items:
                    if item.status == "pending":
                        item.status = "cancelled"
                # 重新计算
                statuses = [item.status for item in items]
                run.passed_items = sum(value == "passed" for value in statuses)
                run.failed_items = sum(value in {"failed", "error", "timeout"} for value in statuses)
                if all(value in terminal for value in statuses):
                    run.status = "failed" if run.failed_items else (
                        "cancelled" if any(value == "cancelled" for value in statuses) else "passed"
                    )
                    run.finished_at = max((by_id[item.code_execution_id].finished_at for item in items
                                           if item.code_execution_id in by_id and by_id[item.code_execution_id].finished_at), default=None)
        await self.db.flush()
        return run


class ScheduleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, schedule_id: int) -> Optional[Schedule]:
        return (await self.db.execute(select(Schedule).where(Schedule.id == schedule_id, Schedule.is_deleted == False))).scalar_one_or_none()

    async def list(self, project_id: int) -> list[Schedule]:
        return list((await self.db.execute(
            select(Schedule).where(Schedule.project_id == project_id, Schedule.is_deleted == False).order_by(Schedule.id.desc())
        )).scalars().all())
