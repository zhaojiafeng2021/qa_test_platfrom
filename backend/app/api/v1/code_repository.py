"""代码源（远程 Git 仓库）API

- GET    /projects/{pid}/code-repos                          列表
- POST   /projects/{pid}/code-repos                          新建
- PATCH  /projects/{pid}/code-repos/{rid}                    更新
- DELETE /projects/{pid}/code-repos/{rid}                    删除
- GET    /projects/{pid}/code-repos/{rid}/branches           远程分支
- GET    /projects/{pid}/code-repos/{rid}/services?branch=   分支下的 Java 服务
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_project_permission
from app.core.errors import success_response
from app.modules.auth.schemas import CurrentUser
from app.modules.code_repository.service import CodeRepositoryService
from app.schemas.code_repository import (
    CodeRepositoryCreate,
    CodeRepositoryOut,
    CodeRepositoryUpdate,
)

router = APIRouter()

# 代码源是覆盖率任务的配置项：读与覆盖率任务读接口一致（登录即可），写沿用 coverage:create
_read = [Depends(get_current_user)]
_write = [Depends(require_project_permission("coverage:create"))]


def _out(repo) -> dict:
    return CodeRepositoryOut.model_validate(repo).model_dump(mode="json")


@router.get("/projects/{project_id}/code-repos", dependencies=_read)
async def list_code_repos(project_id: int, db: AsyncSession = Depends(get_db)):
    repos = await CodeRepositoryService(db).list(project_id)
    return success_response(data=[_out(r) for r in repos])


@router.post("/projects/{project_id}/code-repos", status_code=201, dependencies=_write)
async def create_code_repo(
    project_id: int,
    data: CodeRepositoryCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    repo = await CodeRepositoryService(db).create(project_id, data.model_dump(), current_user.id)
    return success_response(data=_out(repo), message="创建成功")


@router.patch("/projects/{project_id}/code-repos/{repo_id}", dependencies=_write)
async def update_code_repo(
    project_id: int,
    repo_id: int,
    data: CodeRepositoryUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    patch = data.model_dump(exclude_unset=True)
    repo = await CodeRepositoryService(db).update(project_id, repo_id, patch, current_user.id)
    return success_response(data=_out(repo), message="更新成功")


@router.delete("/projects/{project_id}/code-repos/{repo_id}", dependencies=_write)
async def delete_code_repo(
    project_id: int,
    repo_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await CodeRepositoryService(db).delete(project_id, repo_id, current_user.id)
    return success_response(message="代码源已删除")


@router.get("/projects/{project_id}/code-repos/{repo_id}/branches", dependencies=_read)
async def list_repo_branches(project_id: int, repo_id: int, db: AsyncSession = Depends(get_db)):
    svc = CodeRepositoryService(db)
    repo = await svc.get(project_id, repo_id)
    return success_response(data=await svc.list_branches(repo))


@router.get("/projects/{project_id}/code-repos/{repo_id}/services", dependencies=_read)
async def list_repo_services(
    project_id: int,
    repo_id: int,
    branch: str = Query(..., min_length=1, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    svc = CodeRepositoryService(db)
    repo = await svc.get(project_id, repo_id)
    return success_response(data=await svc.discover_services(repo, branch))
