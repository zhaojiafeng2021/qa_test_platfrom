"""Project RBAC business rules."""
from __future__ import annotations

import re
import secrets
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import PermissionDeniedError, ResourceNotFoundError, ValidationError
from app.core.logging import get_logger
from app.db.models.permission import ProjectDataPolicy, ProjectMemberRole, Role
from app.db.models.project_member import ProjectMember, ProjectRole
from app.modules.audit.service import AuditService
from app.modules.auth.repository import UserRepository
from app.modules.notification.service import NotificationService
from app.modules.permission.repository import PermissionRepository
from app.modules.permission.schemas import (
    AvailableUserInfo,
    DataPolicyInfo,
    DataPolicyUpdate,
    PermissionMemberInfo,
    RoleCreate,
    RoleInfo,
    RoleUpdate,
)
from app.modules.project.repository import ProjectRepository

logger = get_logger(__name__)

RESOURCE_TYPES = {"api", "case", "report", "performance_report"}
DATA_POLICY_DEFAULTS = {
    "api": "all",
    "case": "all",
    "report": "owner",
    "performance_report": "all",
}
LEGACY_ROLE_FOR_CODE = {
    "project_admin": ProjectRole.ADMIN,
    "senior_tester": ProjectRole.MEMBER,
    "tester": ProjectRole.MEMBER,
    "viewer": ProjectRole.VIEWER,
}


class PermissionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = PermissionRepository(db)
        self.project_repo = ProjectRepository(db)
        self.user_repo = UserRepository(db)
        self.audit = AuditService(db)

    async def list_catalog(self):
        return await self.repo.list_permissions()

    async def list_roles(self, project_id: int) -> list[RoleInfo]:
        await self._require_project(project_id)
        return [self._role_info(role, count) for role, count in await self.repo.list_roles(project_id)]

    async def create_role(self, project_id: int, data: RoleCreate, user_id: int) -> RoleInfo:
        await self._require_project(project_id)
        code = data.code or await self._new_role_code(project_id, data.name)
        if await self.repo.role_code_exists(project_id, code):
            raise ValidationError("角色编码已存在")
        await self._validate_parent(project_id, data.parent_role_id)
        direct_permissions = await self._resolve_direct_permissions(data.permission_codes)
        role = await self.repo.create_role(
            project_id=project_id,
            code=code,
            name=data.name.strip(),
            description=data.description,
            scope="project",
            is_builtin=False,
            parent_role_id=data.parent_role_id,
            created_by=user_id,
            updated_by=user_id,
        )
        await self.repo.replace_direct_role_permissions(
            role.id, [permission.id for permission in direct_permissions.values()]
        )
        await self._rebuild_role_tree(role.id)
        await self.audit.record(
            "role.create",
            "role",
            user_id,
            project_id,
            role.id,
            {
                "name": role.name,
                "code": role.code,
                "parent_role_id": role.parent_role_id,
                "direct_permission_codes": sorted(direct_permissions),
            },
        )
        await self.db.commit()
        role = await self.repo.get_role(role.id)
        return self._role_info(role, 0)

    async def update_role(
        self, project_id: int, role_id: int, data: RoleUpdate, user_id: int
    ) -> RoleInfo:
        role = await self._require_editable_role(project_id, role_id)
        values = data.model_dump(exclude_unset=True)
        # 内置角色只允许修改 description 和 permission_codes（内置角色为全局共享，改动影响所有项目）
        if role.is_builtin:
            forbidden = [k for k in values if k not in ("description", "permission_codes")]
            if forbidden:
                raise PermissionDeniedError('内置角色不允许修改：' + ', '.join(forbidden))
        before = {
            "name": role.name,
            "parent_role_id": role.parent_role_id,
            "direct_permission_codes": sorted(p.code for p in role.direct_permissions),
            "permission_codes": sorted(p.code for p in role.permissions),
        }
        if "name" in values:
            role.name = values["name"].strip()
        if "description" in values:
            role.description = values["description"]
        if "parent_role_id" in values:
            await self._validate_parent(
                project_id, values["parent_role_id"], descendant_role_id=role.id
            )
            role.parent_role_id = values["parent_role_id"]
        if "permission_codes" in values:
            direct_permissions = await self._resolve_direct_permissions(
                values["permission_codes"] or []
            )
            await self.repo.replace_direct_role_permissions(
                role.id, [permission.id for permission in direct_permissions.values()]
            )
        role.updated_by = user_id
        await self.db.flush()
        await self._rebuild_role_tree(role.id)
        await self.audit.record(
            "role.update", "role", user_id, project_id, role.id,
            {"before": before, "changed_fields": sorted(values)},
        )
        await self.db.commit()
        role = await self.repo.get_role(role.id)
        return self._role_info(
            role, await self.repo.role_member_count(project_id, role.id)
        )

    async def delete_role(self, project_id: int, role_id: int, user_id: int) -> None:
        role = await self._require_custom_role(project_id, role_id)
        if await self.repo.role_member_count(project_id, role_id):
            raise ValidationError("该角色仍有成员，需先重新分配成员角色")
        children = await self.repo.list_child_roles(role_id)
        for child in children:
            child.parent_role_id = None
            child.updated_by = user_id
        await self.db.flush()
        await self.audit.record(
            "role.delete", "role", user_id, project_id, role.id,
            {"name": role.name, "detached_child_role_ids": [child.id for child in children]},
        )
        await self.repo.delete_role(role)
        for child in children:
            await self._rebuild_role_tree(child.id)
        await self.db.commit()

    async def list_data_policies(self, project_id: int) -> list[DataPolicyInfo]:
        await self._require_project(project_id)
        policies = {item.resource_type: item for item in await self.repo.list_data_policies(project_id)}
        created = False
        for resource_type, scope in DATA_POLICY_DEFAULTS.items():
            if resource_type not in policies:
                item = ProjectDataPolicy(
                    project_id=project_id,
                    resource_type=resource_type,
                    visibility_scope=scope,
                    member_ids=[],
                )
                self.db.add(item)
                policies[resource_type] = item
                created = True
        if created:
            await self.db.commit()
        return [DataPolicyInfo.model_validate(policies[key]) for key in sorted(policies)]

    async def update_data_policy(
        self, project_id: int, resource_type: str, data: DataPolicyUpdate, user_id: int
    ) -> DataPolicyInfo:
        await self._require_project(project_id)
        if resource_type not in RESOURCE_TYPES:
            raise ValidationError("不支持的资源类型")
        member_ids = sorted(set(data.member_ids))
        if data.visibility_scope == "members":
            project_member_ids = await self.repo.project_member_ids(project_id)
            if not set(member_ids).issubset(project_member_ids):
                raise ValidationError("指定成员必须属于当前项目")
        policy = await self.repo.get_data_policy(project_id, resource_type)
        if not policy:
            policy = ProjectDataPolicy(project_id=project_id, resource_type=resource_type)
            self.db.add(policy)
        before = {"visibility_scope": policy.visibility_scope, "member_ids": policy.member_ids}
        policy.visibility_scope = data.visibility_scope
        policy.member_ids = member_ids
        policy.updated_by = user_id
        await self.audit.record(
            "data_policy.update", "data_policy", user_id, project_id, resource_type,
            {"before": before, "after": data.model_dump()},
        )
        await self.db.commit()
        await self.db.refresh(policy)
        return DataPolicyInfo.model_validate(policy)

    async def list_members(self, project_id: int) -> list[PermissionMemberInfo]:
        project = await self._require_project(project_id)
        items = []
        for member, user, role in await self.repo.list_members(project_id):
            role_code, role_name = self._member_role(member, role)
            # 多角色: 查询 project_member_roles 获取所有角色
            multi_roles = await self.repo.get_member_roles(member.id)
            logger.info(f"Member {member.id} multi_roles: {multi_roles}")
            if multi_roles:
                role_ids = [r.id for r in multi_roles]
                role_codes = [r.code for r in multi_roles]
                role_names = [r.name for r in multi_roles]
            else:
                # 兼容旧数据: 用单角色
                role_ids = [member.role_id] if member.role_id else []
                role_codes = [role_code]
                role_names = [role_name]
            logger.info(f"Member {member.id} role_ids={role_ids}, role_codes={role_codes}, role_names={role_names}")
            items.append(PermissionMemberInfo(
                id=member.id,
                user_id=user.id,
                username=user.username,
                full_name=user.full_name,
                email=user.email,
                avatar_url=user.avatar_url,
                role_id=member.role_id,
                role_code=role_code,
                role_name=role_name,
                role_ids=role_ids,
                role_codes=role_codes,
                role_names=role_names,
                is_project_owner=user.id == project.owner_id,
                invited_by=member.invited_by,
                created_at=member.created_at,
            ))
        return items

    async def search_available_users(
        self, project_id: int, keyword: str | None, limit: int = 20
    ) -> list[AvailableUserInfo]:
        await self._require_project(project_id)
        users = await self.repo.search_available_users(project_id, keyword, limit)
        return [AvailableUserInfo(
            id=user.id,
            username=user.username,
            full_name=user.full_name,
            email=user.email,
            avatar_url=user.avatar_url,
        ) for user in users]

    async def add_member(
        self, project_id: int, target_user_id: int, role_id: int, user_id: int
    ) -> PermissionMemberInfo:
        await self._require_project(project_id)
        if await self.project_repo.get_member(project_id, target_user_id):
            raise ValidationError("该用户已是项目成员")
        if not await self.user_repo.get_by_id(target_user_id):
            raise ResourceNotFoundError("目标用户不存在")
        role = await self._require_assignable_role(project_id, role_id)
        member = await self.project_repo.add_member(
            project_id,
            target_user_id,
            LEGACY_ROLE_FOR_CODE.get(role.code, ProjectRole.MEMBER),
            user_id,
        )
        member.role_id = role.id
        await self.db.flush()
        await self.repo.replace_member_roles(member.id, [role.id])
        await self.audit.record(
            "member.invite", "project_member", user_id, project_id, target_user_id,
            {"role_id": role.id, "role_name": role.name},
        )
        delivery_ids = await self._write_permission_change_event(
            project_id, target_user_id, role.name, user_id, "member_added"
        )
        await self.db.commit()
        await NotificationService.wake_deliveries(delivery_ids)
        return next(item for item in await self.list_members(project_id) if item.user_id == target_user_id)

    async def assign_member_role(
        self, project_id: int, target_user_id: int, role_id: int, user_id: int
    ) -> PermissionMemberInfo:
        project = await self._require_project(project_id)
        role = await self._require_assignable_role(project_id, role_id)
        member = await self.project_repo.get_member(project_id, target_user_id)
        if not member:
            raise ResourceNotFoundError("该用户不是项目成员")
        if target_user_id == project.owner_id and role.code != "project_admin":
            raise ValidationError("项目创建人的管理员角色不可降级")
        old_role_id = member.role_id
        member.role_id = role.id
        if target_user_id != project.owner_id:
            member.role = LEGACY_ROLE_FOR_CODE.get(role.code, ProjectRole.MEMBER)
        await self.db.flush()  # 确保 member 变更已写入数据库
        await self.audit.record(
            "member.role_changed", "project_member", user_id, project_id, target_user_id,
            {"old_role_id": old_role_id, "new_role_id": role.id, "new_role_name": role.name},
        )
        # 通知事件 best-effort，不阻塞角色修改；使用 savepoint 隔离，防止失败导致事务回滚
        delivery_ids: list[int] = []
        try:
            async with self.db.begin_nested():
                delivery_ids = await self._write_permission_change_event(
                    project_id, target_user_id, role.name, user_id, "role_changed"
                )
        except Exception as e:
            logger.warning(f"Failed to emit permission change event: {e}")
        await self.db.commit()
        if delivery_ids:
            try:
                await NotificationService.wake_deliveries(delivery_ids)
            except Exception as e:
                logger.warning(f"Failed to wake deliveries: {e}")
        return next(item for item in await self.list_members(project_id) if item.user_id == target_user_id)

    async def assign_member_roles(
        self, project_id: int, target_user_id: int, role_ids: list[int], user_id: int
    ) -> PermissionMemberInfo:
        """多角色分配：替换成员的全部角色。"""
        project = await self._require_project(project_id)
        member = await self.project_repo.get_member(project_id, target_user_id)
        if not member:
            raise ResourceNotFoundError("该用户不是项目成员")
        if not role_ids:
            raise ValidationError("至少需要分配一个角色")

        # 验证所有角色
        roles: list[Role] = []
        for rid in role_ids:
            role = await self._require_assignable_role(project_id, rid)
            roles.append(role)

        # 项目创建人必须保留 project_admin
        if target_user_id == project.owner_id:
            if not any(r.code == "project_admin" for r in roles):
                raise ValidationError("项目创建人必须保留管理员角色")

        old_role_ids = await self.repo.get_member_role_ids(member.id)

        # 写入多角色关联表
        await self.repo.replace_member_roles(member.id, [r.id for r in roles])

        # 兼容：同步更新 member.role_id 为第一个角色（向后兼容旧代码读取）
        primary_role = roles[0]
        member.role_id = primary_role.id
        if target_user_id != project.owner_id:
            member.role = LEGACY_ROLE_FOR_CODE.get(primary_role.code, ProjectRole.MEMBER)
        await self.db.flush()

        role_names = [r.name for r in roles]
        await self.audit.record(
            "member.roles_changed", "project_member", user_id, project_id, target_user_id,
            {"old_role_ids": old_role_ids, "new_role_ids": [r.id for r in roles],
             "new_role_names": role_names},
        )

        delivery_ids: list[int] = []
        try:
            async with self.db.begin_nested():
                delivery_ids = await self._write_permission_change_event(
                    project_id, target_user_id, " / ".join(role_names), user_id, "role_changed"
                )
        except Exception as e:
            logger.warning(f"Failed to emit permission change event: {e}")
        await self.db.commit()
        if delivery_ids:
            try:
                await NotificationService.wake_deliveries(delivery_ids)
            except Exception as e:
                logger.warning(f"Failed to wake deliveries: {e}")
        return next(item for item in await self.list_members(project_id) if item.user_id == target_user_id)

    async def remove_member(self, project_id: int, target_user_id: int, user_id: int) -> None:
        project = await self._require_project(project_id)
        if target_user_id == project.owner_id:
            raise ValidationError("不能移除项目创建人")
        member = await self.project_repo.get_member(project_id, target_user_id)
        if not member:
            raise ResourceNotFoundError("该用户不是项目成员")
        await self.audit.record(
            "member.remove", "project_member", user_id, project_id, target_user_id
        )
        delivery_ids = await self._write_permission_change_event(
            project_id, target_user_id, "已移除", user_id, "member_removed"
        )
        await self.project_repo.remove_member(member)
        await self.db.commit()
        await NotificationService.wake_deliveries(delivery_ids)

    async def _resolve_direct_permissions(self, codes: list[str]) -> dict:
        requested = set(codes)
        permission_map = await self.repo.permission_map(sorted(requested))
        missing = requested - set(permission_map)
        if missing:
            raise ValidationError(f"未知权限码: {', '.join(sorted(missing))}")
        if any(permission.platform_only for permission in permission_map.values()):
            raise PermissionDeniedError("项目角色不能授予平台级权限")
        return permission_map

    async def _validate_parent(
        self,
        project_id: int,
        parent_role_id: int | None,
        descendant_role_id: int | None = None,
    ) -> Role | None:
        if parent_role_id is None:
            return None
        parent = await self.repo.get_role(parent_role_id)
        if not parent or (parent.project_id is not None and parent.project_id != project_id):
            raise ValidationError("继承角色不存在或不属于当前项目")
        if parent.scope == "platform":
            raise ValidationError("项目角色不能继承平台级角色")
        seen: set[int] = set()
        cursor = parent
        while cursor:
            if cursor.id in seen:
                raise ValidationError("角色继承关系中存在环")
            if descendant_role_id is not None and cursor.id == descendant_role_id:
                raise ValidationError("角色继承不能形成环")
            seen.add(cursor.id)
            if cursor.parent_role_id is None:
                break
            cursor = await self.repo.get_role(cursor.parent_role_id)
        return parent

    async def _rebuild_role_tree(self, role_id: int, visited: set[int] | None = None) -> None:
        visited = visited or set()
        if role_id in visited:
            raise ValidationError("角色继承关系中存在环")
        visited.add(role_id)
        role = await self.repo.get_role(role_id)
        if not role:
            return
        direct_codes = await self.repo.get_direct_permission_codes(role.id)
        inherited_codes: set[str] = set()
        if role.parent_role_id:
            inherited_codes = await self.repo.get_effective_permission_codes(role.parent_role_id)
        permission_map = await self.repo.permission_map(sorted(direct_codes | inherited_codes))
        await self.repo.replace_role_permissions(
            role.id, sorted(permission.id for permission in permission_map.values())
        )
        for child in await self.repo.list_child_roles(role.id):
            await self._rebuild_role_tree(child.id, set(visited))

    async def _require_project(self, project_id: int):
        project = await self.project_repo.get_by_id(project_id)
        if not project:
            raise ResourceNotFoundError("项目不存在")
        return project

    async def _require_custom_role(self, project_id: int, role_id: int) -> Role:
        role = await self.repo.get_role(role_id)
        if not role or role.project_id != project_id:
            raise ResourceNotFoundError("自定义角色不存在")
        if role.is_builtin:
            raise PermissionDeniedError("内置角色不可修改")
        return role

    async def _require_editable_role(self, project_id: int, role_id: int) -> Role:
        """验证角色可编辑（自定义角色或内置角色，但仅允许修改权限和描述）。"""
        role = await self.repo.get_role(role_id)
        if not role:
            raise ResourceNotFoundError("角色不存在")
        # 自定义角色必须属于当前项目
        if role.project_id is not None and role.project_id != project_id:
            raise ResourceNotFoundError("角色不存在")
        # 内置角色也可编辑（但 update_role 中限制只能改权限和描述）
        return role

    async def _require_assignable_role(self, project_id: int, role_id: int) -> Role:
        role = await self.repo.get_role(role_id)
        if not role or (role.project_id is not None and role.project_id != project_id):
            raise ResourceNotFoundError("角色不存在")
        if role.scope == "platform" or role.code == "super_admin":
            raise PermissionDeniedError("平台超级管理员不能通过项目角色授予")
        return role

    async def _write_permission_change_event(
        self,
        project_id: int,
        target_user_id: int,
        role_name: str,
        operator_id: int,
        change_type: str,
    ) -> list[int]:
        return await NotificationService(self.db).emit_event(
            project_id=project_id,
            event_id=f"member-permission:{project_id}:{target_user_id}:{uuid4().hex}",
            event_type="member.permission_changed",
            context={
                "member_id": target_user_id,
                "role_name": role_name,
                "operator_id": operator_id,
                "change_type": change_type,
            },
            summary=f"成员 #{target_user_id} 的权限已变更：{role_name}",
        )

    async def _new_role_code(self, project_id: int, name: str) -> str:
        base = self._slug(name)
        if base != "custom_role" and not await self.repo.role_code_exists(project_id, base):
            return base
        while True:
            candidate = f"{base}_{secrets.token_hex(3)}"
            if not await self.repo.role_code_exists(project_id, candidate):
                return candidate

    @staticmethod
    def _slug(name: str) -> str:
        ascii_slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return ascii_slug[:52] or "custom_role"

    @staticmethod
    def _member_role(member: ProjectMember, role: Role | None) -> tuple[str, str]:
        if role:
            return role.code, role.name
        value = member.role.value if hasattr(member.role, "value") else str(member.role)
        names = {"owner": "项目负责人", "admin": "项目管理员", "member": "测试工程师", "viewer": "观察者"}
        return value, names.get(value, value)

    @staticmethod
    def _role_info(role: Role, member_count: int) -> RoleInfo:
        return RoleInfo(
            id=role.id,
            project_id=role.project_id,
            code=role.code,
            name=role.name,
            description=role.description,
            scope=role.scope,
            is_builtin=role.is_builtin,
            parent_role_id=role.parent_role_id,
            parent_role_name=role.parent_role.name if role.parent_role else None,
            direct_permission_codes=sorted(p.code for p in role.direct_permissions),
            permission_codes=sorted(p.code for p in role.permissions),
            member_count=member_count,
            created_at=role.created_at,
            updated_at=role.updated_at,
        )
