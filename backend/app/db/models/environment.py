"""
测试环境模型
"""
from sqlalchemy import BigInteger, Column, Integer, String, Text, Boolean, JSON
import enum

from app.db.base import Base
from app.db.base_model import BaseModel, UserTrackingMixin, SoftDeleteMixin


class Environment(Base, BaseModel, UserTrackingMixin, SoftDeleteMixin):
    """测试环境表"""

    __tablename__ = "environments"
    __table_args__ = {"comment": "测试环境表"}

    # 所属项目
    project_id = Column(BigInteger, nullable=False, index=True, comment="项目ID")

    # 基本信息
    name = Column(String(100), nullable=False, comment="环境名称（如 dev、test、prod）")
    display_name = Column(String(100), nullable=False, comment="环境显示名称")
    description = Column(Text, nullable=True, comment="环境描述")

    # 基础配置
    base_url = Column(String(500), nullable=True, comment="环境基础URL")

    # 排序
    sort_order = Column(Integer, default=0, nullable=False, comment="排序权重")

    # 状态
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")

    # Grafana 监控配置
    grafana_target_json = Column(
        JSON,
        nullable=True,
        comment='Grafana监控目标配置: {"namespace": "crm-pre", "pod_pattern": "crm-backend-.*", "dashboard_uid": "2dfs3v8nz"}'
    )

    def __repr__(self):
        return f"<Environment(id={self.id}, name={self.name}, project_id={self.project_id})>"


class VariableScope(str, enum.Enum):
    """变量作用域"""
    GLOBAL = "global"      # 全局变量（项目级）
    ENVIRONMENT = "environment"  # 环境变量（环境级）


class Variable(Base, BaseModel, UserTrackingMixin, SoftDeleteMixin):
    """环境变量表"""

    __tablename__ = "variables"
    __table_args__ = {"comment": "环境变量表"}

    # 所属
    project_id = Column(BigInteger, nullable=False, index=True, comment="项目ID")
    environment_id = Column(BigInteger, nullable=True, index=True, comment="环境ID（scope=environment时必填）")

    # 作用域
    scope = Column(String(20), nullable=False, index=True, comment="作用域: global/environment")

    # 变量信息
    key = Column(String(100), nullable=False, comment="变量键名")
    value = Column(Text, nullable=True, comment="变量值")
    description = Column(String(500), nullable=True, comment="变量描述")

    # 敏感标记
    is_secret = Column(Boolean, default=False, nullable=False, comment="是否为密钥变量（前端脱敏显示）")

    # 状态
    is_active = Column(Boolean, default=True, nullable=False, comment="是否启用")

    def __repr__(self):
        return f"<Variable(id={self.id}, key={self.key}, scope={self.scope})>"
