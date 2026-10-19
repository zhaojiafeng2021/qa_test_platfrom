"""
应用配置模块
使用 pydantic-settings 管理配置
"""
from typing import List
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 在 Settings 实例化之前，先从 Apollo 拉取配置注入 os.environ。
# 未设置 APOLLO_URL 时该调用为 no-op，本地开发继续用 .env。
from app.core.apollo import load_apollo_config

load_apollo_config()


# Dev-only default secrets. Production startup must reject these (see production guard).
_DEV_JWT_SECRET = "dev-secret-key-change-in-production"
_DEV_ENCRYPTION_KEY = "dev-encryption-key-32-bytes-minimum"


class Settings(BaseSettings):
    """应用配置类"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # 应用配置
    app_env: str = Field(default="local", description="环境: local/dev/test/staging/prod")
    app_name: str = Field(default="qa-platform", description="应用名称")
    app_version: str = Field(default="0.1.0", description="应用版本")
    api_prefix: str = Field(default="/api/v1", description="API路径前缀")
    api_base_url: str = Field(default="http://localhost:8000", description="API基础URL（用于生成webhook URL等）")
    debug: bool = Field(default=False, description="调试模式")

    # 数据库配置
    database_url: str = Field(
        default="mysql+asyncmy://root:root@localhost:3306/code_case_platform",
        description="数据库连接URL"
    )
    # 数据库 SSL 配置（生产库强制 SSL 时使用；本地留空即用 asyncpg 默认 prefer，不受影响）
    # 取值: 空("")=默认 prefer / disable / allow / prefer / require / verify-ca / verify-full
    db_ssl_mode: str = Field(default="", description="asyncpg SSL 模式，空则用默认(prefer)")
    db_ssl_root_cert: str = Field(
        default="",
        description="CA 根证书路径（verify-ca/verify-full 校验服务端证书时需要）"
    )

    # Redis配置
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis连接URL(缓存/pub-sub)")
    arq_redis_url: str = Field(default="redis://localhost:6379/1", description="arq任务队列Redis URL")

    # MinIO配置
    minio_endpoint: str = Field(default="localhost:9000", description="MinIO端点")
    minio_access_key: str = Field(default="minioadmin", description="MinIO访问密钥")
    minio_secret_key: str = Field(default="minioadmin", description="MinIO密钥")
    minio_bucket: str = Field(default="qa-platform", description="MinIO存储桶")
    minio_secure: bool = Field(default=False, description="是否使用HTTPS")

    # JWT配置
    jwt_secret_key: str = Field(
        default=_DEV_JWT_SECRET,
        description="JWT签名密钥"
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT算法")
    jwt_access_token_expire_minutes: int = Field(default=10080, description="访问令牌过期时间(分钟)，默认7天")
    jwt_refresh_token_expire_days: int = Field(default=14, description="刷新令牌过期时间(天)")

    # 加密配置
    encryption_key: str = Field(
        default=_DEV_ENCRYPTION_KEY,
        description="数据加密密钥"
    )

    # 飞书配置
    feishu_app_id: str = Field(default="", description="飞书应用ID")
    feishu_app_secret: str = Field(default="", description="飞书应用密钥")
    feishu_redirect_uri: str = Field(default="", description="飞书回调地址")
    feishu_webhook_url: str = Field(
        default="",
        description="飞书群机器人 Webhook URL（告警渠道未单独配置 webhook 时的默认地址）"
    )

    # DeepSeek AI 配置
    deepseek_api_key: str = Field(default="", description="DeepSeek API Key（用于性能测试 AI 建议）")

    # CORS配置
    allowed_origins: List[str] = Field(
        default=["http://localhost:5173"],
        description="允许的跨域来源"
    )

    # 速率限制配置（WP-11 安全基线）
    rate_limit_enabled: bool = Field(default=True, description="是否启用速率限制")
    rate_limit_per_minute: int = Field(default=120, description="常规接口每分钟每 IP 请求上限")
    rate_limit_login_per_minute: int = Field(default=10, description="登录接口每分钟每 IP 请求上限（防爆破）")

    # 文件上传限制（WP-11 安全基线）
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, description="上传文件最大字节数（默认 5MB）")

    # 数据保留/清理配置
    cleanup_enabled: bool = Field(default=True, description="是否启用定时数据清理任务")
    report_retention_days: int = Field(default=90, description="报告文件保留天数（超期清理）")
    cleanup_batch_size: int = Field(default=500, description="单次清理分批删除大小")
    cleanup_protected_run_ids: List[int] = Field(
        default_factory=lambda: [5, 6, 7, 8, 9, 14],
        description="受保护的 PlanRun ID 白名单（绝不清理，如验收数据）",
    )
    cleanup_dry_run: bool = Field(
        default=False, description="清理任务只扫描不实删（预演模式，记录将删数量）"
    )

    # 执行引擎配置
    execution_max_step_seconds: int = Field(default=120, description="单步骤最大执行时间(秒)")
    execution_max_response_bytes: int = Field(default=10485760, description="最大响应大小(字节)")
    execution_default_timeout_ms: int = Field(default=30000, description="默认超时时间(毫秒)")
    sse_keepalive_seconds: int = Field(default=15, description="SSE 心跳保活间隔(秒)")

    # SSRF 防护配置（WP-06 阶段C）
    ssrf_enabled: bool = Field(default=True, description="是否启用 SSRF 防护")
    ssrf_allow_private: bool = Field(default=False, description="是否允许私网地址（生产必须 False）")
    ssrf_allowed_hosts: list[str] = Field(default_factory=list, description="SSRF 白名单 host:port")
    ssrf_max_redirects: int = Field(default=5, description="最大重定向次数")

    # 循环控制配置（WP-06 阶段C）
    max_loop_iterations: int = Field(default=100, description="FOR/WHILE 默认最大迭代数")
    max_loop_depth: int = Field(default=5, description="嵌套循环最大深度")

    # 编排扩展节点配置（方向3：parallel/database/poll）
    max_parallel_branches: int = Field(default=10, description="Parallel 节点最大并行分支数")
    poll_max_timeout_ms: int = Field(default=300000, description="Poll 节点最大超时(毫秒)，硬上限")
    poll_max_attempts: int = Field(default=300, description="Poll 节点最大尝试次数硬上限")
    database_node_enabled: bool = Field(default=True, description="是否允许 Database 节点执行 SQL")
    database_node_max_rows: int = Field(default=1000, description="Database 查询返回最大行数")

    # 脚本节点配置（方向3：script 节点，执行 JavaScript / Python）
    # 安全提示：脚本以 worker 进程权限执行用户自定义代码（无 OS 级沙箱），
    # 语义等同于 Postman/JMeter 的脚本能力。生产可通过 script_node_enabled=False 关闭。
    script_node_enabled: bool = Field(default=True, description="是否允许 Script 节点执行 JS/Python")
    script_node_timeout_ms: int = Field(default=30000, description="Script 节点执行超时(毫秒)，硬上限")
    script_node_python_bin: str = Field(default="", description="Python 解释器路径（空则用当前 sys.executable）")
    script_node_node_bin: str = Field(default="node", description="Node.js 可执行文件路径")
    script_node_max_output_bytes: int = Field(default=1048576, description="脚本 stdout 最大字节数(默认1MB)")

    # 调度器配置
    scheduler_scan_interval_seconds: int = Field(default=10, description="调度器扫描间隔(秒)")
    scheduler_lock_expire_seconds: int = Field(default=30, description="调度器锁过期时间(秒)")
    scheduler_misfire_grace_seconds: int = Field(default=300, description="调度器漏触发补偿窗口(秒)")

    # 前端静态资源
    frontend_dist_dir: str = Field(
        default="",
        description="前端构建产物(dist)目录。留空则回退到后端仓库同级的 frontend/dist"
    )

    # 代码用例扫描路径
    code_testcases_dir: str = Field(
        default="",
        description="代码用例(code_testcases)扫描根目录。留空则回退到后端仓库根目录下的 code_testcases"
    )

    # 日志配置
    log_level: str = Field(default="INFO", description="日志级别")
    log_format: str = Field(default="json", description="日志格式: json/text")

    # 代码用例远程 Git 仓库同步（方案 A：扫描入口 Pull）
    code_repo_enabled: bool = Field(default=True, description="是否启用远程 Git 仓库同步")
    code_repo_url: str = Field(default="https://git.tec-do.com/qa/bic_code_testcase.git", description="代码用例仓库 HTTPS 地址")
    code_repo_token: str = Field(default="", description="GitLab Personal Access Token")
    code_repo_branch: str = Field(default="main", description="同步分支")
    code_repo_throttle_seconds: int = Field(default=60, description="pull 节流间隔（秒）")

    # 凭证数据库（credential_helper 用）
    cred_db_type: str = Field(default="postgresql", description="凭证库类型: postgresql / mysql")
    cred_db_host: str = Field(default="localhost", description="凭证库主机")
    cred_db_port: int = Field(default=5432, description="凭证库端口")
    cred_db_user: str = Field(default="postgres", description="凭证库用户名")
    cred_db_password: str = Field(default="", description="凭证库密码")
    cred_db_database: str = Field(default="qauto", description="凭证库名")


    # Prometheus配置
    metrics_enabled: bool = Field(default=True, description="是否启用指标")
    metrics_port: int = Field(default=9090, description="指标端口")

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v):
        """解析CORS允许的来源"""
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [v]
        return v

    @model_validator(mode="after")
    def _guard_production_secrets(self):
        """生产环境守卫：拒绝使用内置 dev 默认密钥（WP-11 安全基线）。"""
        if self.app_env == "prod":
            insecure = []
            if self.jwt_secret_key == _DEV_JWT_SECRET:
                insecure.append("JWT_SECRET_KEY")
            if self.encryption_key == _DEV_ENCRYPTION_KEY:
                insecure.append("ENCRYPTION_KEY")
            if insecure:
                raise ValueError(
                    "Production environment refuses default dev secrets: "
                    + ", ".join(insecure)
                    + ". Set strong values via environment variables."
                )

            # 生产环境不允许使用默认的 localhost 数据库配置
            if "localhost" in self.database_url or "127.0.0.1" in self.database_url:
                raise ValueError(
                    "Production environment refuses localhost database URL. "
                    "DATABASE_URL must be set via environment variables or Apollo. "
                    f"Current value: {self.database_url[:50]}..."
                )
        return self

    @property
    def is_production(self) -> bool:
        """是否为生产环境"""
        return self.app_env == "prod"

    @property
    def is_development(self) -> bool:
        """是否为开发环境"""
        return self.app_env in ("local", "dev")


# 全局配置实例
settings = Settings()
