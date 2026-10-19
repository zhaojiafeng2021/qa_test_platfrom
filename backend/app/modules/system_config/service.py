"""
系统配置服务
提供配置的读取、更新、缓存功能
"""
import json
from typing import Optional, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.system_config import SystemConfig
from app.core.logging import get_logger
from app.core.redis_client import redis_client

logger = get_logger(__name__)

# Redis 缓存键前缀
CACHE_PREFIX = "sys_config:"
CACHE_TTL = 300  # 5分钟缓存


class SystemConfigService:
    """系统配置服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_config(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（带缓存）

        Args:
            key: 配置键
            default: 默认值

        Returns:
            配置值（根据 config_type 自动转换类型）
        """
        # 先从缓存读取
        cache_key = f"{CACHE_PREFIX}{key}"
        cached = await redis_client.get(cache_key)
        if cached:
            return self._parse_value(cached, "string")

        # 从数据库读取
        result = await self.db.execute(
            select(SystemConfig).where(SystemConfig.config_key == key)
        )
        config = result.scalar_one_or_none()

        if not config or not config.config_value:
            return default

        value = self._parse_value(config.config_value, config.config_type)

        # 写入缓存
        await redis_client.setex(cache_key, CACHE_TTL, str(config.config_value))

        return value

    async def set_config(self, key: str, value: Any, config_type: str = "string", description: str = None) -> None:
        """
        设置配置值

        Args:
            key: 配置键
            value: 配置值
            config_type: 值类型 (string/json/int/bool)
            description: 配置说明
        """
        # 查找已有配置
        result = await self.db.execute(
            select(SystemConfig).where(SystemConfig.config_key == key)
        )
        config = result.scalar_one_or_none()

        # 将值转为字符串存储
        str_value = self._stringify_value(value, config_type)

        if config:
            # 更新
            config.config_value = str_value
            if config_type:
                config.config_type = config_type
            if description:
                config.description = description
        else:
            # 新增
            config = SystemConfig(
                config_key=key,
                config_value=str_value,
                config_type=config_type,
                description=description,
            )
            self.db.add(config)

        await self.db.flush()
        await self.db.commit()

        # 清除缓存
        await redis_client.delete(f"{CACHE_PREFIX}{key}")

    async def get_feishu_config(self) -> Dict[str, str]:
        """获取飞书配置"""
        return {
            "app_id": await self.get_config("feishu.app_id", ""),
            "app_secret": await self.get_config("feishu.app_secret", ""),
            "redirect_uri": await self.get_config("feishu.redirect_uri", ""),
            "webhook_url": await self.get_config("feishu.webhook_url", ""),
        }

    def _parse_value(self, value: str, config_type: str) -> Any:
        """将字符串值解析为对应类型"""
        if not value:
            return None

        try:
            if config_type == "int":
                return int(value)
            elif config_type == "bool":
                return value.lower() in ("true", "1", "yes")
            elif config_type == "json":
                return json.loads(value)
            else:  # string
                return value
        except Exception as e:
            logger.warning(f"Failed to parse config value: {e}")
            return value

    def _stringify_value(self, value: Any, config_type: str) -> str:
        """将值转为字符串"""
        if config_type == "json":
            return json.dumps(value, ensure_ascii=False)
        else:
            return str(value)
