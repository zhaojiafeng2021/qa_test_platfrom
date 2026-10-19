"""
项目业务逻辑服务
"""
import hashlib
import secrets
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.project.repository import ProjectRepository
from app.modules.project.schemas import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    ProjectDetail,
    ProjectInfo,
    MemberInfo,
    ProjectSummary,
)
from app.modules.auth.repository import UserRepository
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember, ProjectRole
from app.db.models.permission import ProjectDataPolicy
from app.core.errors import (
    ValidationError,
    ResourceNotFoundError,
    PermissionDeniedError,
    ErrorCode,
)
from app.core.logging import get_logger
from app.modules.permission.repository import PermissionRepository

LEGACY_ROLE_CODES = {
    ProjectRole.OWNER: "project_admin",
    ProjectRole.ADMIN: "project_admin",
    ProjectRole.MEMBER: "tester",
    ProjectRole.VIEWER: "viewer",
}


logger = get_logger(__name__)


class ProjectService:
    """项目服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProjectRepository(db)
        self.user_repo = UserRepository(db)
        self.permission_repo = PermissionRepository(db)

    # ============ 项目 CRUD ============
    async def create_project(self, request: ProjectCreateRequest, owner_id: int) -> Project:
        """创建项目，并将创建者设置为OWNER成员"""
        if await self.repo.code_exists(request.code):
            raise ValidationError(
                message="项目代码已存在",
                details=[{"field": "code", "reason": "已被使用"}],
            )

        admin_role = await self.permission_repo.get_builtin_role("project_admin")
        if not admin_role:
            raise ValidationError(message="RBAC 内置角色尚未初始化，请先执行数据库迁移")

        project = await self.repo.create(
            code=request.code,
            name=request.name,
            owner_id=owner_id,
            description=request.description,
            icon=request.icon,
            color=request.color,
        )
        self.db.add_all([
            ProjectDataPolicy(
                project_id=project.id,
                resource_type=resource_type,
                visibility_scope="owner" if resource_type == "report" else "all",
                member_ids=[],
            ) for resource_type in ("api", "case", "report", "performance_report")
        ])

        # 创建者自动成为OWNER
        await self.repo.add_member(
            project_id=project.id,
            user_id=owner_id,
            role=ProjectRole.OWNER,
            role_id=admin_role.id,
            invited_by=owner_id,
        )

        await self.db.commit()
        logger.info(f"Project created: {project.code}", extra={"project_id": project.id, "user_id": owner_id})
        return project

    async def get_project_detail(self, project_id: int, user_id: int, is_superuser: bool) -> ProjectDetail:
        """获取项目详情（含当前用户角色和成员数）"""
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise ResourceNotFoundError(message="项目不存在")

        member = await self.repo.get_member(project_id, user_id)
        # 访问权限：超管 / 成员 / 公开项目
        if not member and not is_superuser and not project.is_public:
            raise PermissionDeniedError(message="无权访问该项目")

        member_count = await self.repo.count_members(project_id)

        detail = ProjectDetail.model_validate(project)
        detail.my_role = member.role.value if member else ("owner" if is_superuser else "viewer")
        detail.member_count = member_count
        return detail

    async def update_project(
        self, project_id: int, request: ProjectUpdateRequest, user_id: int, is_superuser: bool
    ) -> Project:
        """更新项目（需admin及以上权限）"""
        project = await self._require_project(project_id)
        await self._require_role(project_id, user_id, is_superuser, {ProjectRole.OWNER, ProjectRole.ADMIN})

        # 构建更新字段（过滤掉 None 值，但 grafana_config_json 例外，允许设置为 None 来清空配置）
        update_fields = {}
        if request.name is not None:
            update_fields['name'] = request.name
        if request.description is not None:
            update_fields['description'] = request.description
        if request.icon is not None:
            update_fields['icon'] = request.icon
        if request.color is not None:
            update_fields['color'] = request.color
        if request.is_public is not None:
            update_fields['is_public'] = request.is_public

        # grafana_config_json 特殊处理：即使为 None 也要更新（用于清空配置）
        if 'grafana_config_json' in request.model_fields_set:
            update_fields['grafana_config_json'] = request.grafana_config_json

        project = await self.repo.update(project, updated_by=user_id, **update_fields)
        await self.db.commit()
        logger.info(f"Project updated: {project.code}", extra={"project_id": project.id, "user_id": user_id})
        return project

    async def delete_project(self, project_id: int, user_id: int, is_superuser: bool) -> None:
        """删除项目（仅超级管理员）"""
        if not is_superuser:
            raise PermissionDeniedError(message="权限不足，仅超级管理员可删除项目")

        project = await self._require_project(project_id)
        await self.repo.soft_delete(project)
        await self.db.commit()
        logger.info(f"Project deleted: {project.code}", extra={"project_id": project.id, "user_id": user_id})

    async def list_projects(
        self,
        user_id: int,
        is_superuser: bool,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[list[ProjectInfo], int]:
        """列出用户可见的项目"""
        projects, total = await self.repo.list_for_user(
            user_id=user_id,
            is_superuser=is_superuser,
            page=page,
            page_size=page_size,
            keyword=keyword,
            status=status,
        )
        items = [ProjectInfo.model_validate(p) for p in projects]
        return items, total

    async def get_dashboard_summary(
        self, project_id: int, user_id: int, is_superuser: bool
    ) -> ProjectSummary:
        """Return project dashboard aggregates after access validation."""
        await self.get_project_detail(project_id, user_id, is_superuser)
        summary = await self.repo.get_dashboard_summary(project_id)
        return ProjectSummary.model_validate(summary)
    # ============ 成员管理 ============
    async def add_member(
        self, project_id: int, target_user_id: int, role_str: str, operator_id: int, is_superuser: bool
    ) -> ProjectMember:
        """添加成员（需admin及以上权限）"""
        await self._require_project(project_id)
        await self._require_role(project_id, operator_id, is_superuser, {ProjectRole.OWNER, ProjectRole.ADMIN})

        role = self._parse_role(role_str)
        rbac_role = await self._builtin_role_for_legacy(role)

        # 校验目标用户存在
        target = await self.user_repo.get_by_id(target_user_id)
        if not target:
            raise ResourceNotFoundError(message="目标用户不存在")

        # 校验是否已是成员
        existing = await self.repo.get_member(project_id, target_user_id)
        if existing:
            raise ValidationError(
                message="该用户已是项目成员",
                details=[{"field": "user_id", "reason": "已存在"}],
            )

        member = await self.repo.add_member(
            project_id=project_id,
            user_id=target_user_id,
            role=role,
            role_id=rbac_role.id,
            invited_by=operator_id,
        )
        await self.db.commit()
        logger.info(
            f"Member added to project {project_id}",
            extra={"project_id": project_id, "target_user_id": target_user_id, "operator_id": operator_id},
        )
        return member

    async def update_member_role(
        self, project_id: int, target_user_id: int, role_str: str, operator_id: int, is_superuser: bool
    ) -> ProjectMember:
        """更新成员角色（需admin及以上权限）"""
        await self._require_project(project_id)
        await self._require_role(project_id, operator_id, is_superuser, {ProjectRole.OWNER, ProjectRole.ADMIN})

        role = self._parse_role(role_str)
        rbac_role = await self._builtin_role_for_legacy(role)
        member = await self.repo.get_member(project_id, target_user_id)
        if not member:
            raise ResourceNotFoundError(message="该用户不是项目成员")

        # 若将唯一OWNER降级，需阻止
        if member.role == ProjectRole.OWNER and role != ProjectRole.OWNER:
            owner_count = await self.repo.count_owners(project_id)
            if owner_count <= 1:
                raise ValidationError(message="项目至少需要保留一名负责人")

        member = await self.repo.update_member_role(member, role, role_id=rbac_role.id)
        await self.db.commit()
        logger.info(
            f"Member role updated in project {project_id}",
            extra={"project_id": project_id, "target_user_id": target_user_id, "operator_id": operator_id},
        )
        return member

    async def remove_member(
        self, project_id: int, target_user_id: int, operator_id: int, is_superuser: bool
    ) -> None:
        """移除成员（需admin及以上权限）"""
        await self._require_project(project_id)
        await self._require_role(project_id, operator_id, is_superuser, {ProjectRole.OWNER, ProjectRole.ADMIN})

        member = await self.repo.get_member(project_id, target_user_id)
        if not member:
            raise ResourceNotFoundError(message="该用户不是项目成员")

        # 不可移除唯一OWNER
        if member.role == ProjectRole.OWNER:
            owner_count = await self.repo.count_owners(project_id)
            if owner_count <= 1:
                raise ValidationError(message="不能移除项目唯一的负责人")

        await self.repo.remove_member(member)
        await self.db.commit()
        logger.info(
            f"Member removed from project {project_id}",
            extra={"project_id": project_id, "target_user_id": target_user_id, "operator_id": operator_id},
        )

    async def list_members(self, project_id: int, user_id: int, is_superuser: bool) -> list[MemberInfo]:
        """列出项目成员（成员可见）"""
        project = await self._require_project(project_id)
        member = await self.repo.get_member(project_id, user_id)
        # 访问权限：超管 / 成员 / 公开项目
        if not member and not is_superuser and not project.is_public:
            raise PermissionDeniedError(message="无权访问该项目")

        rows = await self.repo.list_members(project_id)
        items: list[MemberInfo] = []
        for m, user in rows:
            items.append(MemberInfo(
                id=m.id,
                project_id=m.project_id,
                user_id=m.user_id,
                role=m.role.value,
                invited_by=m.invited_by,
                created_at=m.created_at,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
                is_virtual=False,
            ))

        # 如果是公开项目，添加虚拟"所有访客"成员
        if project.is_public:
            items.append(MemberInfo(
                id=0,  # 虚拟ID
                project_id=project_id,
                user_id=0,  # 虚拟用户ID
                role="viewer",
                invited_by=None,
                created_at=project.created_at,
                username="所有访客",
                email=None,
                full_name="公开项目访客用户",
                avatar_url=None,
                is_virtual=True,
            ))

        return items

    async def get_project_permissions(self, project_id: int, user_id: int, is_superuser: bool) -> list[str]:
        """获取用户在指定项目的权限码列表"""
        if is_superuser:
            return ["project:*"]
        permissions = await self.permission_repo.get_member_permission_codes(project_id, user_id)
        return permissions or []

    # ============ 内部辅助 ============
    async def _require_project(self, project_id: int) -> Project:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise ResourceNotFoundError(message="项目不存在")
        return project

    async def _require_role(
        self, project_id: int, user_id: int, is_superuser: bool, allowed: set[ProjectRole]
    ) -> None:
        """校验用户在项目中具备指定角色之一"""
        if is_superuser:
            return
        member = await self.repo.get_member(project_id, user_id)
        if not member or member.role not in allowed:
            raise PermissionDeniedError(message="权限不足，无法执行该操作")

    async def _builtin_role_for_legacy(self, role: ProjectRole):
        rbac_role = await self.permission_repo.get_builtin_role(LEGACY_ROLE_CODES[role])
        if not rbac_role:
            raise ValidationError(message="RBAC 内置角色尚未初始化，请先执行数据库迁移")
        return rbac_role

    @staticmethod
    def _parse_role(role_str: str) -> ProjectRole:
        try:
            return ProjectRole(role_str)
        except ValueError:
            raise ValidationError(
                message="无效的角色",
                details=[{"field": "role", "reason": "必须为 owner/admin/member/viewer 之一"}],
            )
