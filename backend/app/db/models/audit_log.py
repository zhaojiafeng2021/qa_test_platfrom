"""审计日志数据模型（记录关键写操作，供合规追溯）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.core.snowflake import generate_id


class AuditLog(Base):
    """审计日志。

    记录谁（user）在哪个项目（project）对什么资源（resource_type/resource_id）
    做了什么操作（action），以及可选的详情快照（detail_json）与来源 IP。
    project_id 可空：全局操作（如项目创建前）不属于任何项目。
    """

    __tablename__ = "audit_logs"
    __table_args__ = {"comment": "审计日志"}

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True, comment="操作者用户ID")
    project_id = Column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True, comment="所属项目ID（全局操作为空）")
    action = Column(String(100), nullable=False, index=True, comment="操作动作，如 create/update/delete/run")
    resource_type = Column(String(50), nullable=False, index=True, comment="资源类型，如 environment/automation_case/test_plan")
    resource_id = Column(String(50), nullable=True, comment="资源ID（字符串以兼容各类主键）")
    detail_json = Column(JSON, nullable=True, comment="操作详情快照")
    ip_address = Column(String(64), nullable=True, comment="来源IP")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    # relationships
    user = relationship("User", foreign_keys=[user_id])
    project = relationship("Project", foreign_keys=[project_id])
