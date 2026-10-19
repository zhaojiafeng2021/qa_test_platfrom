"""
用户模型
"""
from sqlalchemy import Column, Integer, String, Boolean, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.db.base import Base
from app.db.base_model import BaseModel


class UserStatus(str, enum.Enum):
    """用户状态"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"


class User(Base, BaseModel):
    """用户表"""

    __tablename__ = "users"
    __table_args__ = {"comment": "用户表"}

    # 基本信息
    username = Column(String(50), unique=True, nullable=False, index=True, comment="用户名")
    email = Column(String(100), unique=True, nullable=False, index=True, comment="邮箱")
    password_hash = Column(String(255), nullable=True, comment="密码哈希（本地登录）")
    full_name = Column(String(100), nullable=True, comment="全名")
    avatar_url = Column(String(500), nullable=True, comment="头像URL")

    # 飞书相关
    feishu_open_id = Column(String(100), unique=True, nullable=True, index=True, comment="飞书OpenID")
    feishu_union_id = Column(String(100), nullable=True, comment="飞书UnionID")

    # 状态
    status = Column(
        SQLEnum(UserStatus, values_callable=lambda x: [e.value for e in x]),
        default=UserStatus.ACTIVE,
        nullable=False,
        comment="用户状态"
    )
    is_superuser = Column(Boolean, default=False, nullable=False, comment="是否超级管理员")

    # 最后登录
    last_login_at = Column(String(50), nullable=True, comment="最后登录时间")
    last_login_ip = Column(String(50), nullable=True, comment="最后登录IP")

    # 关系
    # project_members = relationship("ProjectMember", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"
