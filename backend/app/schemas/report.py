"""WP-08 报告与通知的Pydantic模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ============ ReportFile Schemas ============


class ReportFileBase(BaseModel):
    """报告文件基础模型。"""

    report_type: str = Field(..., description="html/pdf")


class ReportFileCreate(ReportFileBase):
    """创建报告文件。"""

    plan_run_id: int


class ReportFileInfo(ReportFileBase):
    """报告文件信息。"""

    id: int
    project_id: int
    plan_run_id: int
    file_path: str
    file_size: int | None
    status: str
    error_message: str | None
    download_url: str | None = Field(None, description="预签名下载URL")
    created_by: int
    created_by_name: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============ NotificationRule Schemas ============


class NotificationRuleBase(BaseModel):
    """通知规则基础模型。"""

    name: str = Field(..., max_length=200, description="规则名称")
    enabled: bool = Field(True, description="是否启用")
    trigger_type: str = Field(..., description="plan_run/execution")
    conditions_json: dict[str, Any] = Field(..., description="触发条件")
    webhook_url: str = Field(..., max_length=500, description="飞书Webhook URL")


class NotificationRuleCreate(NotificationRuleBase):
    """创建通知规则。"""

    pass


class NotificationRuleUpdate(BaseModel):
    """更新通知规则。"""

    name: str | None = Field(None, max_length=200)
    enabled: bool | None = None
    trigger_type: str | None = None
    conditions_json: dict[str, Any] | None = None
    webhook_url: str | None = Field(None, max_length=500)


class NotificationRuleInfo(NotificationRuleBase):
    """通知规则信息。"""

    id: int
    project_id: int
    created_by: int
    updated_by: int
    created_by_name: str | None = None
    updated_by_name: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ NotificationLog Schemas ============


class NotificationLogInfo(BaseModel):
    """通知日志信息。"""

    id: int
    rule_id: int
    project_id: int
    plan_run_id: int | None
    status: str
    request_json: dict[str, Any] | None
    response_json: dict[str, Any] | None
    error_message: str | None
    created_at: datetime

    class Config:
        from_attributes = True
