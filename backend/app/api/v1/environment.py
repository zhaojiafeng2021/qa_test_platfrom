"""
环境管理API路由
"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.db.base import get_db
from app.api.deps import get_current_user, get_client_ip, require_project_permission
from app.core.errors import success_response
from app.modules.audit.service import AuditService
from app.modules.auth.schemas import CurrentUser
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentUpdate,
    EnvironmentInfo,
    VariableCreate,
    VariableUpdate,
    VariableInfo,
    VariableInfoMasked,
)
from app.modules.environment.service import EnvironmentService, VariableService


router = APIRouter(prefix="/projects/{project_id}", tags=["环境管理"])


# ============ 环境管理 ============

@router.post("/environments", dependencies=[Depends(require_project_permission("asset:create"))])
async def create_environment(
    project_id: int,
    data: EnvironmentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """创建测试环境"""
    env = await EnvironmentService.create_environment(db, project_id, data, current_user.id)
    await AuditService(db).record(
        action="create", resource_type="environment",
        user_id=current_user.id, project_id=project_id, resource_id=env.id,
        detail_json={"name": getattr(env, "display_name", None) or getattr(env, "name", None)},
        ip_address=get_client_ip(request),
    )
    return success_response(data=env.model_dump())


@router.get("/environments")
async def list_environments(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """获取项目的所有环境"""
    envs = await EnvironmentService.list_environments(db, project_id)
    return success_response(data=[e.model_dump() for e in envs])


@router.get("/environments/{env_id}")
async def get_environment(
    project_id: int,
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """获取环境详情"""
    env = await EnvironmentService.get_environment(db, env_id)
    return success_response(data=env.model_dump())


@router.patch("/environments/{env_id}", dependencies=[Depends(require_project_permission("asset:update"))])
async def update_environment(
    project_id: int,
    env_id: int,
    data: EnvironmentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """更新环境"""
    env = await EnvironmentService.update_environment(db, env_id, data, current_user.id)
    await AuditService(db).record(
        action="update", resource_type="environment",
        user_id=current_user.id, project_id=project_id, resource_id=env_id,
        detail_json=data.model_dump(exclude_unset=True),
        ip_address=get_client_ip(request),
    )
    return success_response(data=env.model_dump())


@router.delete("/environments/{env_id}", dependencies=[Depends(require_project_permission("asset:delete"))])
async def delete_environment(
    project_id: int,
    env_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """删除环境"""
    await EnvironmentService.delete_environment(db, env_id, current_user.id)
    await AuditService(db).record(
        action="delete", resource_type="environment",
        user_id=current_user.id, project_id=project_id, resource_id=env_id,
        ip_address=get_client_ip(request),
    )
    return success_response(message="环境已删除")


# ============ 变量管理 ============

@router.post("/variables", dependencies=[Depends(require_project_permission("asset:create"))])
async def create_variable(
    project_id: int,
    data: VariableCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """创建变量"""
    var = await VariableService.create_variable(db, project_id, data, current_user.id)
    return success_response(data=var.model_dump())


@router.get("/variables")
async def list_variables(
    project_id: int,
    scope: Optional[str] = Query(None, description="作用域过滤: global/environment"),
    environment_id: Optional[int] = Query(None, description="环境ID过滤"),
    mask_secret: bool = Query(True, description="是否脱敏密钥变量"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """获取项目的变量列表"""
    variables = await VariableService.list_variables(
        db, project_id, scope, environment_id, mask_secret
    )
    return success_response(data=[v.model_dump() for v in variables])


@router.get("/variables/{var_id}")
async def get_variable(
    project_id: int,
    var_id: int,
    mask_secret: bool = Query(True, description="是否脱敏密钥变量"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """获取变量详情"""
    var = await VariableService.get_variable(db, var_id, mask_secret)
    return success_response(data=var.model_dump())


@router.patch("/variables/{var_id}", dependencies=[Depends(require_project_permission("asset:update"))])
async def update_variable(
    project_id: int,
    var_id: int,
    data: VariableUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """更新变量"""
    var = await VariableService.update_variable(db, var_id, data, current_user.id)
    return success_response(data=var.model_dump())


@router.delete("/variables/{var_id}", dependencies=[Depends(require_project_permission("asset:delete"))])
async def delete_variable(
    project_id: int,
    var_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user)
):
    """删除变量"""
    await VariableService.delete_variable(db, var_id, current_user.id)
    await AuditService(db).record(
        action="delete", resource_type="variable",
        user_id=current_user.id, project_id=project_id, resource_id=var_id,
        ip_address=get_client_ip(request),
    )
    return success_response(message="变量已删除")
