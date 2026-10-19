"""
项目模型
"""
from sqlalchemy import BigInteger, Column, Integer, String, Text, Enum as SQLEnum, JSON, Boolean
from sqlalchemy.orm import relationship
import enum

from app.db.base import Base
from app.db.base_model import BaseModel, UserTrackingMixin


class ProjectStatus(str, enum.Enum):
    """项目状态"""
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class Project(Base, BaseModel, UserTrackingMixin):
    """项目表"""

    __tablename__ = "projects"
    __table_args__ = {"comment": "项目表"}

    # 基本信息
    code = Column(String(50), unique=True, nullable=False, index=True, comment="项目代码（唯一标识）")
    name = Column(String(100), nullable=False, comment="项目名称")
    description = Column(Text, nullable=True, comment="项目描述")

    # 负责人
    owner_id = Column(BigInteger, nullable=False, index=True, comment="项目负责人ID")

    # 状态
    status = Column(
        SQLEnum(ProjectStatus, values_callable=lambda x: [e.value for e in x]),
        default=ProjectStatus.ACTIVE,
        nullable=False,
        index=True,
        comment="项目状态"
    )

    # 配置
    icon = Column(String(100), nullable=True, comment="项目图标")
    color = Column(String(20), nullable=True, comment="项目颜色")
    is_public = Column(Boolean, nullable=False, default=False, server_default='0', comment="是否公开项目（所有用户可见）")
    grafana_config_json = Column(
        JSON,
        nullable=True,
        comment='Grafana全局配置: {"url": "http://grafana.example.com", "token": "glsa_xxx", "datasource_uid": "prometheus-uid", "cluster": "cluster-name"}'
    )

    def __repr__(self):
        return f"<Project(id={self.id}, code={self.code}, name={self.name})>"
