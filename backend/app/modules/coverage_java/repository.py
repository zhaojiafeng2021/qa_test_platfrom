"""JaCoCo 覆盖率采集：3 张表的 CRUD repository。

风格参照 app/modules/code_case/repository.py：薄封装 SQLAlchemy async 查询。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.coverage_java import (
    CoverageTask,
    JavaCoverageReport,
    JavaCoverageRun,
)


def _now() -> datetime:
    return datetime.utcnow()


# ──────────────────────────────────────────────
# CoverageTask
# ──────────────────────────────────────────────

class CoverageTaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> CoverageTask:
        task = CoverageTask(**kwargs)
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def get(self, task_id: int) -> Optional[CoverageTask]:
        result = await self.db.execute(
            select(CoverageTask).where(
                CoverageTask.id == task_id,
                CoverageTask.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: int,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        branch: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[CoverageTask]]:
        stmt = select(CoverageTask).where(
            CoverageTask.project_id == project_id,
            CoverageTask.is_deleted == False,  # noqa: E712
        )
        if keyword:
            stmt = stmt.where(CoverageTask.name.like(f"%{keyword}%"))
        if status:
            stmt = stmt.where(CoverageTask.status == status)
        if branch:
            stmt = stmt.where(CoverageTask.branch == branch)

        count_stmt = select(CoverageTask.id).where(*stmt._where_criteria)  # noqa: SLF001
        total_result = await self.db.execute(count_stmt)
        total = len(total_result.scalars().all())

        stmt = stmt.order_by(CoverageTask.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(stmt)
        return total, list(result.scalars().all())

    async def update(self, task: CoverageTask, **kwargs) -> CoverageTask:
        for k, v in kwargs.items():
            if v is not None:
                setattr(task, k, v)
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def soft_delete(self, task: CoverageTask, user_id: Optional[int] = None) -> None:
        task.soft_delete(user_id)
        await self.db.flush()

    async def update_status(
        self,
        task_id: int,
        status: str,
        current_run_id: Optional[int] = None,
        last_completed_at: Optional[datetime] = None,
        last_failed_at: Optional[datetime] = None,
    ) -> None:
        values: dict = {"status": status}
        if current_run_id is not None:
            values["current_run_id"] = current_run_id
        if last_completed_at is not None:
            values["last_completed_at"] = last_completed_at
        if last_failed_at is not None:
            values["last_failed_at"] = last_failed_at
        await self.db.execute(
            update(CoverageTask).where(CoverageTask.id == task_id).values(**values)
        )
        await self.db.flush()


# ──────────────────────────────────────────────
# JavaCoverageRun
# ──────────────────────────────────────────────

class JavaCoverageRunRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> JavaCoverageRun:
        run = JavaCoverageRun(**kwargs)
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get(self, run_id: int) -> Optional[JavaCoverageRun]:
        result = await self.db.execute(
            select(JavaCoverageRun).where(JavaCoverageRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_by_task(
        self,
        task_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[JavaCoverageRun]]:
        stmt = select(JavaCoverageRun).where(JavaCoverageRun.task_id == task_id)

        count_stmt = select(JavaCoverageRun.id).where(JavaCoverageRun.task_id == task_id)
        total_result = await self.db.execute(count_stmt)
        total = len(total_result.scalars().all())

        stmt = stmt.order_by(JavaCoverageRun.created_at.desc())
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(stmt)
        return total, list(result.scalars().all())

    async def update(self, run: JavaCoverageRun, **kwargs) -> JavaCoverageRun:
        for k, v in kwargs.items():
            setattr(run, k, v)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def update_status(
        self,
        run_id: int,
        overall_status: str,
        started_at: Optional[datetime] = None,
        finished_at: Optional[datetime] = None,
        services_completed: Optional[int] = None,
        services_failed: Optional[int] = None,
    ) -> None:
        values: dict = {"overall_status": overall_status}
        if started_at is not None:
            values["started_at"] = started_at
        if finished_at is not None:
            values["finished_at"] = finished_at
        if services_completed is not None:
            values["services_completed"] = services_completed
        if services_failed is not None:
            values["services_failed"] = services_failed
        await self.db.execute(
            update(JavaCoverageRun).where(JavaCoverageRun.id == run_id).values(**values)
        )
        await self.db.flush()


# ──────────────────────────────────────────────
# JavaCoverageReport
# ──────────────────────────────────────────────

class JavaCoverageReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> JavaCoverageReport:
        report = JavaCoverageReport(**kwargs)
        self.db.add(report)
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def get(self, report_id: int) -> Optional[JavaCoverageReport]:
        result = await self.db.execute(
            select(JavaCoverageReport).where(JavaCoverageReport.id == report_id)
        )
        return result.scalar_one_or_none()

    async def list_by_run(self, run_id: int) -> list[JavaCoverageReport]:
        result = await self.db.execute(
            select(JavaCoverageReport)
            .where(JavaCoverageReport.run_id == run_id)
            .order_by(JavaCoverageReport.id)
        )
        return list(result.scalars().all())

    async def update(self, report: JavaCoverageReport, **kwargs) -> JavaCoverageReport:
        for k, v in kwargs.items():
            setattr(report, k, v)
        await self.db.flush()
        await self.db.refresh(report)
        return report

    async def update_progress(
        self,
        report_id: int,
        progress: int,
        stage: str,
        stage_detail: Optional[str] = None,
        status: Optional[str] = None,
    ) -> None:
        values: dict = {"progress": progress, "stage": stage}
        if stage_detail is not None:
            values["stage_detail"] = stage_detail
        if status is not None:
            values["status"] = status
        await self.db.execute(
            update(JavaCoverageReport).where(JavaCoverageReport.id == report_id).values(**values)
        )
        await self.db.flush()

    async def update_result(
        self,
        report_id: int,
        status: str,
        progress: Optional[int] = None,
        stage: Optional[str] = None,
        stage_detail: Optional[str] = None,
        commit_sha: Optional[str] = None,
        line_rate: Optional[float] = None,
        branch_rate: Optional[float] = None,
        lines_covered: Optional[int] = None,
        lines_total: Optional[int] = None,
        branches_covered: Optional[int] = None,
        branches_total: Optional[int] = None,
        line_coverage_json: Optional[dict] = None,
        xml_report_path: Optional[str] = None,
        html_report_path: Optional[str] = None,
        exec_file_path: Optional[str] = None,
        build_log_path: Optional[str] = None,
        source_snapshot_path: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        values: dict = {"status": status}
        for k, v in (
            ("progress", progress),
            ("stage", stage),
            ("stage_detail", stage_detail),
            ("commit_sha", commit_sha),
            ("line_rate", line_rate),
            ("branch_rate", branch_rate),
            ("lines_covered", lines_covered),
            ("lines_total", lines_total),
            ("branches_covered", branches_covered),
            ("branches_total", branches_total),
            ("line_coverage_json", line_coverage_json),
            ("xml_report_path", xml_report_path),
            ("html_report_path", html_report_path),
            ("exec_file_path", exec_file_path),
            ("build_log_path", build_log_path),
            ("source_snapshot_path", source_snapshot_path),
            ("error_message", error_message),
        ):
            if v is not None:
                values[k] = v
        await self.db.execute(
            update(JavaCoverageReport).where(JavaCoverageReport.id == report_id).values(**values)
        )
        await self.db.flush()
