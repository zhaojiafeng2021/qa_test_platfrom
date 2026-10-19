"""
通用数据库模型基类和混入类
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy import Column, Integer, BigInteger, DateTime, String, Boolean
from sqlalchemy.ext.declarative import declared_attr

from app.core.snowflake import generate_id


class TimestampMixin:
    """时间戳混入类"""

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, comment="创建时间")
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
        comment="更新时间"
    )


class SoftDeleteMixin:
    """软删除混入类"""

    is_deleted = Column(Boolean, default=False, nullable=False, server_default="0", comment="是否已删除")
    deleted_at = Column(DateTime, nullable=True, comment="删除时间")

    def soft_delete(self, user_id: int | None = None) -> None:
        """标记为已删除"""
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()
        if user_id is not None and hasattr(self, 'updated_by'):
            self.updated_by = user_id

    @classmethod
    def alive(cls):
        """返回未删除记录的过滤条件"""
        return cls.is_deleted == False


class ProjectScopeMixin:
    """项目范围混入类"""

    @declared_attr
    def project_id(cls):
        return Column(BigInteger, nullable=False, index=True, comment="项目ID")


class UserTrackingMixin:
    """用户追踪混入类"""

    @declared_attr
    def created_by(cls):
        return Column(BigInteger, nullable=True, comment="创建者ID")

    @declared_attr
    def updated_by(cls):
        return Column(BigInteger, nullable=True, comment="更新者ID")


class BaseModel(TimestampMixin):
    """基础模型类"""

    id = Column(BigInteger, primary_key=True, index=True, default=generate_id, comment="主键ID")

    def dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            column.name: getattr(self, column.name)
            for column in self.__table__.columns
        }
