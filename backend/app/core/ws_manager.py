"""WebSocket 连接管理 + Redis pub/sub 跨进程桥接

场景：arq worker 进程 publish 进度 → FastAPI 进程 subscribe 后广播给所有 WS 客户端。

设计要点：
- ConnectionManager 按 channel 维护 WebSocket 集合，线程/协程安全（asyncio.Lock）
- 每个 channel 第一次有连接时启动一个 subscriber task，最后断开时取消
- subscriber task 独立消费 Redis pub/sub，消息 fan-out 给当前 channel 的所有 WS
- 单个 WS 发送失败不影响其他客户端，失败连接会被移除
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from app.core.redis_client import redis_client

logger = logging.getLogger(__name__)


class ConnectionManager:
    """按 channel 管理 WS 连接 + Redis 订阅任务"""

    def __init__(self) -> None:
        # channel → set[WebSocket]
        self._connections: dict[str, set[WebSocket]] = {}
        # channel → asyncio.Task（Redis subscriber 协程）
        self._subscriber_tasks: dict[str, asyncio.Task] = {}
        # channel → asyncio.Lock（保护该 channel 的连接集合增删）
        self._locks: dict[str, asyncio.Lock] = {}
        # 保护 _locks 字典本身
        self._global_lock = asyncio.Lock()

    async def _get_lock(self, channel: str) -> asyncio.Lock:
        async with self._global_lock:
            if channel not in self._locks:
                self._locks[channel] = asyncio.Lock()
            return self._locks[channel]

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        """登记连接；若是该 channel 第一个连接，启动 Redis subscriber"""
        lock = await self._get_lock(channel)
        async with lock:
            self._connections.setdefault(channel, set()).add(websocket)
            if channel not in self._subscriber_tasks or self._subscriber_tasks[channel].done():
                self._subscriber_tasks[channel] = asyncio.create_task(
                    self._redis_subscriber(channel),
                    name=f"ws-sub-{channel}",
                )
                logger.info(f"Started Redis subscriber for channel={channel}")
        logger.info(f"WS connected channel={channel} total={len(self._connections[channel])}")

    async def disconnect(self, channel: str, websocket: WebSocket) -> None:
        """移除连接；若该 channel 已无连接，取消 Redis subscriber"""
        lock = await self._get_lock(channel)
        async with lock:
            conns = self._connections.get(channel)
            if conns and websocket in conns:
                conns.discard(websocket)
            remaining = len(conns) if conns else 0
            if remaining == 0:
                self._connections.pop(channel, None)
                task = self._subscriber_tasks.pop(channel, None)
                if task and not task.done():
                    task.cancel()
                    logger.info(f"Cancelled Redis subscriber for channel={channel}")
        logger.info(f"WS disconnected channel={channel} remaining={remaining}")

    async def broadcast(self, channel: str, message: dict[str, Any]) -> None:
        """向 channel 下所有 WS 广播；发送失败的连接被移除"""
        conns = list(self._connections.get(channel, ()))
        if not conns:
            return
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"WS send failed channel={channel}: {e}")
                dead.append(ws)
        if dead:
            lock = await self._get_lock(channel)
            async with lock:
                for ws in dead:
                    self._connections.get(channel, set()).discard(ws)

    async def _redis_subscriber(self, channel: str) -> None:
        """后台协程：订阅 Redis channel → fan-out 到本地 WS 集合"""
        pubsub = redis_client.pubsub()
        try:
            await pubsub.subscribe(channel)
            logger.info(f"Redis subscribed channel={channel}")
            async for raw in pubsub.listen():
                if raw is None:
                    continue
                if raw.get("type") != "message":
                    continue
                data = raw.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                try:
                    msg = json.loads(data)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Invalid JSON from Redis channel={channel}: {data!r}")
                    continue
                await self.broadcast(channel, msg)
        except asyncio.CancelledError:
            logger.info(f"Redis subscriber cancelled channel={channel}")
            raise
        except Exception:
            logger.exception(f"Redis subscriber crashed channel={channel}")
        finally:
            try:
                await pubsub.unsubscribe(channel)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass


# 全局单例（FastAPI 进程内共享）
ws_manager = ConnectionManager()
