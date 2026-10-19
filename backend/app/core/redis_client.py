"""
Redis客户端模块
提供缓存、分布式锁、状态存储等功能
"""
from typing import Optional, Any
import secrets
import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisClient:
    """Redis客户端封装"""

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def connect(self):
        """连接Redis"""
        if self._client is None:
            self._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                protocol=2
            )
            logger.info("Redis client connected")

    async def disconnect(self):
        """断开Redis连接"""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis client disconnected")

    @property
    def client(self) -> redis.Redis:
        """获取Redis客户端"""
        if self._client is None:
            self._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                protocol=2
            )
        return self._client

    async def set(self, key: str, value: str, expire: Optional[int] = None) -> None:
        """
        设置键值

        Args:
            key: 键
            value: 值
            expire: 过期时间（秒）
        """
        await self.client.set(key, value, ex=expire)

    async def get(self, key: str) -> Optional[str]:
        """获取值"""
        return await self.client.get(key)

    async def delete(self, key: str) -> None:
        """删除键"""
        await self.client.delete(key)

    async def exists(self, key: str) -> bool:
        """检查键是否存在"""
        return await self.client.exists(key) > 0

    async def setex(self, key: str, seconds: int, value: str) -> None:
        """设置带过期时间的键值"""
        await self.client.setex(key, seconds, value)

    async def acquire_token_lock(self, lock_key: str, expire: int = 30) -> Optional[str]:
        """Acquire a lock and return an ownership token."""
        token = secrets.token_urlsafe(24)
        result = await self.client.set(lock_key, token, nx=True, ex=expire)
        return token if result is True else None

    async def release_token_lock(self, lock_key: str, token: str) -> bool:
        """Release a lock only while it is still owned by this caller."""
        script = """
        if redis.call('get', KEYS[1]) == ARGV[1] then
          return redis.call('del', KEYS[1])
        end
        return 0
        """
        return bool(await self.client.eval(script, 1, lock_key, token))

    async def acquire_lock(self, lock_key: str, expire: int = 30) -> bool:
        """
        获取分布式锁

        Args:
            lock_key: 锁的键
            expire: 锁的过期时间（秒）

        Returns:
            是否成功获取锁
        """
        result = await self.client.set(lock_key, "1", nx=True, ex=expire)
        return result is True

    async def release_lock(self, lock_key: str) -> None:
        """释放分布式锁"""
        await self.client.delete(lock_key)

    async def publish(self, channel: str, message: str) -> int:
        """发布消息到频道（SSE 实时通道），返回收到消息的订阅者数量。"""
        return await self.client.publish(channel, message)

    def pubsub(self):
        """返回一个绑定到当前连接池的 PubSub 对象。

        调用方负责 subscribe/unsubscribe/aclose。decode_responses=True 时
        收到的 message["data"] 为 str，无需 decode。
        """
        return self.client.pubsub()

    async def ping(self) -> bool:
        """健康检查"""
        try:
            return await self.client.ping()
        except Exception as e:
            logger.error(f"Redis ping failed: {str(e)}")
            return False


# 全局Redis客户端实例
redis_client = RedisClient()
