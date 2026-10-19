"""Database operations for project RBAC."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.permission import (
    Permission,
    ProjectDataPolicy,
    ProjectMemberRole,
    Role,
    RoleDirectPermission,
    RolePermission,
)
from app.db.models.project_member import ProjectMember, ROLE_PERMISSIONS
from app.db.models.user import User, UserStatus


class PermissionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_permissions(self) -> list[Permission]:
        rows = await self.db.execute(
            select(Permission).order_by(Permission.module, Permission.sort_order, Permission.id)
        )
        return list(rows.scalars().all())

    async def permission_map(self, codes: Sequence[str] | None = None) -> dict[str, Permission]:
        stmt = select(Permission)
        if codes is not None:
            stmt = stmt.where(Permission.code.in_(list(codes)))
        rows = await self.db.execute(stmt)
        return {item.code: item for item in rows.scalars().all()}

    async def get_role(self, role_id: int) -> Role | None:
        row = await self.db.execute(
            select(Role)
            .options(
                selectinload(Role.permissions),
                selectinload(Role.direct_permissions),
                selectinload(Role.parent_role),
            )
            .where(Role.id == role_id)
        )
        return row.scalar_one_or_none()

    async def get_builtin_role(self, code: str) -> Role | None:
        row = await self.db.execute(
            select(Role).where(Role.project_id.is_(None), Role.code == code)
        )
        return row.scalar_one_or_none()

    async def role_code_exists(
        self, project_id: int, code: str, exclude_id: int | None = None
    ) -> bool:
        stmt = select(Role.id).where(Role.project_id == project_id, Role.code == code)
        if exclude_id is not None:
            stmt = stmt.where(Role.id != exclude_id)
        return (await self.db.execute(stmt)).scalar_one_or_none() is not None

    async def list_roles(self, project_id: int) -> list[tuple[Role, int]]:
        member_count = (
            select(ProjectMember.role_id, func.count(ProjectMember.id).label("member_count"))
            .where(ProjectMember.project_id == project_id, ProjectMember.is_deleted == False)
            .group_by(ProjectMember.role_id)
            .subquery()
        )
        rows = await self.db.execute(
            select(Role, func.coalesce(member_count.c.member_count, 0))
            .outerjoin(member_count, member_count.c.role_id == Role.id)
            .options(
                selectinload(Role.permissions),
                selectinload(Role.direct_permissions),
                selectinload(Role.parent_role),
            )
            .where((Role.project_id.is_(None)) | (Role.project_id == project_id))
            .order_by(Role.is_builtin.desc(), Role.id)
        )
        return [(role, int(count)) for role, count in rows.all()]

    async def create_role(self, **values) -> Role:
        role = Role(**values)
        self.db.add(role)
        await self.db.flush()
        return role

    async def replace_role_permissions(self, role_id: int, permission_ids: Sequence[int]) -> None:
        await self.db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        self.db.add_all([
            RolePermission(role_id=role_id, permission_id=permission_id)
            for permission_id in permission_ids
        ])
        await self.db.flush()

    async def replace_direct_role_permissions(
        self, role_id: int, permission_ids: Sequence[int]
    ) -> None:
        await self.db.execute(
            delete(RoleDirectPermission).where(RoleDirectPermission.role_id == role_id)
        )
        self.db.add_all([
            RoleDirectPermission(role_id=role_id, permission_id=permission_id)
            for permission_id in permission_ids
        ])
        await self.db.flush()

    async def get_direct_permission_codes(self, role_id: int) -> set[str]:
        rows = await self.db.execute(
            select(Permission.code)
            .join(
                RoleDirectPermission,
                RoleDirectPermission.permission_id == Permission.id,
            )
            .where(RoleDirectPermission.role_id == role_id)
        )
        return set(rows.scalars().all())

    async def get_effective_permission_codes(self, role_id: int) -> set[str]:
        rows = await self.db.execute(
            select(Permission.code)
            .join(RolePermission, RolePermission.permission_id == Permission.id)
            .where(RolePermission.role_id == role_id)
        )
        return set(rows.scalars().all())

    async def list_child_roles(self, parent_role_id: int) -> list[Role]:
        rows = await self.db.execute(
            select(Role).where(Role.parent_role_id == parent_role_id).order_by(Role.id)
        )
        return list(rows.scalars().all())

    async def role_member_count(self, project_id: int, role_id: int) -> int:
        row = await self.db.execute(
            select(func.count(ProjectMember.id)).where(
                ProjectMember.project_id == project_id,
                ProjectMember.role_id == role_id,
                ProjectMember.is_deleted == False,
            )
        )
        return int(row.scalar_one())

    async def delete_role(self, role: Role) -> None:
        await self.db.delete(role)
        await self.db.flush()

    async def get_member_permission_codes(self, project_id: int, user_id: int) -> list[str] | None:
        row = await self.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
                ProjectMember.is_deleted == False,
            )
        )
        member = row.scalar_one_or_none()
        if not member:
            return None

        # 多角色并集：优先从 project_member_roles 表获取所有角色
        multi_role_ids = await self.get_member_role_ids(member.id)
        if multi_role_ids:
            all_codes: set[str] = set()
            for rid in multi_role_ids:
                codes = await self.get_effective_permission_codes(rid)
                if codes:
                    all_codes.update(codes)
                else:
                    # Fallback: role_permissions 可能为空，用 ROLE_PERMISSIONS legacy map
                    role_row = await self.db.execute(select(Role.code).where(Role.id == rid))
                    role_code = role_row.scalar_one_or_none()
                    if role_code and role_code in ROLE_PERMISSIONS:
                        all_codes.update(ROLE_PERMISSIONS[role_code])
            if all_codes:
                return sorted(all_codes)

        # 兼容：旧数据仍用 member.role_id 单角色
        if member.role_id:
            codes = sorted(await self.get_effective_permission_codes(member.role_id))
            if codes:
                return codes
            role_row = await self.db.execute(select(Role.code).where(Role.id == member.role_id))
            role_code = role_row.scalar_one_or_none()
            if role_code and role_code in ROLE_PERMISSIONS:
                return list(ROLE_PERMISSIONS[role_code])

        role_value = member.role.value if hasattr(member.role, "value") else str(member.role)
        return list(ROLE_PERMISSIONS.get(role_value, []))

    async def get_member_role_ids(self, member_id: int) -> list[int]:
        try:
            async with self.db.begin_nested():
                rows = await self.db.execute(
                    select(ProjectMemberRole.role_id).where(ProjectMemberRole.member_id == member_id)
                )
                return list(rows.scalars().all())
        except Exception:
            # project_member_roles 表可能尚未创建（migration 未运行），优雅降级
            return []

    async def replace_member_roles(self, member_id: int, role_ids: list[int]) -> None:
        try:
            async with self.db.begin_nested():
                await self.db.execute(
                    delete(ProjectMemberRole).where(ProjectMemberRole.member_id == member_id)
                )
                self.db.add_all([
                    ProjectMemberRole(member_id=member_id, role_id=rid) for rid in role_ids
                ])
                await self.db.flush()
        except Exception:
            # project_member_roles 表可能尚未创建，跳过
            pass

    async def get_member_roles(self, member_id: int) -> list[Role]:
        try:
            async with self.db.begin_nested():
                rows = await self.db.execute(
                    select(Role)
                    .join(ProjectMemberRole, ProjectMemberRole.role_id == Role.id)
                    .where(ProjectMemberRole.member_id == member_id)
                    .order_by(Role.id)
                )
                return list(rows.scalars().all())
        except Exception:
            # project_member_roles 表可能尚未创建，优雅降级
            return []

    async def list_data_policies(self, project_id: int) -> list[ProjectDataPolicy]:
        rows = await self.db.execute(
            select(ProjectDataPolicy)
            .where(ProjectDataPolicy.project_id == project_id)
            .order_by(ProjectDataPolicy.resource_type)
        )
        return list(rows.scalars().all())

    async def get_data_policy(self, project_id: int, resource_type: str) -> ProjectDataPolicy | None:
        row = await self.db.execute(
            select(ProjectDataPolicy).where(
                ProjectDataPolicy.project_id == project_id,
                ProjectDataPolicy.resource_type == resource_type,
            )
        )
        return row.scalar_one_or_none()

    async def list_members(self, project_id: int) -> list[tuple[ProjectMember, User, Role | None]]:
        rows = await self.db.execute(
            select(ProjectMember, User, Role)
            .join(User, User.id == ProjectMember.user_id)
            .outerjoin(Role, Role.id == ProjectMember.role_id)
            .where(ProjectMember.project_id == project_id, ProjectMember.is_deleted == False)
            .order_by(ProjectMember.created_at, ProjectMember.id)
        )
        return list(rows.all())

    async def project_member_ids(self, project_id: int) -> set[int]:
        rows = await self.db.execute(
            select(ProjectMember.user_id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.is_deleted == False,
            )
        )
        return set(rows.scalars().all())

    async def search_available_users(
        self, project_id: int, keyword: str | None, limit: int = 20
    ) -> list[User]:
        is_member = select(ProjectMember.id).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == User.id,
            ProjectMember.is_deleted == False,
        ).exists()
        stmt = select(User).where(User.status == UserStatus.ACTIVE, ~is_member)
        if keyword:
            term = f"%{keyword.strip()}%"
            stmt = stmt.where(or_(
                User.username.ilike(term),
                User.full_name.ilike(term),
                User.email.ilike(term),
            ))
        rows = await self.db.execute(
            stmt.order_by(User.full_name, User.username).limit(limit)
        )
        return list(rows.scalars().all())
