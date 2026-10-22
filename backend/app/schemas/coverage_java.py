"""JaCoCo 覆盖率采集 Pydantic Schemas

Phase 0 契约：前后端并行开发的类型对齐依据。
前端对应文件：frontend/src/types/coverage.ts
"""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ──────────────────────────────────────────────
# 枚举
# ──────────────────────────────────────────────

TASK_STATUS_VALUES = ["draft", "queued", "running", "completed", "failed", "cancelled"]
RUN_STATUS_VALUES = ["queued", "running", "completed", "failed", "cancelled", "partial"]
REPORT_STATUS_VALUES = ["queued", "running", "completed", "failed", "skipped", "cancelled"]
STAGE_VALUES = ["pending", "clone", "build", "test", "report", "done"]

TaskStatus = Literal["draft", "queued", "running", "completed", "failed", "cancelled"]
RunStatus = Literal["queued", "running", "completed", "failed", "cancelled", "partial"]
ReportStatus = Literal["queued", "running", "completed", "failed", "skipped", "cancelled"]
ProgressStage = Literal["pending", "clone", "build", "test", "report", "done"]
TriggerType = Literal["manual", "cron", "retry"]


# ──────────────────────────────────────────────
# 服务引用（monorepo 多服务场景）
# ──────────────────────────────────────────────

class ServiceRef(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="服务名称")
    module: Optional[str] = Field(None, description="Maven/Gradle 模块名（子模块坐标）")
    path: str = Field(..., min_length=1, description="相对仓库根的路径，如 services/order")
    agent_host: Optional[str] = Field(
        None, max_length=255,
        description="运行时模式：该服务 JaCoCo agent 地址，覆盖 runtime_config.host",
    )
    agent_port: Optional[int] = Field(None, ge=1, le=65535, description="运行时模式：该服务 agent 端口")


CollectionMode = Literal["unittest", "runtime"]


class RuntimeConfig(BaseModel):
    """运行时（tcpserver dump）模式配置"""
    host: Optional[str] = Field(None, max_length=255, description="默认 agent 地址（服务未单独配置时使用）")
    port: int = Field(6300, ge=1, le=65535, description="默认 agent 端口")
    reset: bool = Field(False, description="dump 后是否清空 agent 端计数（用于分段统计）")


def _validate_runtime(mode: Optional[str], cfg: Optional[RuntimeConfig], services: Optional[list[ServiceRef]]) -> None:
    if mode != "runtime" or services is None:
        return
    default_host = cfg.host if cfg else None
    missing = [s.name for s in services if not (s.agent_host or default_host)]
    if missing:
        raise ValueError(f"运行时模式需配置 agent 地址：runtime_config.host 或服务 agent_host（缺失: {', '.join(missing)}）")


# ──────────────────────────────────────────────
# 任务（CoverageTask）
# ──────────────────────────────────────────────

class CoverageTaskBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    repo_id: Optional[int] = Field(None, description="关联代码源 ID；设置后 repo_url 以代码源为准")
    repo_url: str = Field(..., min_length=1, max_length=500, description="Git 仓库 URL（HTTPS/SSH）")
    services: list[ServiceRef] = Field(..., min_length=1, max_length=20)
    branch: str = Field("main", max_length=100)
    diff_base_branch: Optional[str] = Field(
        None, max_length=100,
        description="增量 diff 基准分支，为空则用 project.default_main_branch"
    )
    requirement_ref: Optional[str] = Field(
        None, max_length=200,
        description="关联需求（预留字段，二期接第三方平台）"
    )
    cron_expr: Optional[str] = Field(
        None, max_length=100,
        description="定时采集 cron 表达式（MVP 仅存储不调度）"
    )
    threshold_line_rate: Optional[float] = Field(
        None, ge=0, le=100,
        description="行覆盖率告警阈值（MVP 仅存储不触发）"
    )
    threshold_branch_rate: Optional[float] = Field(
        None, ge=0, le=100,
        description="分支覆盖率告警阈值（MVP 仅存储不触发）"
    )
    collection_mode: CollectionMode = Field(
        "unittest", description="采集模式：unittest=跑单测 / runtime=从运行中应用 tcpserver dump"
    )
    runtime_config: Optional[RuntimeConfig] = Field(None, description="运行时模式配置")


class CoverageTaskCreate(CoverageTaskBase):
    # 选了代码源时 repo_url 由后端从代码源回填
    repo_url: Optional[str] = Field(None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def _check_runtime(self):
        if not self.repo_id and not self.repo_url:
            raise ValueError("请选择代码源或填写 Git 仓库地址")
        _validate_runtime(self.collection_mode, self.runtime_config, self.services)
        return self


class CoverageTaskUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    repo_id: Optional[int] = None
    repo_url: Optional[str] = Field(None, min_length=1, max_length=500)
    services: Optional[list[ServiceRef]] = Field(None, min_length=1, max_length=20)
    branch: Optional[str] = Field(None, max_length=100)
    diff_base_branch: Optional[str] = Field(None, max_length=100)
    requirement_ref: Optional[str] = Field(None, max_length=200)
    cron_expr: Optional[str] = Field(None, max_length=100)
    threshold_line_rate: Optional[float] = Field(None, ge=0, le=100)
    threshold_branch_rate: Optional[float] = Field(None, ge=0, le=100)
    collection_mode: Optional[CollectionMode] = None
    runtime_config: Optional[RuntimeConfig] = None


class CoverageTask(CoverageTaskBase):
    id: int
    project_id: int
    owner_id: int
    status: TaskStatus
    current_run_id: Optional[int] = None
    last_completed_at: Optional[datetime] = None
    last_failed_at: Optional[datetime] = None
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CoverageTaskPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CoverageTask]


# ──────────────────────────────────────────────
# 运行实例（JavaCoverageRun）
# ──────────────────────────────────────────────

class JavaCoverageRun(BaseModel):
    id: int
    task_id: int
    trigger_type: TriggerType
    overall_status: RunStatus
    services_total: int = 0
    services_completed: int = 0
    services_failed: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ──────────────────────────────────────────────
# 报告（JavaCoverageReport，一个服务一份）
# ──────────────────────────────────────────────

class JavaCoverageReport(BaseModel):
    id: int
    run_id: int
    task_id: int
    service_name: str
    commit_sha: Optional[str] = None
    status: ReportStatus
    progress: int = Field(0, ge=0, le=100)
    stage: ProgressStage = "pending"
    stage_detail: Optional[str] = None
    line_rate: Optional[float] = None
    branch_rate: Optional[float] = None
    lines_covered: Optional[int] = None
    lines_total: Optional[int] = None
    branches_covered: Optional[int] = None
    branches_total: Optional[int] = None
    xml_report_path: Optional[str] = None
    html_report_path: Optional[str] = None
    exec_file_path: Optional[str] = None
    build_log_path: Optional[str] = None
    source_snapshot_path: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TriggerResponse(BaseModel):
    """POST trigger 的响应：返回 run_id + 各服务占位 report"""
    run_id: int
    reports: list[JavaCoverageReport]


# ──────────────────────────────────────────────
# 文件行级覆盖（代码浏览页用）
# ──────────────────────────────────────────────

class LineCoverage(BaseModel):
    line_no: int
    covered_instructions: int = 0
    missed_instructions: int = 0
    covered_branches: int = 0
    missed_branches: int = 0
    status: Literal["covered", "missed", "partial", "unknown"] = "unknown"


class FileCoverageSummary(BaseModel):
    file_path: str
    package: Optional[str] = None
    class_name: Optional[str] = None
    lines_total: int = 0
    lines_covered: int = 0
    line_rate: float = 0.0


class FileContentWithCoverage(BaseModel):
    file_path: str
    source: str
    source_available: bool = True
    line_coverage: list[LineCoverage]


# ──────────────────────────────────────────────
# WebSocket 消息协议
# ──────────────────────────────────────────────

class WsSnapshotMessage(BaseModel):
    """连接建立后立即推：当前 run 全部 report 的状态快照"""
    type: Literal["snapshot"] = "snapshot"
    task_id: int
    run_id: int
    reports: list[JavaCoverageReport]


class WsProgressMessage(BaseModel):
    """实时进度（arq worker 在每个关键阶段广播）"""
    type: Literal["progress"] = "progress"
    report_id: int
    service_name: str
    progress: int = Field(..., ge=0, le=100)
    stage: ProgressStage
    stage_detail: Optional[str] = None


class WsServiceDoneMessage(BaseModel):
    """单服务完成（成功或失败都算 done，看 success）"""
    type: Literal["service_done"] = "service_done"
    report_id: int
    service_name: str
    success: bool
    progress: int = 100
    stage: Literal["done"] = "done"
    coverage: Optional[dict[str, Any]] = None


class WsServiceErrorMessage(BaseModel):
    """单服务失败（带错误信息 + build_log URL）"""
    type: Literal["service_error"] = "service_error"
    report_id: int
    service_name: str
    progress: int = 0
    stage: ProgressStage
    message: str
    build_log_url: Optional[str] = None


class WsTaskDoneMessage(BaseModel):
    """所有服务完成，run 结束"""
    type: Literal["task_done"] = "task_done"
    task_id: int
    run_id: int
    success: Optional[bool] = None  # True=全成功 / False=全失败 / None=部分成功
    partial: bool = False


# ──────────────────────────────────────────────
# 增量覆盖率相关
# ──────────────────────────────────────────────


class DiffCoverageChangedLine(BaseModel):
    """变更行的覆盖状态"""
    line_no: int
    status: Literal["covered", "partial", "missed", "not_executable"]


class DiffCoverageFile(BaseModel):
    """单文件的增量覆盖率"""
    changed_lines_total: int
    changed_lines_covered: int
    line_rate: float
    changed_lines: list[DiffCoverageChangedLine]


class DiffCoverageResponse(BaseModel):
    """增量覆盖率汇总"""
    base_branch: str = Field(..., description="对比基准分支")
    merge_base: str = Field(..., description="merge-base commit SHA")
    head_commit: Optional[str] = Field(None, description="采集时的 commit SHA")
    line_rate: float = Field(..., description="增量行覆盖率 0-100")
    lines_total: int = Field(..., description="变更的可执行行总数")
    lines_covered: int = Field(..., description="变更可执行行中已覆盖数")
    files: dict[str, DiffCoverageFile] = Field(default_factory=dict, description="按文件的增量覆盖")
