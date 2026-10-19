"""API contracts and stable catalogs for the notification center."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EVENT_CATALOG = [
    {"code": "execution.completed", "name": "执行完成", "description": "测试计划或用例执行完成"},
    {"code": "execution.failed", "name": "执行失败", "description": "测试执行失败或异常"},
    {"code": "schedule.failed", "name": "定时任务失败", "description": "调度任务执行失败"},
    {"code": "performance.completed", "name": "压测完成", "description": "性能测试运行完成"},
    {"code": "performance.threshold_breached", "name": "压测指标异常", "description": "错误率或响应时间超过阈值"},
    {"code": "member.permission_changed", "name": "成员权限变更", "description": "成员角色或权限发生变化"},
    {"code": "daily.summary.ready", "name": "每日测试摘要", "description": "每日汇总数据生成完成"},
]
EVENT_CODES = {item["code"] for item in EVENT_CATALOG}

TEMPLATE_CATALOG = [
    {"code": "execution_summary", "name": "执行结果摘要", "event_types": ["execution.completed"], "tone": "success"},
    {"code": "failure_alert", "name": "执行失败告警", "event_types": ["execution.failed", "schedule.failed"], "tone": "danger"},
    {"code": "performance_summary", "name": "压测结果摘要", "event_types": ["performance.completed"], "tone": "success"},
    {"code": "threshold_alert", "name": "性能指标异常", "event_types": ["performance.threshold_breached"], "tone": "warning"},
    {"code": "permission_change", "name": "权限变更通知", "event_types": ["member.permission_changed"], "tone": "info"},
    {"code": "daily_summary", "name": "每日测试摘要", "event_types": ["daily.summary.ready"], "tone": "info"},
]
TEMPLATE_CODES = {item["code"] for item in TEMPLATE_CATALOG}
RECIPIENT_TYPES = {"all_members", "project_admins", "event_owner", "affected_member", "custom"}


class ChannelBase(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    enabled: bool = True


class ChannelCreate(ChannelBase):
    webhook_url: str = Field(min_length=20, max_length=500)


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    webhook_url: str | None = Field(default=None, min_length=20, max_length=500)
    enabled: bool | None = None


class ChannelInfo(ChannelBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    channel_type: str
    webhook_masked: str
    last_test_status: str | None
    last_test_at: datetime | None
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelTestRequest(BaseModel):
    message: str = Field(default="QA 自动化平台飞书通知测试成功", min_length=1, max_length=200)


class RuleBase(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    event_type: str
    channel_id: int
    template_code: str = "execution_summary"
    recipient_type: str = "all_members"
    recipient_config: dict[str, Any] = Field(default_factory=dict)
    conditions_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in EVENT_CODES:
            raise ValueError("不支持的事件类型")
        return value

    @field_validator("template_code")
    @classmethod
    def validate_template(cls, value: str) -> str:
        if value not in TEMPLATE_CODES:
            raise ValueError("不支持的消息模板")
        return value

    @field_validator("recipient_type")
    @classmethod
    def validate_recipient_type(cls, value: str) -> str:
        if value not in RECIPIENT_TYPES:
            raise ValueError("不支持的接收人类型")
        return value

    @model_validator(mode="after")
    def validate_custom_recipients(self):
        if self.recipient_type == "custom" and not self.recipient_config.get("member_ids"):
            raise ValueError("自定义接收人至少需要选择一名成员")
        return self


class RuleCreate(RuleBase):
    pass


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    event_type: str | None = None
    channel_id: int | None = None
    template_code: str | None = None
    recipient_type: str | None = None
    recipient_config: dict[str, Any] | None = None
    conditions_json: dict[str, Any] | None = None
    enabled: bool | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str | None) -> str | None:
        if value is not None and value not in EVENT_CODES:
            raise ValueError("不支持的事件类型")
        return value

    @field_validator("template_code")
    @classmethod
    def validate_template(cls, value: str | None) -> str | None:
        if value is not None and value not in TEMPLATE_CODES:
            raise ValueError("不支持的消息模板")
        return value

    @field_validator("recipient_type")
    @classmethod
    def validate_recipient_type(cls, value: str | None) -> str | None:
        if value is not None and value not in RECIPIENT_TYPES:
            raise ValueError("不支持的接收人类型")
        return value


class RuleInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    enabled: bool
    event_type: str
    channel_id: int | None
    channel_name: str | None = None
    template_code: str
    recipient_type: str
    recipient_config: dict[str, Any]
    conditions_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DeliveryInfo(BaseModel):
    id: int
    project_id: int
    rule_id: int | None
    rule_name: str | None = None
    channel_id: int | None
    channel_name: str | None = None
    event_id: str
    event_type: str
    status: Literal["pending", "sending", "sent", "retrying", "failed", "skipped"]
    attempt_count: int
    max_attempts: int
    next_attempt_at: datetime | None
    error_message: str | None
    message_summary: str | None
    created_at: datetime
    sent_at: datetime | None


class EventEmitRequest(BaseModel):
    event_id: str = Field(min_length=3, max_length=160)
    event_type: str
    context: dict[str, Any] = Field(default_factory=dict)
    summary: str = Field(min_length=1, max_length=300)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in EVENT_CODES:
            raise ValueError("不支持的事件类型")
        return value
