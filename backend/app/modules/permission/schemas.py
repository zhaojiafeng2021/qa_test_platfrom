"""Pydantic contracts for RBAC v2 APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PermissionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    module: str
    action: str
    description: str | None = None
    platform_only: bool
    sort_order: int


class RoleInfo(BaseModel):
    id: int
    project_id: int | None
    code: str
    name: str
    description: str | None
    scope: str
    is_builtin: bool
    parent_role_id: int | None
    parent_role_name: str | None = None
    direct_permission_codes: list[str]
    permission_codes: list[str]
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    code: str | None = Field(
        default=None,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    description: str | None = Field(default=None, max_length=500)
    parent_role_id: int | None = None
    permission_codes: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    parent_role_id: int | None = None
    permission_codes: list[str] | None = None


class DataPolicyInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    resource_type: str
    visibility_scope: str
    member_ids: list[int]
    updated_by: int | None
    updated_at: datetime


class DataPolicyUpdate(BaseModel):
    visibility_scope: Literal["all", "owner", "members"]
    member_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_members(self):
        if self.visibility_scope == "members" and not self.member_ids:
            raise ValueError("指定成员范围至少需要选择一名成员")
        if self.visibility_scope != "members":
            self.member_ids = []
        return self


class PermissionMemberAdd(BaseModel):
    user_id: int
    role_id: int


class PermissionMemberUpdate(BaseModel):
    role_id: int | None = None
    role_ids: list[int] | None = None

    @model_validator(mode="after")
    def validate_roles(self):
        if self.role_ids is not None:
            if not self.role_ids:
                raise ValueError("至少需要分配一个角色")
            return self
        if self.role_id is not None:
            self.role_ids = [self.role_id]
            return self
        raise ValueError("role_id 或 role_ids 必须提供其一")


class PermissionMemberInfo(BaseModel):
    id: int
    user_id: int
    username: str
    full_name: str | None
    email: str | None
    avatar_url: str | None
    role_id: int | None
    role_code: str
    role_name: str
    role_ids: list[int] = Field(default_factory=list)
    role_codes: list[str] = Field(default_factory=list)
    role_names: list[str] = Field(default_factory=list)
    is_project_owner: bool
    invited_by: int | None
    created_at: datetime


class AvailableUserInfo(BaseModel):
    id: int
    username: str
    full_name: str | None
    email: str
    avatar_url: str | None
