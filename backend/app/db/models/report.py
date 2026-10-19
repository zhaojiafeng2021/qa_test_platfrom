"""WP-08 报告与通知数据模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.db.base_model import SoftDeleteMixin
from app.core.snowflake import generate_id


class ReportFile(Base, SoftDeleteMixin):
    """测试报告文件。"""

    __tablename__ = "report_files"
    __table_args__ = (
        {"comment": "测试报告文件"},
    )

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    project_id = Column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_run_id = Column(BigInteger, ForeignKey("plan_runs.id", ondelete="CASCADE"), nullable=False, index=True, comment="关联计划运行（计划报告）")
    report_type = Column(String(20), nullable=False, comment="html/pdf")
    file_path = Column(String(500), nullable=False, comment="MinIO文件路径")
    file_size = Column(Integer, nullable=True, comment="文件大小（字节）")
    status = Column(String(20), nullable=False, default="pending", comment="pending/generated/failed")
    error_message = Column(Text, nullable=True)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    project = relationship("Project")
    plan_run = relationship("PlanRun", foreign_keys=[plan_run_id])
    creator = relationship("User", foreign_keys=[created_by])


class NotificationRule(Base, SoftDeleteMixin):
    """通知规则，保留旧字段以兼容现有报告通知调用。"""

    __tablename__ = "notification_rules"
    __table_args__ = {"comment": "通知规则"}

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    project_id = Column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False, comment="规则名称")
    enabled = Column(Boolean, nullable=False, default=True, index=True)
    trigger_type = Column(String(30), nullable=False, comment="兼容字段: plan_run/execution")
    conditions_json = Column(JSON, nullable=False, comment="触发条件")
    webhook_url = Column(String(500), nullable=True, comment="兼容字段；迁移后必须为空")
    event_type = Column(String(80), nullable=False, default="execution.completed", index=True)
    channel_id = Column(BigInteger, ForeignKey("notification_channels.id", ondelete="SET NULL"), nullable=True, index=True)
    template_code = Column(String(80), nullable=False, default="execution_summary")
    recipient_type = Column(String(30), nullable=False, default="all_members")
    recipient_config = Column(JSON, nullable=False, default=dict)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by = Column(BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project")
    channel = relationship("NotificationChannel", foreign_keys=[channel_id])
    creator = relationship("User", foreign_keys=[created_by])
    updater = relationship("User", foreign_keys=[updated_by])


class NotificationLog(Base):
    """旧通知发送日志，仅为兼容旧查询保留。"""

    __tablename__ = "notification_logs"
    __table_args__ = {"comment": "通知发送日志"}

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    rule_id = Column(BigInteger, ForeignKey("notification_rules.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_run_id = Column(BigInteger, ForeignKey("plan_runs.id", ondelete="CASCADE"), nullable=True)
    status = Column(String(20), nullable=False, comment="sent/failed/skipped")
    request_json = Column(JSON, nullable=True, comment="发送的消息体")
    response_json = Column(JSON, nullable=True, comment="webhook响应")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    rule = relationship("NotificationRule")
    project = relationship("Project")
    plan_run = relationship("PlanRun", foreign_keys=[plan_run_id])
