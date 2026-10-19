"""WP-07 test plan, schedule, and plan-run models."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Integer, String, Text
from sqlalchemy import JSON

from app.db.base import Base
from app.db.base_model import BaseModel, UserTrackingMixin, SoftDeleteMixin
from app.core.snowflake import generate_id


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TestPlan(Base, BaseModel, UserTrackingMixin, SoftDeleteMixin):
    __tablename__ = "test_plans"
    __table_args__ = {"comment": "测试计划表"}

    project_id = Column(BigInteger, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    environment_id = Column(BigInteger, nullable=True)
    concurrency = Column(Integer, nullable=False, default=1)
    failure_strategy = Column(String(20), nullable=False, default="continue")
    status = Column(String(20), nullable=False, default="draft", index=True)
    owner_id = Column(BigInteger, nullable=True)
    due_date = Column(Date, nullable=True)
    notification_channel_id = Column(BigInteger, nullable=True, comment="通知渠道ID")
    notification_template_code = Column(String(50), nullable=True, comment="通知模板代码")
    notification_rule_ids = Column(JSON, nullable=True, comment="关联的通知规则ID列表")


class PlanItem(Base, BaseModel):
    __tablename__ = "plan_items"
    __table_args__ = {"comment": "测试计划用例项表"}

    plan_id = Column(BigInteger, nullable=False, index=True)
    project_id = Column(BigInteger, nullable=False, index=True)
    case_id = Column(BigInteger, nullable=False, index=True)
    case_type = Column(String(20), nullable=False, default="manual", index=True,
                       comment="用例类型: manual(手工)/code(代码)")
    case_version = Column(Integer, nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)


class Schedule(Base, BaseModel, UserTrackingMixin, SoftDeleteMixin):
    __tablename__ = "schedules"
    __table_args__ = {"comment": "测试计划调度表"}

    project_id = Column(BigInteger, nullable=False, index=True)
    plan_id = Column(BigInteger, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    cron_expression = Column(String(100), nullable=False)
    timezone = Column(String(64), nullable=False, default="UTC")
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    next_run_at = Column(DateTime, nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    last_status = Column(String(20), nullable=True)


class PlanRun(Base):
    __tablename__ = "plan_runs"
    __table_args__ = {"comment": "测试计划运行表"}

    id = Column(BigInteger, primary_key=True, default=generate_id)
    project_id = Column(BigInteger, nullable=False, index=True)
    plan_id = Column(BigInteger, nullable=False, index=True)
    trigger_type = Column(String(20), nullable=False)
    trigger_by = Column(BigInteger, nullable=True)
    environment_id = Column(BigInteger, nullable=True)
    concurrency = Column(Integer, nullable=False)
    failure_strategy = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    idempotency_key = Column(String(100), nullable=True, index=True)
    total_items = Column(Integer, nullable=False, default=0)
    passed_items = Column(Integer, nullable=False, default=0)
    failed_items = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=_utc_now, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)


class PlanRunItem(Base):
    __tablename__ = "plan_run_items"
    __table_args__ = {"comment": "测试计划运行用例项关联表"}

    id = Column(BigInteger, primary_key=True, default=generate_id)
    plan_run_id = Column(BigInteger, nullable=False, index=True)
    project_id = Column(BigInteger, nullable=False, index=True)
    case_id = Column(BigInteger, nullable=False, index=True)
    case_type = Column(String(20), nullable=False, default="manual", index=True,
                       comment="用例类型: manual(手工)/code(代码)")
    case_version = Column(Integer, nullable=False)
    execution_id = Column(BigInteger, nullable=True, index=True,
                          comment="手工用例执行ID(automation_case_executions)")
    code_execution_id = Column(BigInteger, nullable=True, index=True,
                               comment="代码用例执行ID(code_case_executions)")
    sort_order = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="pending", index=True)
    created_at = Column(DateTime, nullable=False, default=_utc_now)
