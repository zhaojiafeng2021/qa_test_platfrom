"""
项目相关的Pydantic模型
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ============ 项目 ============
class ProjectCreateRequest(BaseModel):
    """创建项目请求"""
    code: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-zA-Z][a-zA-Z0-9_-]*$", description="项目代码（唯一标识，字母开头）")
    name: str = Field(..., min_length=1, max_length=100, description="项目名称")
    description: Optional[str] = Field(None, description="项目描述")
    icon: Optional[str] = Field(None, max_length=100, description="项目图标")
    color: Optional[str] = Field(None, max_length=20, description="项目颜色")


class ProjectUpdateRequest(BaseModel):
    """更新项目请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="项目名称")
    description: Optional[str] = Field(None, description="项目描述")
    icon: Optional[str] = Field(None, max_length=100, description="项目图标")
    color: Optional[str] = Field(None, max_length=20, description="项目颜色")
    is_public: Optional[bool] = Field(None, description="是否公开项目（所有用户可见）")
    grafana_config_json: Optional[dict] = Field(None, description="Grafana监控配置")


class ProjectInfo(BaseModel):
    """项目信息"""
    id: int
    code: str
    name: str
    description: Optional[str] = None
    owner_id: int
    status: str
    icon: Optional[str] = None
    color: Optional[str] = None
    is_public: bool = False
    grafana_config_json: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectDetail(ProjectInfo):
    """项目详情（含当前用户角色）"""
    my_role: Optional[str] = Field(None, description="当前用户在项目中的角色")
    member_count: int = Field(0, description="成员数量")


class ProjectListResponse(BaseModel):
    """项目列表响应"""
    items: list[ProjectInfo]
    total: int
    page: int
    page_size: int


# ============ 项目成员 ============
class MemberAddRequest(BaseModel):
    """添加成员请求"""
    user_id: int = Field(..., description="用户ID")
    role: str = Field("member", description="项目角色: owner/admin/member/viewer")


class MemberUpdateRequest(BaseModel):
    """更新成员角色请求"""
    role: str = Field(..., description="项目角色: owner/admin/member/viewer")


class MemberInfo(BaseModel):
    """成员信息"""
    id: int
    project_id: int
    user_id: int
    role: str
    invited_by: Optional[int] = None
    created_at: datetime
    # 关联的用户信息
    username: Optional[str] = None
    email: Optional[str] = None
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    # 虚拟成员标识（公开项目的访客）
    is_virtual: bool = False

    class Config:
        from_attributes = True


class MemberListResponse(BaseModel):
    """成员列表响应"""
    items: list[MemberInfo]
    total: int

# ============ Dashboard ============
class RecentExecutionInfo(BaseModel):
    id: int
    case_id: int
    case_name: str
    module: Optional[str] = None
    level: Optional[str] = None
    status: str
    duration_ms: Optional[int] = None
    created_at: datetime


class RecentPlanRunInfo(BaseModel):
    id: int
    plan_id: int
    status: str
    total_items: int = 0
    passed_items: int = 0
    failed_items: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ProjectSummary(BaseModel):
    code_case_count: int = 0
    code_case_weekly_added: int = 0
    test_plan_count: int = 0
    environment_count: int = 0
    execution_count: int = 0
    completed_execution_count: int = 0
    passed_execution_count: int = 0
    recent_pass_rate: float = 0
    recent_executions: list[RecentExecutionInfo] = Field(default_factory=list)
    recent_plan_runs: list[RecentPlanRunInfo] = Field(default_factory=list)