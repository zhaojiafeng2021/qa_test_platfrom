"""
FastAPI应用主入口
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import time

from prometheus_client import make_asgi_app
from sqlalchemy import text

from app.core.config import settings
from app.core.errors import AppException, ErrorCode, error_response, success_response
from app.core.logging import setup_logging, get_logger, request_id_var
from app.core.security import generate_request_id
from app.core.redis_client import redis_client
from app.core.rate_limit import rate_limit_middleware
from app.core import metrics as app_metrics
from app.db.base import AsyncSessionLocal


# 设置日志
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Code Case Platform API starting...", extra={
        "app_env": settings.app_env,
        "app_version": settings.app_version,
    })

    # 连接Redis
    await redis_client.connect()
    logger.info("Redis connected")

    yield

    # 关闭时执行
    await redis_client.disconnect()
    logger.info("Code Case Platform API shutting down...")


# 创建FastAPI应用
app = FastAPI(
    title="代码用例测试平台API",
    description="代码用例测试管理和执行平台",
    version=settings.app_version,
    docs_url=f"{settings.api_prefix}/docs",
    redoc_url=f"{settings.api_prefix}/redoc",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)


# Prometheus /metrics 端点（受 metrics_enabled 控制，豁免限流）
if settings.metrics_enabled:
    app.mount("/metrics", make_asgi_app())


# CORS中间件（WP-11：收敛方法/头白名单）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


# 速率限制中间件（WP-06 安全基线）
app.middleware("http")(rate_limit_middleware)


# 安全响应头集合（WP-11）。docs/redoc 路径放宽 CSP（Swagger UI 需内联脚本）。
_DOCS_PATHS = (
    f"{settings.api_prefix}/docs",
    f"{settings.api_prefix}/redoc",
    f"{settings.api_prefix}/openapi.json",
)


def _apply_security_headers(response, path: str) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if not any(path.startswith(p) for p in _DOCS_PATHS):
        response.headers["Content-Security-Policy"] = "default-src 'self'"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    """请求中间件：添加请求ID、记录日志、计时"""
    # 生成或获取请求ID
    request_id = request.headers.get("X-Request-ID") or generate_request_id()
    request_id_var.set(request_id)

    # 记录请求开始
    start_time = time.time()
    logger.info(
        f"{request.method} {request.url.path}",
        extra={
            "method": request.method,
            "path": request.url.path,
            "client_ip": request.client.host if request.client else None,
        }
    )

    # 处理请求
    path = request.url.path
    app_metrics.http_requests_in_progress.inc()
    try:
        response = await call_next(request)

        # 添加请求ID + 安全响应头
        response.headers["X-Request-ID"] = request_id
        _apply_security_headers(response, path)

        # 计算耗时
        duration = time.time() - start_time
        duration_ms = int(duration * 1000)

        # 记录 Prometheus 指标
        metric_path = app_metrics.normalize_path(request)
        app_metrics.http_requests_total.labels(
            method=request.method, path=metric_path, status=str(response.status_code)
        ).inc()
        app_metrics.http_request_duration_seconds.labels(
            method=request.method, path=metric_path
        ).observe(duration)

        # 记录响应
        logger.info(
            f"Response {response.status_code}",
            extra={
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        )

        return response

    except Exception as e:
        logger.exception("Unhandled exception during request processing")
        duration = time.time() - start_time

        metric_path = app_metrics.normalize_path(request)
        app_metrics.http_requests_total.labels(
            method=request.method, path=metric_path, status="500"
        ).inc()
        app_metrics.http_request_duration_seconds.labels(
            method=request.method, path=metric_path
        ).observe(duration)

        error_resp = JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response(
                code=ErrorCode.INTERNAL_ERROR,
                message="服务器内部错误",
                request_id=request_id
            )
        )
        error_resp.headers["X-Request-ID"] = request_id
        _apply_security_headers(error_resp, path)
        return error_resp
    finally:
        app_metrics.http_requests_in_progress.dec()


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """应用异常处理器"""
    request_id = request_id_var.get()

    logger.warning(
        f"AppException: {exc.message}",
        extra={
            "error_code": exc.code,
            "details": exc.details,
        }
    )

    return JSONResponse(
        status_code=exc.http_status,
        content=error_response(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=request_id
        )
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数验证异常处理器"""
    request_id = request_id_var.get()

    errors = []
    for error in exc.errors():
        errors.append({
            "field": ".".join(str(x) for x in error["loc"]),
            "message": error["msg"],
            "type": error["type"],
        })

    logger.warning("Validation error", extra={"errors": errors})

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response(
            code=ErrorCode.VALIDATION_ERROR,
            message="参数验证失败",
            details=errors,
            request_id=request_id
        )
    )


# 健康检查
@app.get("/health/live", tags=["健康检查"])
async def health_live():
    """存活检查"""
    return success_response(data={"status": "alive"})


@app.get("/health/ready", tags=["健康检查"])
async def health_ready():
    """就绪检查：检查 Redis 与数据库连接"""
    redis_ok = await redis_client.ping()

    db_ok = False
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        logger.error(f"Database readiness check failed: {e}")

    ready = redis_ok and db_ok
    return success_response(data={
        "status": "ready" if ready else "not_ready",
        "redis": "up" if redis_ok else "down",
        "database": "up" if db_ok else "down",
    })


# 根路径
@app.get("/", tags=["基础"])
async def root():
    """API根路径"""
    return success_response(data={
        "name": "Code Case Platform API",
        "version": settings.app_version,
        "environment": settings.app_env,
        "docs": f"{settings.api_prefix}/docs"
    })


# 注册路由
from app.api.v1 import (
    auth,
    code_case,
    environment,
    notifications,
    permissions,
    projects,
    report,
    test_plan,
)

app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(projects.router, prefix=settings.api_prefix)
app.include_router(environment.router, prefix=settings.api_prefix)
app.include_router(test_plan.router, prefix=settings.api_prefix)
app.include_router(report.router, prefix=settings.api_prefix)
app.include_router(code_case.router, prefix=settings.api_prefix)
app.include_router(permissions.router, prefix=settings.api_prefix)
app.include_router(notifications.router, prefix=settings.api_prefix)


# 挂载前端静态文件（生产环境）
# 优先使用配置项 FRONTEND_DIST_DIR；留空时回退到后端仓库同级的 frontend/dist
if settings.frontend_dist_dir:
    frontend_dist = Path(settings.frontend_dist_dir)
else:
    frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")

    # SPA 路由回退：所有非 API 路径返回 index.html
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """SPA 路由回退"""
        # API 路径已被路由处理，这里只处理前端路由
        if full_path.startswith("api/") or full_path.startswith("metrics"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        # 返回 index.html
        index_file = frontend_dist / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse(status_code=404, content={"detail": "Frontend not found"})
else:
    logger.warning(f"Frontend dist directory not found: {frontend_dist}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_config=None,  # 使用我们自己的日志配置
    )
