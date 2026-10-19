"""
一次性种子脚本：灌入 RBAC 内置角色、权限目录和角色-权限映射。
执行一次即可（有唯一约束，重复执行会报错，可按需清空后重跑）。
"""
import asyncio

from app.db.base import AsyncSessionLocal
from app.core.snowflake import generate_id
from sqlalchemy import text


PERMISSIONS = [
    ("project:read", "查看项目", "project", "read", False),
    ("project:update", "编辑项目", "project", "update", False),
    ("project:member:read", "查看项目成员", "member", "read", False),
    ("project:member:manage", "管理项目成员", "member", "manage", False),
    ("permission:role:manage", "管理项目角色", "permission", "manage", False),
    ("permission:data:manage", "管理数据权限", "permission", "manage_data", False),
    ("permission:audit:read", "查看权限审计", "permission", "read_audit", False),
    ("notification:read", "查看通知配置", "notification", "read", False),
    ("notification:manage", "管理通知配置", "notification", "manage", False),
    ("asset:read", "查看测试资产", "asset", "read", False),
    ("asset:create", "新建测试资产", "asset", "create", False),
    ("asset:update", "编辑测试资产", "asset", "update", False),
    ("asset:delete", "删除测试资产", "asset", "delete", False),
    ("execution:read", "查看执行记录", "execution", "read", False),
    ("execution:run", "发起测试执行", "execution", "run", False),
    ("case:read", "查看用例", "case", "read", False),
    ("case:create", "新建用例", "case", "create", False),
    ("case:update", "编辑用例", "case", "update", False),
    ("case:delete", "删除用例", "case", "delete", False),
    ("case:run", "运行用例", "case", "run", False),
    ("report:read", "查看报告", "report", "read", False),
    ("report:export", "导出报告", "report", "export", False),
    ("report:delete", "删除报告", "report", "delete", False),
    ("platform:user:manage", "管理全平台用户", "platform", "manage_users", True),
    ("platform:role:manage", "管理平台角色", "platform", "manage_roles", True),
    ("platform:settings:manage", "管理系统配置", "platform", "manage_settings", True),
]

ROLE_DEFINITIONS = [
    ("super_admin", "超级管理员", "拥有全部平台权限，实际身份仍由 users.is_superuser 决定。", "platform"),
    ("project_admin", "项目管理员", "项目内全部权限，可管理成员、角色与通知。", "project"),
    ("senior_tester", "高级测试工程师", "可管理测试资产并执行测试。", "project"),
    ("tester", "测试工程师", "可创建和运行测试资产。", "project"),
    ("viewer", "观察者", "只读查看项目与测试结果。", "project"),
]

_ALL_CODES = {code for code, *_ in PERMISSIONS}
_PLATFORM_ONLY_CODES = {code for code, _n, _m, _a, platform_only in PERMISSIONS if platform_only}

ROLE_PERMISSION_CODES = {
    "super_admin": _ALL_CODES,
    "project_admin": _ALL_CODES - _PLATFORM_ONLY_CODES,
    "senior_tester": {
        "project:read", "project:member:read",
        "notification:read",
        "asset:read", "asset:create", "asset:update", "asset:delete",
        "execution:read", "execution:run",
        "case:read", "case:create", "case:update", "case:delete", "case:run",
        "report:read", "report:export", "report:delete",
    },
    "tester": {
        "project:read", "project:member:read",
        "notification:read",
        "asset:read", "asset:create", "asset:update",
        "execution:read", "execution:run",
        "case:read", "case:create", "case:update", "case:run",
        "report:read", "report:export",
    },
    "viewer": {
        "project:read", "project:member:read",
        "notification:read",
        "asset:read", "execution:read", "case:read", "report:read",
    },
}


async def seed() -> None:
    async with AsyncSessionLocal() as db:
        # 1. 插入权限目录
        for sort_order, (code, name, module, action, platform_only) in enumerate(PERMISSIONS, start=1):
            await db.execute(
                text(
                    "INSERT INTO permissions (id, code, name, module, action, platform_only, sort_order) "
                    "VALUES (:id, :code, :name, :module, :action, :platform_only, :sort_order)"
                ),
                {
                    "id": generate_id(),
                    "code": code,
                    "name": name,
                    "module": module,
                    "action": action,
                    "platform_only": platform_only,
                    "sort_order": sort_order,
                },
            )

        # 2. 插入内置角色（project_id 为 NULL，is_builtin 固定 1）
        for code, name, description, scope in ROLE_DEFINITIONS:
            await db.execute(
                text(
                    "INSERT INTO roles (id, code, name, description, scope, is_builtin, created_at, updated_at) "
                    "VALUES (:id, :code, :name, :description, :scope, 1, NOW(), NOW())"
                ),
                {
                    "id": generate_id(),
                    "code": code,
                    "name": name,
                    "description": description,
                    "scope": scope,
                },
            )

        await db.flush()

        # 3. 插入角色-权限关联
        for role_code, permission_codes in ROLE_PERMISSION_CODES.items():
            for permission_code in sorted(permission_codes):
                await db.execute(
                    text(
                        "INSERT INTO role_permissions (role_id, permission_id) "
                        "SELECT r.id, p.id FROM roles r, permissions p "
                        "WHERE r.code=:role_code AND r.project_id IS NULL AND p.code=:permission_code"
                    ),
                    {"role_code": role_code, "permission_code": permission_code},
                )
                await db.execute(
                    text(
                        "INSERT INTO role_direct_permissions (role_id, permission_id) "
                        "SELECT r.id, p.id FROM roles r, permissions p "
                        "WHERE r.code=:role_code AND r.project_id IS NULL AND p.code=:permission_code"
                    ),
                    {"role_code": role_code, "permission_code": permission_code},
                )

        await db.commit()
    print("RBAC_SEED_OK")


if __name__ == "__main__":
    asyncio.run(seed())
