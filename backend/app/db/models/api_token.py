"""
个人访问令牌（PAT）模型

面向机器账号 / CICD 集成的长期 Token：
- 可自定义有效期（expires_at 为空表示永不过期）
- 可随时吊销（is_active=false 或删除记录）
- DB 仅存储 token 的 sha256 哈希，明文仅创建时返回一次
"""
from sqlalchemy import BigInteger, Column, Integer, String, Boolean, DateTime, ForeignKey

from app.db.base import Base
from app.db.base_model import BaseModel


class ApiToken(Base, BaseModel):
    """个人访问令牌表"""

    __tablename__ = "api_tokens"
    __table_args__ = {"comment": "个人访问令牌（PAT），用于 CICD 等机器账号长期认证"}

    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户ID",
    )
    name = Column(String(100), nullable=False, comment="令牌名称/用途标识")
    token_hash = Column(String(64), unique=True, nullable=False, index=True, comment="令牌sha256哈希")
    token_prefix = Column(String(16), nullable=False, comment="令牌前缀（展示用，如 qat_abc123）")
    expires_at = Column(DateTime, nullable=True, comment="过期时间，空=永不过期")
    last_used_at = Column(DateTime, nullable=True, comment="最后使用时间")
    is_active = Column(Boolean, default=True, nullable=False, comment="是否有效")

    def __repr__(self):
        return f"<ApiToken(id={self.id}, user_id={self.user_id}, name={self.name})>"
