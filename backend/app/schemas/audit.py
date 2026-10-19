"""审计日志 Pydantic schema。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class AuditLogInfo(BaseModel):
    """审计日志信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    project_id: Optional[int] = None
    action: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    resource_type: str
    resource_id: Optional[str] = None
    detail_json: Optional[dict[str, Any]] = None
    ip_address: Optional[str] = None
    created_at: datetime
