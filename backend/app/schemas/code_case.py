"""
代码用例 Pydantic Schemas
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

LEVEL_VALUES = ["P0", "P1", "P2", "P3"]
STATUS_VALUES = ["idle", "running", "passed", "failed"]


# ──────────────────────────────────────────────
# 用例模块
# ──────────────────────────────────────────────

class CodeModuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="模块名称")
    parent_id: Optional[int] = Field(None, description="父模块ID，不传为根级")
    sort_order: int = 0


class CodeModuleUpdate(BaseModel):
    """仅支持改名和排序：层级由扫描的 module 参数决定，不允许手工移动"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    sort_order: Optional[int] = None


class CodeModuleInfo(BaseModel):
    id: int
    parent_id: Optional[int]
    name: str
    level: int
    full_path: str
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CodeModuleTreeNode(BaseModel):
    id: int
    parent_id: Optional[int]
    name: str
    level: int
    full_path: str
    sort_order: int
    case_count: int = Field(0, description="本模块直属用例数")
    total_case_count: int = Field(0, description="含子模块的用例总数")
    children: list["CodeModuleTreeNode"] = []


# ──────────────────────────────────────────────
# 用例
# ──────────────────────────────────────────────

class CodeCaseListItem(BaseModel):
    id: int
    module_id: Optional[int]
    module: str = Field(..., description='模块层级，如 "支付中心-支付渠道-支付宝"')
    module_path: list[str] = Field(default_factory=list, description="模块层级数组")
    name: str
    level: str
    description: Optional[str] = None
    file_path: str
    function_name: str
    line_number: Optional[int] = None
    status: str
    last_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # 最近一次执行的结果（无执行记录时为空）
    last_execution_id: Optional[int] = None
    last_duration_ms: Optional[int] = None
    last_message: Optional[str] = None

    model_config = {"from_attributes": True}


class CodeCaseDetail(CodeCaseListItem):
    code_snippet: Optional[str] = None


class CodeCasePage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CodeCaseListItem]


class CodeCaseStats(BaseModel):
    total: int = Field(0, description="用例总数")
    module_count: int = Field(0, description="涉及模块数")
    by_level: dict[str, int] = Field(default_factory=dict, description="按等级统计")
    by_status: dict[str, int] = Field(default_factory=dict, description="按状态统计")


# ──────────────────────────────────────────────
# 扫描
# ──────────────────────────────────────────────

class ScanResult(BaseModel):
    scanned_files: int = Field(0, description="扫描的文件数")
    scanned_cases: int = Field(0, description="扫描到的用例数")
    created: int = Field(0, description="新增用例数")
    updated: int = Field(0, description="更新用例数")
    restored: int = Field(0, description="恢复的用例数（文件重新出现）")
    deleted: int = Field(0, description="标记删除的用例数（文件已消失）")
    modules_created: int = Field(0, description="自动新增的模块数")
    skipped: int = Field(0, description="按项目扫描时跳过的其他项目/全局用例数")
    project_id: Optional[int] = Field(None, description="本次扫描限定的项目；为空表示全量扫描")
    errors: list[str] = Field(default_factory=list, description="解析错误")


# ──────────────────────────────────────────────
# 执行
# ──────────────────────────────────────────────

EXEC_STATUS_VALUES = ["pending", "running", "passed", "failed", "error", "timeout"]


class ExecuteRequest(BaseModel):
    """
    发起执行：三种方式取其一
      case_ids   指定用例（单个或多个）
      module_id  执行某模块下全部用例（含子模块）
      all_cases  执行全部用例
    """
    case_ids: Optional[list[int]] = Field(None, description="指定用例ID列表")
    module_id: Optional[int] = Field(None, description="按模块执行（含子模块）")
    all_cases: bool = Field(False, description="执行全部用例")
    timeout: int = Field(60, ge=1, le=600, description="单用例超时（秒）")


class ExecutionInfo(BaseModel):
    id: int
    batch_id: str
    case_id: int
    case_name: str
    module: Optional[str] = None
    level: Optional[str] = None
    file_path: Optional[str] = None
    function_name: Optional[str] = None
    status: str
    message: Optional[str] = None
    duration_ms: Optional[int] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    trigger_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ExecutionDetail(ExecutionInfo):
    """详情：附带完整日志和堆栈"""
    logs: Optional[str] = None
    traceback: Optional[str] = None


class BatchSummary(BaseModel):
    batch_id: str
    total: int = 0
    pending: int = 0
    running: int = 0
    passed: int = 0
    failed: int = 0
    error: int = 0
    timeout: int = 0
    finished: bool = Field(False, description="批次是否已全部结束")
    pass_rate: float = Field(0.0, description="通过率(%)，按已结束的用例算")
    duration_ms: int = Field(0, description="批次总耗时")


class BatchResult(BaseModel):
    """执行结果预览：汇总 + 明细"""
    summary: BatchSummary
    items: list[ExecutionInfo] = []


class ExecutionPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ExecutionInfo]


CodeModuleTreeNode.model_rebuild()
