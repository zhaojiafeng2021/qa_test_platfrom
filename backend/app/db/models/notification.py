"""Secure notification channels and durable delivery records."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.db.base_model import SoftDeleteMixin
from app.core.snowflake import generate_id


class NotificationChannel(Base, SoftDeleteMixin):
    """Encrypted outbound notification endpoint."""

    __tablename__ = "notification_channels"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_notification_channel_name"),
        Index("ix_notification_channels_project_enabled", "project_id", "enabled"),
        {"comment": "通知渠道（Secret加密存储）"},
    )

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    project_id = Column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    channel_type = Column(String(30), nullable=False, default="feishu_webhook")
    webhook_encrypted = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    last_test_status = Column(String(20), nullable=True)
    last_test_at = Column(DateTime(timezone=True), nullable=True)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationDelivery(Base):
    """Idempotent delivery state machine and immutable send history."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("rule_id", "event_id", name="uq_notification_delivery_event"),
        Index("ix_notification_delivery_project_time", "project_id", "created_at"),
        Index("ix_notification_delivery_retry", "status", "next_attempt_at"),
        {"comment": "可靠通知投递记录"},
    )

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    project_id = Column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(BigInteger, ForeignKey("notification_rules.id", ondelete="SET NULL"), nullable=True)
    channel_id = Column(BigInteger, ForeignKey("notification_channels.id", ondelete="SET NULL"), nullable=True)
    event_id = Column(String(160), nullable=False)
    event_type = Column(String(80), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=5)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    payload_json = Column(JSON, nullable=False)
    response_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    message_summary = Column(String(300), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    sent_at = Column(DateTime(timezone=True), nullable=True)

    rule = relationship("NotificationRule")
    channel = relationship("NotificationChannel")
