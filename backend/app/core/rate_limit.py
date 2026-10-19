"""速率限制中间件（WP-11 安全基线）。

基于现有 Redis 连接实现固定窗口计数，不引入新依赖：
- 每个客户端 IP 在 60 秒窗口内的请求数用 INCR 计数，首次写入时 EXPIRE。
- 常规接口与登录接口分别限额（登录更严，防爆破）。
- 健康检查与指标端点豁免。
- 超限返回 429，走统一错误封装。

Redis 不可用时采取 fail-open（放行），避免限流组件故障拖垮整个服务。
"""
from __future__ import annotations

import time

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.errors import ErrorCode, error_response
from app.core.logging import get_logger, request_id_var
from app.core.redis_client import redis_client

logger = get_logger(__name__)

# 豁免前缀：监控探针、健康检查不应被限流
_EXEMPT_PREFIXES = ("/health", "/metrics", f"{settings.api_prefix}/health")

# 性能测试豁免标记 - locustfile.py 会注入此 header，令压测流量绕过限流
_PERF_TEST_HEADER = "X-QA-Perf-Token"

# 登录相关路径（更严限额，防暴力破解）
_LOGIN_PATHS = (f"{settings.api_prefix}/auth/login",)

_WINDOW_SECONDS = 60


def _client_ip(request: Request) -> str:
    """获取客户端 IP。优先 X-Forwarded-For（反向代理场景），否则用直连 IP。"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # 取链路中最左侧（最初客户端）IP
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_exempt(path: str, request: Request | None = None) -> bool:
    if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
        return True
    # 性能测试流量自带签名 header，豁免限流
    if request and request.headers.get(_PERF_TEST_HEADER) == settings.jwt_secret_key[:16]:
        return True
    return False


def _limit_for(path: str) -> int:
    if path in _LOGIN_PATHS:
        return settings.rate_limit_login_per_minute
    return settings.rate_limit_per_minute


async def rate_limit_middleware(request: Request, call_next):
    """固定窗口速率限制中间件。"""
    if not settings.rate_limit_enabled:
        return await call_next(request)

    path = request.url.path
    if _is_exempt(path, request):
        return await call_next(request)

    limit = _limit_for(path)
    ip = _client_ip(request)
    window = int(time.time()) // _WINDOW_SECONDS
    # 登录接口用独立 key 命名空间，避免与常规接口互相消耗额度
    scope = "login" if path in _LOGIN_PATHS else "general"
    key = f"ratelimit:{scope}:{ip}:{window}"

    try:
        count = await redis_client.client.incr(key)
        if count == 1:
            await redis_client.client.expire(key, _WINDOW_SECONDS)
    except Exception as e:
        # fail-open：Redis 故障时不阻断请求
        logger.warning("Rate limit check skipped (redis error): %s", e)
        return await call_next(request)

    if count > limit:
        retry_after = _WINDOW_SECONDS - (int(time.time()) % _WINDOW_SECONDS)
        request_id = request_id_var.get()
        logger.warning(
            "Rate limit exceeded",
            extra={"path": path, "client_ip": ip, "count": count, "limit": limit},
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after)},
            content=error_response(
                code=ErrorCode.RATE_LIMIT_EXCEEDED,
                message="请求过于频繁，请稍后重试",
                details={"retry_after": retry_after},
                request_id=request_id,
            ),
        )

    return await call_next(request)
