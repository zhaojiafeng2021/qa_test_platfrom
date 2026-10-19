"""
认证相关的Pydantic模型
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field
from typing import Optional


# 登录相关
class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")


class LoginResponse(BaseModel):
    """登录响应"""
    access_token: str = Field(..., description="访问令牌")
    refresh_token: str = Field(..., description="刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    user: "UserInfo"


class RefreshTokenRequest(BaseModel):
    """刷新令牌请求"""
    refresh_token: str = Field(..., description="刷新令牌")


class RefreshTokenResponse(BaseModel):
    """刷新令牌响应"""
    access_token: str = Field(..., description="新的访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")


# 注册相关
class RegisterRequest(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    full_name: Optional[str] = Field(None, max_length=100, description="全名")


class RegisterResponse(BaseModel):
    """注册响应"""
    user: "UserInfo"


# 用户信息
class UserInfo(BaseModel):
    """用户信息"""
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: str
    is_superuser: bool

    class Config:
        from_attributes = True


class CurrentUser(BaseModel):
    """当前用户（包含权限信息）"""
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    status: str
    is_superuser: bool
    permissions: list[str] = Field(default_factory=list, description="权限列表")

    class Config:
        from_attributes = True


# 个人访问令牌（PAT）相关
class ApiTokenCreateRequest(BaseModel):
    """创建 PAT 请求"""
    name: str = Field(..., min_length=1, max_length=100, description="令牌名称/用途标识")
    expires_in_days: Optional[int] = Field(
        None, gt=0, le=3650, description="有效天数，不传或 null 表示永不过期"
    )


class ApiTokenCreateResponse(BaseModel):
    """创建 PAT 响应（明文 token 仅此一次返回）"""
    id: int
    name: str
    token: str = Field(..., description="令牌明文，仅创建时返回一次，请妥善保存")
    token_prefix: str
    expires_at: Optional[datetime] = None
    created_at: datetime


class ApiTokenInfo(BaseModel):
    """PAT 信息（不含明文）"""
    id: int
    name: str
    token_prefix: str
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# 飞书登录相关
class FeishuAuthUrlResponse(BaseModel):
    """飞书授权地址响应"""
    authorization_url: str = Field(..., description="飞书授权地址")
    state: str = Field(..., description="状态参数")


class FeishuCallbackRequest(BaseModel):
    """飞书回调请求"""
    code: str = Field(..., description="授权码")
    state: str = Field(..., description="状态参数")
