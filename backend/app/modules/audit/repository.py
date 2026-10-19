"""审计日志数据访问层。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog
from app.db.models.user import User


class AuditLogRepository:
    """审计日志数据访问层。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        action: str,
        resource_type: str,
        user_id: int | None = None,
        project_id: int | None = None,
        resource_id: str | None = None,
        detail_json: dict | None = None,
        ip_address: str | None = None,
    ) -> AuditLog:
        """写入一条审计日志（仅 add+flush，提交由调用方掌控）。"""
        log = AuditLog(
            action=action,
            resource_type=resource_type,
            user_id=user_id,
            project_id=project_id,
            resource_id=str(resource_id) if resource_id is not None else None,
            detail_json=detail_json,
            ip_address=ip_address,
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def list_logs(
        self,
        project_id: int,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_id: Optional[int] = None,
        started_from: Optional[datetime] = None,
        started_to: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[tuple[AuditLog, User | None]]]:
        """按项目 + 多维过滤分页列出审计日志。"""
        conditions = [AuditLog.project_id == project_id]
        if action:
            conditions.append(AuditLog.action == action)
        if resource_type:
            conditions.append(AuditLog.resource_type == resource_type)
        if resource_id:
            conditions.append(AuditLog.resource_id == resource_id)
        if user_id is not None:
            conditions.append(AuditLog.user_id == user_id)
        if started_from is not None:
            conditions.append(AuditLog.created_at >= started_from)
        if started_to is not None:
            conditions.append(AuditLog.created_at <= started_to)

        total = (
            await self.db.execute(select(func.count(AuditLog.id)).where(*conditions))
        ).scalar_one()
        result = await self.db.execute(
            select(AuditLog, User)
            .outerjoin(User, User.id == AuditLog.user_id)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return total, list(result.all())
