"""Prometheus 指标（WP-11 可观测性）。

使用已有依赖 prometheus-client，无需新增库。指标在请求中间件中记录，
/metrics 端点由 make_asgi_app 暴露（在 main.py 挂载）。

为避免高基数标签，path 使用路由模板（如 /projects/{project_id}），
无法归一时降级为原始路径前两段。
"""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

http_requests_total = Counter(
    "http_requests_total",
    "HTTP 请求总数",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "正在处理中的 HTTP 请求数",
)


def normalize_path(request) -> str:
    """将请求归一为低基数的路由模板，避免 path 标签爆炸。

    优先使用匹配到的路由模板（request.scope['route'].path）；
    匹配不到（404 等）时降级为原始路径前两段。
    """
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if template:
        return template
    raw = request.url.path
    segments = [s for s in raw.split("/") if s]
    if not segments:
        return "/"
    return "/" + "/".join(segments[:2])
