"""
Apollo 配置中心客户端（轻量实现，基于 httpx，无第三方 apollo 依赖）。

设计目标
========
- 在应用启动、`Settings()` 实例化之前，从 Apollo 拉取业务配置并注入 `os.environ`，
  这样 pydantic-settings 照旧读取环境变量，业务代码与配置 key 完全不变。
- Apollo 的连接信息由部署平台（Zadig / K8s）通过环境变量注入：
    APOLLO_URL   Apollo 配置服务地址（config service / meta server），必填才启用
    APP_NAME     作为 Apollo AppId（默认回退到该值）
    DEPLOY_ENV   作为 Apollo cluster（默认回退到该值）
  可选覆盖：
    APOLLO_APP_ID     显式指定 AppId（优先于 APP_NAME）
    APOLLO_CLUSTER    显式指定 cluster（优先于 DEPLOY_ENV，最终默认 "default"）
    APOLLO_NAMESPACE  命名空间，逗号分隔可多个，默认 "application"
    APOLLO_SECRET     命名空间访问密钥（开启访问密钥校验时需要）
    APOLLO_TIMEOUT    单次请求超时秒数，默认 5

行为约定
========
- 未设置 APOLLO_URL 时直接跳过（本地开发继续用 .env），不报错。
- Apollo 拉取失败（网络/超时/命名空间不存在）时打印告警并跳过该命名空间，
  绝不阻塞应用启动，退回到 .env / 已有环境变量。
- Apollo 返回的 key 直接写入 os.environ（同名覆盖），pydantic-settings 大小写不敏感，
  因此 Apollo 里保持与 .env 一致的 KEY 命名即可（如 DATABASE_URL / REDIS_URL）。
- 多命名空间按顺序拉取，后者覆盖前者的同名 key。

环境名称映射
============
- K8s/Zadig 的部署环境名称（DEPLOY_ENV）可能与 Apollo cluster 名称不一致
- 代码会自动映射常见的部署环境到 Apollo cluster：
    dev01, dev02, dev03 → DEV
    test01, test02 → TEST
    prod01, prod02, prod → PRO
- 如果 APOLLO_CLUSTER 显式指定，则不进行映射，直接使用指定值
"""
from __future__ import annotations

import hashlib
import hmac
import base64
import os
import time
from urllib.parse import quote

# httpx 已是项目依赖
import httpx


# 部署环境到 Apollo Cluster 的映射表
# K8s/Zadig 的部署环境名称 → Apollo 配置中心的 cluster 名称
DEPLOY_ENV_TO_CLUSTER_MAP = {
    # 开发环境
    "dev01": "DEV",
    "dev02": "DEV",
    "dev03": "DEV",
    "dev": "DEV",
    # 测试环境
    "test01": "TEST",
    "test02": "TEST",
    "test": "TEST",
    # 预发布环境
    "staging": "TEST",
    "uat": "TEST",
    # 生产环境
    "prod01": "PRO",
    "prod02": "PRO",
    "prod": "PRO",
    "production": "PRO",
}


def _map_cluster_name(raw_cluster: str) -> str:
    """
    将部署环境名称映射到 Apollo cluster 名称。

    映射规则：
    - 如果在映射表中找到，返回映射后的值（如 dev01 → DEV）
    - 否则返回原值（支持自定义 cluster 名称）
    - 映射匹配不区分大小写

    Args:
        raw_cluster: 原始的 cluster 名称（来自 DEPLOY_ENV 或 APOLLO_CLUSTER）

    Returns:
        映射后的 Apollo cluster 名称
    """
    # 先尝试精确匹配（区分大小写）
    if raw_cluster in DEPLOY_ENV_TO_CLUSTER_MAP:
        return DEPLOY_ENV_TO_CLUSTER_MAP[raw_cluster]

    # 再尝试不区分大小写匹配
    raw_lower = raw_cluster.lower()
    for key, value in DEPLOY_ENV_TO_CLUSTER_MAP.items():
        if key.lower() == raw_lower:
            return value

    # 没有匹配规则，返回原值
    return raw_cluster


def _sign(timestamp: str, path_with_query: str, secret: str) -> str:
    """Apollo 访问密钥签名（HMAC-SHA1 + Base64）。"""
    string_to_sign = f"{timestamp}\n{path_with_query}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _auth_headers(app_id: str, secret: str, path_with_query: str) -> dict[str, str]:
    """构造带访问密钥签名的请求头（未配置 secret 时返回空）。"""
    if not secret:
        return {}
    timestamp = str(int(round(time.time() * 1000)))
    return {
        "Authorization": f"Apollo {app_id}:{_sign(timestamp, path_with_query, secret)}",
        "Timestamp": timestamp,
    }


def _fetch_namespace(
    base_url: str,
    app_id: str,
    cluster: str,
    namespace: str,
    secret: str,
    timeout: float,
) -> dict[str, str]:
    """
    通过「不带缓存」接口拉取单个命名空间的全部配置。
    接口: GET /configs/{appId}/{cluster}/{namespace}
    返回 configurations 字典（key -> value，均为字符串）。
    """
    path = (
        f"/configs/{quote(app_id, safe='')}"
        f"/{quote(cluster, safe='')}"
        f"/{quote(namespace, safe='')}"
    )
    url = f"{base_url}{path}"
    headers = _auth_headers(app_id, secret, path)

    resp = httpx.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    configs = data.get("configurations") or {}
    if not isinstance(configs, dict):
        return {}
    # 统一转字符串（环境变量只接受字符串）
    return {str(k): str(v) for k, v in configs.items()}


def load_apollo_config() -> dict[str, str]:
    """
    从 Apollo 拉取配置并注入 os.environ。

    返回实际注入（覆盖/新增）的 key->value 字典，便于日志与自检。
    未启用 Apollo（无 APOLLO_URL）时返回空字典。
    """
    base_url = (os.getenv("APOLLO_URL") or "").strip().rstrip("/")
    if not base_url:
        print("[apollo] APOLLO_URL 未设置，跳过 Apollo，使用 .env / 现有环境变量")
        return {}

    app_id = (os.getenv("APOLLO_APP_ID") or os.getenv("APP_NAME") or "qauto").strip()

    # 获取原始 cluster 名称
    raw_cluster = (
        os.getenv("APOLLO_CLUSTER") or os.getenv("DEPLOY_ENV") or "default"
    ).strip()

    # 映射到 Apollo cluster 名称
    cluster = _map_cluster_name(raw_cluster)

    # 如果进行了映射，记录日志
    if cluster != raw_cluster:
        print(f"[apollo] 环境映射: {raw_cluster} → {cluster}")

    namespaces = [
        ns.strip()
        for ns in (os.getenv("APOLLO_NAMESPACE") or "application").split(",")
        if ns.strip()
    ]
    secret = (os.getenv("APOLLO_SECRET") or "").strip()
    try:
        timeout = float(os.getenv("APOLLO_TIMEOUT") or "5")
    except ValueError:
        timeout = 5.0

    print(
        f"[apollo] loading url={base_url} app_id={app_id} "
        f"cluster={cluster} namespaces={namespaces}"
    )

    injected: dict[str, str] = {}
    failed_namespaces = []
    for namespace in namespaces:
        try:
            configs = _fetch_namespace(
                base_url, app_id, cluster, namespace, secret, timeout
            )
        except Exception as exc:  # noqa: BLE001 - 启动期容错，绝不阻塞
            print(
                f"[apollo] WARN 命名空间 '{namespace}' 拉取失败，已跳过: "
                f"{type(exc).__name__}: {exc}"
            )
            failed_namespaces.append(namespace)
            continue

        for key, value in configs.items():
            os.environ[key] = value
            injected[key] = value
        print(f"[apollo] namespace '{namespace}' 注入 {len(configs)} 个 key")

    if injected:
        # 只打印 key 名，避免泄露密钥类明文
        print(f"[apollo] 共注入 {len(injected)} 个 key: {sorted(injected.keys())}")

    # 如果 Apollo 已启用但所有命名空间都失败了，记录严重警告
    if not injected and failed_namespaces:
        print(
            f"[apollo] ERROR: APOLLO_URL 已设置但所有命名空间均拉取失败！"
            f"应用将使用默认配置，生产环境可能无法正常工作。"
            f"失败的命名空间: {failed_namespaces}"
        )

    return injected
