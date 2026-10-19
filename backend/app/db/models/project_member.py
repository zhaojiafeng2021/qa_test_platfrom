"""
项目成员模型
定义项目内的成员关系和角色
"""
from sqlalchemy import BigInteger, Column, Enum as SQLEnum, ForeignKey, Integer, UniqueConstraint
import enum

from app.db.base import Base
from app.db.base_model import BaseModel, SoftDeleteMixin


class ProjectRole(str, enum.Enum):
    """
    项目角色

    - OWNER: 项目负责人（拥有全部权限，含删除项目、管理成员）
    - ADMIN: 项目管理员（可管理成员、配置，不可删除项目）
    - MEMBER: 普通成员（可创建/编辑/执行测试资产）
    - VIEWER: 只读成员（仅查看）
    """
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


# 角色 -> 权限码映射（项目级RBAC）
ROLE_PERMISSIONS: dict[str, list[str]] = {
    ProjectRole.OWNER.value: ["*"],  # OWNER拥有所有权限
    ProjectRole.ADMIN.value: [
        "project:read",
        "project:update",
        "project:member:read",
        "project:member:manage",
        "asset:*",
        "execution:*",
        "menu:*",
    ],
    ProjectRole.MEMBER.value: [
        "project:read",
        "project:member:read",
        "asset:read",
        "asset:create",
        "asset:update",
        "asset:delete",
        "execution:read",
        "execution:run",
        "menu:*",
    ],
    ProjectRole.VIEWER.value: [
        "project:read",
        "project:member:read",
        "asset:read",
        "execution:read",
        "menu:*",  # 允许访问所有菜单（只读）
    ],
}


class ProjectMember(Base, BaseModel, SoftDeleteMixin):
    """项目成员表"""

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        {"comment": "项目成员表"},
    )

    project_id = Column(BigInteger, nullable=False, index=True, comment="项目ID")
    user_id = Column(BigInteger, nullable=False, index=True, comment="用户ID")
    role = Column(
        SQLEnum(ProjectRole, values_callable=lambda x: [e.value for e in x]),
        default=ProjectRole.MEMBER,
        nullable=False,
        comment="项目角色"
    )
    role_id = Column(
        BigInteger,
        ForeignKey("roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="RBAC v2角色ID；为空时回退旧role枚举",
    )
    invited_by = Column(BigInteger, nullable=True, comment="邀请人ID")

    def __repr__(self):
        return f"<ProjectMember(project_id={self.project_id}, user_id={self.user_id}, role={self.role})>"
