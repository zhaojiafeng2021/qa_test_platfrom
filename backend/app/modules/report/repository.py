"""WP-08 报告与通知的数据访问层。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.report import NotificationLog, NotificationRule, ReportFile


class ReportFileRepository:
    """报告文件数据访问层。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        project_id: int,
        report_type: str,
        file_path: str,
        created_by: int,
        plan_run_id: int,
        file_size: int | None = None,
    ) -> ReportFile:
        """创建报告文件记录。"""
        report = ReportFile(
            project_id=project_id,
            plan_run_id=plan_run_id,
            report_type=report_type,
            file_path=file_path,
            file_size=file_size,
            status="pending",
            created_by=created_by,
        )
        self.db.add(report)
        await self.db.flush()
        return report

    async def get(self, report_id: int) -> Optional[ReportFile]:
        """根据ID获取报告文件。"""
        result = await self.db.execute(
            select(ReportFile).where(ReportFile.id == report_id)
        )
        return result.scalar_one_or_none()

    async def list_by_plan_run(self, plan_run_id: int) -> list[ReportFile]:
        """列出某个计划运行的所有报告。"""
        result = await self.db.execute(
            select(ReportFile)
            .where(ReportFile.plan_run_id == plan_run_id)
            .order_by(ReportFile.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_project(
        self,
        project_id: int,
        page: int = 1,
        page_size: int = 20,
        report_type: str | None = None,
        started_from: str | None = None,
        started_to: str | None = None,
    ) -> tuple[int, list[ReportFile]]:
        """分页列出项目的所有报告（支持类型和日期范围筛选）。"""
        stmt = select(ReportFile).where(ReportFile.project_id == project_id)

        if report_type:
            stmt = stmt.where(ReportFile.report_type == report_type)

        if started_from:
            from datetime import datetime
            started_from_dt = datetime.fromisoformat(started_from.replace('Z', '+00:00'))
            stmt = stmt.where(ReportFile.created_at >= started_from_dt)

        if started_to:
            from datetime import datetime
            started_to_dt = datetime.fromisoformat(started_to.replace('Z', '+00:00'))
            stmt = stmt.where(ReportFile.created_at <= started_to_dt)

        total = (
            await self.db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        result = await self.db.execute(
            stmt.order_by(ReportFile.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return total, list(result.scalars().all())

    async def update_status(
        self,
        report_id: int,
        status: str,
        file_size: int | None = None,
        error_message: str | None = None,
    ):
        """更新报告状态。"""
        report = await self.get(report_id)
        if report:
            report.status = status
            if file_size is not None:
                report.file_size = file_size
            if error_message is not None:
                report.error_message = error_message
            await self.db.flush()

    async def delete(self, report_id: int):
        """删除报告记录。"""
        report = await self.get(report_id)
        if report:
            await self.db.delete(report)
            await self.db.flush()


class NotificationRuleRepository:
    """通知规则数据访问层。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        project_id: int,
        name: str,
        trigger_type: str,
        conditions_json: dict,
        webhook_url: str,
        enabled: bool,
        created_by: int,
    ) -> NotificationRule:
        """创建通知规则。"""
        rule = NotificationRule(
            project_id=project_id,
            name=name,
            trigger_type=trigger_type,
            conditions_json=conditions_json,
            webhook_url=webhook_url,
            enabled=enabled,
            created_by=created_by,
            updated_by=created_by,
        )
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def get(self, rule_id: int) -> Optional[NotificationRule]:
        """根据ID获取通知规则。"""
        result = await self.db.execute(
            select(NotificationRule).where(NotificationRule.id == rule_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: int) -> list[NotificationRule]:
        """列出项目的所有通知规则。"""
        result = await self.db.execute(
            select(NotificationRule)
            .where(NotificationRule.project_id == project_id)
            .order_by(NotificationRule.id.desc())
        )
        return list(result.scalars().all())

    async def list_enabled_by_trigger(
        self, project_id: int, trigger_type: str
    ) -> list[NotificationRule]:
        """列出启用的通知规则（按触发类型过滤）。"""
        result = await self.db.execute(
            select(NotificationRule)
            .where(
                NotificationRule.project_id == project_id,
                NotificationRule.trigger_type == trigger_type,
                NotificationRule.enabled == True,
            )
            .order_by(NotificationRule.id)
        )
        return list(result.scalars().all())

    async def update(
        self, rule_id: int, updated_by: int, **kwargs
    ) -> Optional[NotificationRule]:
        """更新通知规则。"""
        rule = await self.get(rule_id)
        if not rule:
            return None
        for key, value in kwargs.items():
            if value is not None and hasattr(rule, key):
                setattr(rule, key, value)
        rule.updated_by = updated_by
        await self.db.flush()
        return rule

    async def delete(self, rule_id: int):
        """删除通知规则。"""
        rule = await self.get(rule_id)
        if rule:
            await self.db.delete(rule)
            await self.db.flush()


class NotificationLogRepository:
    """通知日志数据访问层。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        rule_id: int,
        project_id: int,
        status: str,
        plan_run_id: int | None = None,
        request_json: dict | None = None,
        response_json: dict | None = None,
        error_message: str | None = None,
    ) -> NotificationLog:
        """创建通知日志。"""
        log = NotificationLog(
            rule_id=rule_id,
            project_id=project_id,
            plan_run_id=plan_run_id,
            status=status,
            request_json=request_json,
            response_json=response_json,
            error_message=error_message,
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def list_by_rule(
        self, rule_id: int, page: int = 1, page_size: int = 20
    ) -> tuple[int, list[NotificationLog]]:
        """分页列出某规则的通知日志。"""
        stmt = select(NotificationLog).where(NotificationLog.rule_id == rule_id)
        total = (
            await self.db.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        result = await self.db.execute(
            stmt.order_by(NotificationLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return total, list(result.scalars().all())
