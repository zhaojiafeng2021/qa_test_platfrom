"""Project RBAC v2 API."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_permission
from app.core.errors import success_response
from app.db.base import get_db
from app.modules.auth.schemas import CurrentUser
from app.modules.permission.schemas import (
    DataPolicyUpdate,
    PermissionMemberAdd,
    PermissionMemberUpdate,
    RoleCreate,
    RoleUpdate,
)
from app.modules.permission.service import PermissionService

router = APIRouter(prefix="/projects/{project_id}/permissions", tags=["权限管理 RBAC v2"])


@router.get("/catalog", dependencies=[Depends(require_project_permission("project:read"))])
async def list_catalog(project_id: int, db: AsyncSession = Depends(get_db)):
    items = await PermissionService(db).list_catalog()
    return success_response(data=[{
        "id": item.id, "code": item.code, "name": item.name, "module": item.module,
        "action": item.action, "description": item.description,
        "platform_only": item.platform_only, "sort_order": item.sort_order,
    } for item in items])


@router.get("/roles", dependencies=[Depends(require_project_permission("project:read"))])
async def list_roles(project_id: int, db: AsyncSession = Depends(get_db)):
    items = await PermissionService(db).list_roles(project_id)
    return success_response(data=[item.model_dump(mode="json") for item in items])


@router.post("/roles", status_code=201, dependencies=[Depends(require_project_permission("permission:role:manage"))])
async def create_role(
    project_id: int, data: RoleCreate, db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    item = await PermissionService(db).create_role(project_id, data, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="角色创建成功")


@router.put("/roles/{role_id}", dependencies=[Depends(require_project_permission("permission:role:manage"))])
async def update_role(
    project_id: int, role_id: int, data: RoleUpdate, db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    item = await PermissionService(db).update_role(project_id, role_id, data, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="角色更新成功")


@router.delete("/roles/{role_id}", dependencies=[Depends(require_project_permission("permission:role:manage"))])
async def delete_role(
    project_id: int, role_id: int, db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    await PermissionService(db).delete_role(project_id, role_id, current_user.id)
    return success_response(message="角色已删除")


@router.get("/data-policies", dependencies=[Depends(require_project_permission("project:read"))])
async def list_data_policies(project_id: int, db: AsyncSession = Depends(get_db)):
    items = await PermissionService(db).list_data_policies(project_id)
    return success_response(data=[item.model_dump(mode="json") for item in items])


@router.put("/data-policies/{resource_type}", dependencies=[Depends(require_project_permission("permission:data:manage"))])
async def update_data_policy(
    project_id: int, resource_type: str, data: DataPolicyUpdate,
    db: AsyncSession = Depends(get_db), current_user: CurrentUser = Depends(get_current_user),
):
    item = await PermissionService(db).update_data_policy(project_id, resource_type, data, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="数据权限已更新")


@router.get("/members", dependencies=[Depends(require_project_permission("project:member:read"))])
async def list_members(project_id: int, db: AsyncSession = Depends(get_db)):
    items = await PermissionService(db).list_members(project_id)
    return success_response(data=[item.model_dump(mode="json") for item in items])


@router.get("/available-users", dependencies=[Depends(require_project_permission("project:member:manage"))])
async def search_available_users(
    project_id: int,
    keyword: str | None = Query(None, max_length=100),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    items = await PermissionService(db).search_available_users(project_id, keyword, limit)
    return success_response(data=[item.model_dump(mode="json") for item in items])


@router.post("/members", status_code=201, dependencies=[Depends(require_project_permission("project:member:manage"))])
async def add_member(
    project_id: int, data: PermissionMemberAdd, db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    item = await PermissionService(db).add_member(project_id, data.user_id, data.role_id, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="成员添加成功")


@router.patch("/members/{user_id}", dependencies=[Depends(require_project_permission("project:member:manage"))])
async def assign_member_role(
    project_id: int, user_id: int, data: PermissionMemberUpdate, db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    role_ids = data.role_ids if data.role_ids else [data.role_id] if data.role_id else []
    item = await PermissionService(db).assign_member_roles(project_id, user_id, role_ids, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="成员角色已更新")


@router.delete("/members/{user_id}", dependencies=[Depends(require_project_permission("project:member:manage"))])
async def remove_member(
    project_id: int, user_id: int, db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    await PermissionService(db).remove_member(project_id, user_id, current_user.id)
    return success_response(message="成员已移除")
