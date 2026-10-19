"""
环境管理相关的Schema定义
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime


# ============ 环境 Environment ============

class EnvironmentBase(BaseModel):
    """环境基础信息"""
    name: str = Field(..., description="环境名称（如 dev、test、prod）")
    display_name: str = Field(..., description="环境显示名称")
    description: Optional[str] = Field(None, description="环境描述")
    base_url: Optional[str] = Field(None, description="环境基础URL")
    sort_order: int = Field(0, description="排序权重")
    is_active: bool = Field(True, description="是否启用")
    grafana_target_json: Optional[dict] = Field(
        None,
        description='Grafana监控目标配置: {"namespace": "crm-pre", "pod_pattern": "crm-backend-.*", "dashboard_uid": "2dfs3v8nz"}'
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """验证环境名称格式"""
        if not v or not v.strip():
            raise ValueError("环境名称不能为空")
        # 只允许字母、数字、下划线、连字符
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("环境名称只能包含字母、数字、下划线和连字符")
        return v.strip()


class EnvironmentCreate(EnvironmentBase):
    """创建环境"""
    pass


class EnvironmentUpdate(BaseModel):
    """更新环境"""
    display_name: Optional[str] = None
    description: Optional[str] = None
    base_url: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    grafana_target_json: Optional[dict] = None


class EnvironmentInfo(EnvironmentBase):
    """环境信息"""
    id: int
    project_id: int
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============ 变量 Variable ============

class VariableBase(BaseModel):
    """变量基础信息"""
    key: str = Field(..., description="变量键名")
    value: Optional[str] = Field(None, description="变量值")
    description: Optional[str] = Field(None, description="变量描述")
    is_secret: bool = Field(False, description="是否为密钥变量")
    is_active: bool = Field(True, description="是否启用")

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        """验证变量键名格式"""
        if not v or not v.strip():
            raise ValueError("变量键名不能为空")
        # 只允许字母、数字、下划线
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', v):
            raise ValueError("变量键名必须以字母或下划线开头，只能包含字母、数字和下划线")
        return v.strip()


class VariableCreate(VariableBase):
    """创建变量"""
    scope: str = Field(..., description="作用域: global/environment")
    environment_id: Optional[int] = Field(None, description="环境ID（scope=environment时必填）")


class VariableUpdate(BaseModel):
    """更新变量"""
    value: Optional[str] = None
    description: Optional[str] = None
    is_secret: Optional[bool] = None
    is_active: Optional[bool] = None


class VariableInfo(VariableBase):
    """变量信息"""
    id: int
    project_id: int
    environment_id: Optional[int] = None
    scope: str
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VariableInfoMasked(BaseModel):
    """变量信息（脱敏）- 用于前端显示"""
    id: int
    project_id: int
    environment_id: Optional[int] = None
    scope: str
    key: str
    value: Optional[str] = Field(None, description="密钥变量已脱敏")
    description: Optional[str] = None
    is_secret: bool
    is_active: bool
    created_by: Optional[int] = None
    updated_by: Optional[int] = None
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_variable(cls, var: VariableInfo) -> "VariableInfoMasked":
        """从VariableInfo创建脱敏版本"""
        data = var.model_dump()
        # 如果是密钥变量，脱敏value
        if var.is_secret and var.value:
            data["value"] = "******"
        return cls(**data)

    class Config:
        from_attributes = True


# ============ 批量操作 ============

class VariableBatchCreate(BaseModel):
    """批量创建变量"""
    variables: List[VariableCreate] = Field(..., description="变量列表")


class VariableBatchUpdate(BaseModel):
    """批量更新变量"""
    updates: List[dict] = Field(..., description="更新列表，每项包含id和要更新的字段")
