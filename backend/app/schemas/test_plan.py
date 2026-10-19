"""WP-07 test plan API schemas."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class PlanItemInput(BaseModel):
    case_id: int = Field(gt=0)
    case_type: str = Field(default="manual", pattern=r"^(manual|code)$",
                           description="用例类型: manual(手工)/code(代码)")
    case_version: Optional[int] = Field(default=None, gt=0)
    sort_order: int = Field(default=0, ge=0)
    enabled: bool = True


class TestPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    environment_id: Optional[int] = Field(default=None, gt=0)
    concurrency: int = Field(default=1, ge=1, le=100)
    failure_strategy: str = Field(default="continue", pattern=r"^(continue|stop)$")
    status: str = Field(default="draft", pattern=r"^(draft|active|archived)$")
    owner_id: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[date] = None
    notification_channel_id: Optional[int] = Field(default=None, gt=0, description="通知渠道ID")
    notification_template_code: Optional[str] = Field(default=None, max_length=50, description="通知模板代码")
    notification_rule_ids: Optional[list[int]] = Field(default=None, description="关联的通知规则ID列表")
    items: list[PlanItemInput] = Field(default_factory=list)


class TestPlanUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    environment_id: Optional[int] = Field(default=None, gt=0)
    concurrency: Optional[int] = Field(default=None, ge=1, le=100)
    failure_strategy: Optional[str] = Field(default=None, pattern=r"^(continue|stop)$")
    status: Optional[str] = Field(default=None, pattern=r"^(draft|active|archived)$")
    owner_id: Optional[int] = Field(default=None, gt=0)
    due_date: Optional[date] = None
    notification_channel_id: Optional[int] = Field(default=None, gt=0, description="通知渠道ID")
    notification_template_code: Optional[str] = Field(default=None, max_length=50, description="通知模板代码")
    notification_rule_ids: Optional[list[int]] = Field(default=None, description="关联的通知规则ID列表")
    items: Optional[list[PlanItemInput]] = None


class PlanRunCreate(BaseModel):
    environment_id: Optional[int] = Field(default=None, gt=0)
    concurrency: Optional[int] = Field(default=None, ge=1, le=100)
    failure_strategy: Optional[str] = Field(default=None, pattern=r"^(continue|stop)$")


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    cron_expression: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    plan_id: Optional[int] = Field(default=None, gt=0)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    cron_expression: Optional[str] = Field(default=None, min_length=1, max_length=100)
    timezone: Optional[str] = Field(default=None, min_length=1, max_length=64)
    enabled: Optional[bool] = None


class PlanItemInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_type: str = Field(default="manual", description="用例类型: manual/code")
    case_version: int
    sort_order: int
    enabled: bool
    case_name: Optional[str] = None
    priority: Optional[str] = None
    step_count: int = 0
    module: Optional[str] = Field(None, description="代码用例模块层级")
    level: Optional[str] = Field(None, description="代码用例等级")


class TestPlanInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    name: str
    description: Optional[str]
    environment_id: Optional[int]
    concurrency: int
    failure_strategy: str
    status: str
    owner_id: Optional[int]
    due_date: Optional[date]
    notification_channel_id: Optional[int] = Field(None, description="通知渠道ID")
    notification_template_code: Optional[str] = Field(None, description="通知模板代码")
    notification_rule_ids: Optional[list[int]] = Field(None, description="关联的通知规则ID列表")
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: list[PlanItemInfo] = Field(default_factory=list)


class PlanRunItemInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_type: str = Field(default="manual", description="用例类型: manual/code")
    case_version: int
    execution_id: Optional[int] = Field(None, description="手工用例执行ID")
    code_execution_id: Optional[int] = Field(None, description="代码用例执行ID")
    sort_order: int
    status: str
    case_name: Optional[str] = None
    priority: Optional[str] = None
    module: Optional[str] = Field(None, description="代码用例模块层级")
    level: Optional[str] = Field(None, description="代码用例等级")
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    total_steps: Optional[int] = None
    passed_steps: Optional[int] = None
    failed_steps: Optional[int] = None
    logs: Optional[str] = Field(None, description="代码用例执行日志")
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class PlanRunInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plan_id: int
    project_id: int
    trigger_type: str
    status: str
    environment_id: Optional[int]
    concurrency: int
    failure_strategy: str
    total_items: int
    passed_items: int
    failed_items: int
    created_by: Optional[int] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    items: list[PlanRunItemInfo] = Field(default_factory=list)


class ScheduleInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plan_id: int
    project_id: int
    name: str
    cron_expression: str
    timezone: str
    enabled: bool
    next_run_at: Optional[datetime]
    last_run_at: Optional[datetime]
    last_status: Optional[str]
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
