"""
系统配置模型
"""
from sqlalchemy import Column, Integer, String, Text, Boolean

from app.db.base import Base
from app.db.base_model import BaseModel


class SystemConfig(Base, BaseModel):
    """系统配置表"""

    __tablename__ = "system_configs"
    __table_args__ = {"comment": "系统配置表"}

    config_key = Column(String(100), unique=True, nullable=False, index=True, comment="配置键")
    config_value = Column(Text, nullable=True, comment="配置值")
    config_type = Column(String(20), nullable=False, server_default="string", comment="值类型: string/json/int/bool")
    description = Column(String(500), nullable=True, comment="配置说明")
    is_encrypted = Column(Boolean, nullable=False, server_default="0", comment="是否加密存储")

    def __repr__(self):
        return f"<SystemConfig(key={self.config_key}, type={self.config_type})>"
