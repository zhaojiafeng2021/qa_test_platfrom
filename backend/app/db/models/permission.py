"""Project RBAC roles, functional permissions, and data visibility policies."""
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
    text,
)
from sqlalchemy import JSON
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.db.base_model import SoftDeleteMixin
from app.core.snowflake import generate_id


class Role(Base, SoftDeleteMixin):
    """Built-in role template or a project-owned custom role."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_roles_project_code"),
        Index("ix_roles_project_builtin", "project_id", "is_builtin"),
        {"comment": "RBAC角色定义"},
    )

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    project_id = Column(
        BigInteger,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=True,
        comment="自定义角色所属项目；内置角色为空",
    )
    code = Column(String(64), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    scope = Column(String(20), nullable=False, default="project", comment="platform/project")
    is_builtin = Column(Boolean, nullable=False, default=False)
    parent_role_id = Column(BigInteger, ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    permissions = relationship(
        "Permission",
        secondary="role_permissions",
        lazy="selectin",
        order_by="Permission.sort_order",
    )
    direct_permissions = relationship(
        "Permission",
        secondary="role_direct_permissions",
        lazy="selectin",
        order_by="Permission.sort_order",
    )
    parent_role = relationship("Role", remote_side=[id], foreign_keys=[parent_role_id])


class Permission(Base):
    """Stable permission catalog entry used by both the API and the UI matrix."""

    __tablename__ = "permissions"
    __table_args__ = (
        Index("ix_permissions_module_sort", "module", "sort_order"),
        {"comment": "功能权限目录"},
    )

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    code = Column(String(100), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    module = Column(String(50), nullable=False)
    action = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    platform_only = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)


class RolePermission(Base):
    """Materialized effective permissions for one role."""

    __tablename__ = "role_permissions"
    __table_args__ = ({"comment": "角色有效权限关联"},)

    role_id = Column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id = Column(
        BigInteger,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class RoleDirectPermission(Base):
    """Permissions explicitly granted to a role, excluding inherited grants."""

    __tablename__ = "role_direct_permissions"
    __table_args__ = ({"comment": "角色直接授权；用于继承权限重算"},)

    role_id = Column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_id = Column(
        BigInteger,
        ForeignKey("permissions.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ProjectMemberRole(Base):
    """Many-to-many: one project member can have multiple roles."""

    __tablename__ = "project_member_roles"
    __table_args__ = ({"comment": "成员多角色关联"},)

    member_id = Column(BigInteger, ForeignKey("project_members.id", ondelete="CASCADE"), primary_key=True)
    role_id = Column(BigInteger, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)


class ProjectDataPolicy(Base):
    """Default visibility policy for one project resource type."""

    __tablename__ = "project_data_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "resource_type", name="uq_project_data_policy"),
        Index("ix_project_data_policies_project", "project_id", "resource_type"),
        {"comment": "项目资源默认数据可见范围"},
    )

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id)
    project_id = Column(BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    resource_type = Column(String(40), nullable=False, comment="api/case/report/performance_report")
    visibility_scope = Column(String(20), nullable=False, default="all", comment="all/owner/members")
    member_ids = Column(JSON, nullable=False, default=list)
    updated_by = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
