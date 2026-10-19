"""API dependencies for authentication, authorization, and request context."""
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthenticationError, ErrorCode, PermissionDeniedError
from app.core.logging import project_id_var, user_id_var
from app.db.base import get_db
from app.modules.auth.schemas import CurrentUser
from app.modules.auth.service import AuthService


security = HTTPBearer(auto_error=False)


async def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(db)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_service: AuthService = Depends(get_auth_service),
) -> CurrentUser:
    if not credentials:
        raise AuthenticationError(
            message="未提供认证令牌",
            code=ErrorCode.TOKEN_MISSING,
        )
    current_user = await auth_service.get_current_user(credentials.credentials)
    user_id_var.set(str(current_user.id))
    return current_user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    auth_service: AuthService = Depends(get_auth_service),
) -> Optional[CurrentUser]:
    if not credentials:
        return None
    try:
        current_user = await auth_service.get_current_user(credentials.credentials)
        user_id_var.set(str(current_user.id))
        return current_user
    except Exception:
        return None


def require_permissions(*required_permissions: str):
    async def permission_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.is_superuser or "*" in current_user.permissions:
            return current_user
        for permission in required_permissions:
            if not _permission_granted(current_user.permissions, permission):
                raise PermissionDeniedError(
                    message=f"权限不足，需要权限: {permission}"
                )
        return current_user

    return permission_checker


def _permission_granted(granted: list[str], required: str) -> bool:
    if required in granted or "*" in granted:
        return True
    for permission in granted:
        if permission.endswith(":*") and required.startswith(permission[:-1]):
            return True
    return False


def require_project_permission(*required_permissions: str):
    """Authorize from RBAC v2 effective grants, with legacy-role fallback."""

    async def checker(
        request: Request,
        project_id: int,
        current_user: CurrentUser = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> CurrentUser:
        project_id_var.set(str(project_id))
        if current_user.is_superuser:
            return current_user

        from app.modules.permission.repository import PermissionRepository

        granted = await PermissionRepository(db).get_member_permission_codes(
            project_id, current_user.id
        )
        if granted is None:
            raise PermissionDeniedError(message="无权访问该项目")
        for permission in required_permissions:
            if not _permission_granted(granted, permission):
                raise PermissionDeniedError(
                    message=f"权限不足，需要权限: {permission}"
                )
        return current_user

    return checker


async def get_current_superuser(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """仅超级管理员可访问"""
    if not current_user.is_superuser:
        raise PermissionDeniedError(message="需要超级管理员权限")
    return current_user


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"
