"""代码源（远程 Git 仓库）Schemas"""
import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# 拒绝以 "-" 开头（防止被 git 当作选项）以及空白字符
_URL_RE = re.compile(r"^(https?://|ssh://|git@)[^\s]+$")


def _check_url(v: str) -> str:
    v = v.strip()
    if not _URL_RE.match(v):
        raise ValueError("仓库地址需为 https://、ssh:// 或 git@ 开头的 Git URL")
    return v


class CodeRepositoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    repo_url: str = Field(..., min_length=1, max_length=500)
    default_branch: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("repo_url")
    @classmethod
    def _v_url(cls, v: str) -> str:
        return _check_url(v)


class CodeRepositoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    repo_url: Optional[str] = Field(None, min_length=1, max_length=500)
    default_branch: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

    @field_validator("repo_url")
    @classmethod
    def _v_url(cls, v: Optional[str]) -> Optional[str]:
        return _check_url(v) if v is not None else v


class CodeRepositoryOut(BaseModel):
    id: int
    project_id: int
    name: str
    repo_url: str
    default_branch: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RepoBranch(BaseModel):
    name: str
    commit_sha: str


class RepoService(BaseModel):
    """仓库内自动发现的 Java 服务（含 pom.xml / build.gradle 的目录）"""
    name: str
    path: str
    build_tool: str
