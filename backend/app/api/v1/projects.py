"""
项目管理相关API路由
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.modules.auth.schemas import CurrentUser
from app.modules.project.service import ProjectService
from app.modules.project.schemas import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectInfo,
    MemberAddRequest,
    MemberUpdateRequest,
)
from app.db.base import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import success_response
from app.core.logging import request_id_var

router = APIRouter(prefix="/projects", tags=["项目管理"])


async def get_project_service(db: AsyncSession = Depends(get_db)) -> ProjectService:
    """获取项目服务"""
    return ProjectService(db)


@router.post("", summary="创建项目")
async def create_project(
    request: ProjectCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """
    创建新项目

    - **code**: 项目代码（唯一，字母开头）
    - **name**: 项目名称
    - **description**: 描述（可选）

    创建者自动成为项目负责人（OWNER）
    """
    project = await service.create_project(request, current_user.id)
    return success_response(
        data=ProjectInfo.model_validate(project).model_dump(),
        message="项目创建成功",
        request_id=request_id_var.get(),
    )


@router.get("", summary="获取项目列表")
async def list_projects(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    keyword: Optional[str] = Query(None, description="按项目名称搜索"),
    status: Optional[str] = Query(None, description="按状态过滤: active/archived"),
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """
    获取当前用户可见的项目列表

    超级管理员可见全部项目，普通用户仅可见其为成员的项目
    """
    items, total = await service.list_projects(
        user_id=current_user.id,
        is_superuser=current_user.is_superuser,
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
    )
    return success_response(
        data={
            "items": [i.model_dump() for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        request_id=request_id_var.get(),
    )


@router.get("/{project_id}/summary", summary="获取项目工作台汇总")
async def get_project_summary(
    project_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    summary = await service.get_dashboard_summary(
        project_id, current_user.id, current_user.is_superuser
    )
    return success_response(
        data=summary.model_dump(),
        request_id=request_id_var.get(),
    )

@router.get("/{project_id}", summary="获取项目详情")
async def get_project(
    project_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """获取项目详情（含当前用户角色和成员数量）"""
    detail = await service.get_project_detail(
        project_id, current_user.id, current_user.is_superuser
    )
    return success_response(
        data=detail.model_dump(),
        request_id=request_id_var.get(),
    )


@router.patch("/{project_id}", summary="更新项目")
async def update_project(
    project_id: int,
    request: ProjectUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """更新项目信息（需负责人或管理员权限）"""
    project = await service.update_project(
        project_id, request, current_user.id, current_user.is_superuser
    )
    return success_response(
        data=ProjectInfo.model_validate(project).model_dump(),
        message="项目更新成功",
        request_id=request_id_var.get(),
    )


@router.delete("/{project_id}", summary="删除项目")
async def delete_project(
    project_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """删除项目（软删除，仅负责人可操作）"""
    await service.delete_project(project_id, current_user.id, current_user.is_superuser)
    return success_response(
        message="项目删除成功",
        request_id=request_id_var.get(),
    )


# ============ 成员管理 ============
@router.get("/{project_id}/members", summary="获取项目成员列表")
async def list_members(
    project_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """获取项目成员列表"""
    members = await service.list_members(
        project_id, current_user.id, current_user.is_superuser
    )
    return success_response(
        data={
            "items": [m.model_dump() for m in members],
            "total": len(members),
        },
        request_id=request_id_var.get(),
    )


@router.post("/{project_id}/members", summary="添加项目成员")
async def add_member(
    project_id: int,
    request: MemberAddRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """添加项目成员（需负责人或管理员权限）"""
    member = await service.add_member(
        project_id=project_id,
        target_user_id=request.user_id,
        role_str=request.role,
        operator_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    return success_response(
        data={
            "id": member.id,
            "project_id": member.project_id,
            "user_id": member.user_id,
            "role": member.role.value,
        },
        message="成员添加成功",
        request_id=request_id_var.get(),
    )


@router.patch("/{project_id}/members/{user_id}", summary="更新成员角色")
async def update_member(
    project_id: int,
    user_id: int,
    request: MemberUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """更新成员角色（需负责人或管理员权限）"""
    member = await service.update_member_role(
        project_id=project_id,
        target_user_id=user_id,
        role_str=request.role,
        operator_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    return success_response(
        data={
            "id": member.id,
            "project_id": member.project_id,
            "user_id": member.user_id,
            "role": member.role.value,
        },
        message="成员角色更新成功",
        request_id=request_id_var.get(),
    )


@router.delete("/{project_id}/members/{user_id}", summary="移除项目成员")
async def remove_member(
    project_id: int,
    user_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
):
    """移除项目成员（需负责人或管理员权限）"""
    await service.remove_member(
        project_id=project_id,
        target_user_id=user_id,
        operator_id=current_user.id,
        is_superuser=current_user.is_superuser,
    )
    return success_response(
        message="成员移除成功",
        request_id=request_id_var.get(),
    )


@router.get("/{project_id}/my-permissions", summary="获取当前用户在项目中的权限")
async def get_my_project_permissions(
    project_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取当前用户在指定项目中的权限列表

    返回格式：
    {
        "permissions": ["asset:read", "asset:create", ...],
        "is_member": true
    }

    如果用户是超级管理员，返回 ["*"]
    如果用户不是项目成员但项目是公开的，返回 viewer 权限
    如果用户不是项目成员且项目私有，返回 is_member=false
    """
    from app.modules.permission.repository import PermissionRepository
    from app.modules.project.repository import ProjectRepository
    from app.db.models.project_member import ROLE_PERMISSIONS

    # 超级管理员拥有所有权限
    if current_user.is_superuser:
        return success_response(
            data={
                "permissions": ["*"],
                "is_member": True,
                "is_superuser": True,
            },
            request_id=request_id_var.get(),
        )

    # 获取用户在项目中的权限
    perm_repo = PermissionRepository(db)
    permissions = await perm_repo.get_member_permission_codes(project_id, current_user.id)

    if permissions is None:
        # 不是项目成员，检查项目是否公开
        project_repo = ProjectRepository(db)
        project = await project_repo.get_by_id(project_id)

        if project and project.is_public:
            # 公开项目：返回 viewer 权限
            viewer_permissions = ROLE_PERMISSIONS.get("viewer", [])
            return success_response(
                data={
                    "permissions": viewer_permissions,
                    "is_member": False,
                    "is_superuser": False,
                    "is_public_viewer": True,
                },
                request_id=request_id_var.get(),
            )

        # 私有项目：无权限
        return success_response(
            data={
                "permissions": [],
                "is_member": False,
                "is_superuser": False,
            },
            request_id=request_id_var.get(),
        )

    return success_response(
        data={
            "permissions": permissions,
            "is_member": True,
            "is_superuser": False,
        },
        request_id=request_id_var.get(),
    )
