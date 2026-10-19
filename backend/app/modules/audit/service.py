"""审计日志业务逻辑层。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.core.logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.repository import AuditLogRepository
from app.schemas.audit import AuditLogInfo

logger = get_logger(__name__)


class AuditService:
    """审计日志服务。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuditLogRepository(db)

    async def record(
        self,
        action: str,
        resource_type: str,
        user_id: int | None = None,
        project_id: int | None = None,
        resource_id: str | int | None = None,
        detail_json: dict | None = None,
        ip_address: str | None = None,
    ) -> None:
        """记录一条审计日志，并随调用方事务一起提交。"""
        await self.repo.create(
            action=action,
            resource_type=resource_type,
            user_id=user_id,
            project_id=project_id,
            resource_id=resource_id,
            detail_json=detail_json,
            ip_address=ip_address,
        )

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
    ) -> dict:
        """分页查询审计日志。"""
        total, logs = await self.repo.list_logs(
            project_id=project_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            started_from=started_from,
            started_to=started_to,
            page=page,
            page_size=page_size,
        )
        items = [AuditLogInfo(
            **{**AuditLogInfo.model_validate(log).model_dump(),
               "username": user.username if user else None,
               "full_name": user.full_name if user else None},
        ) for log, user in logs]
        return {"total": total, "items": items}
