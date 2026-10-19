"""
认证业务逻辑服务
"""
from typing import Optional, Tuple
from datetime import datetime, timedelta
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    UserInfo,
    CurrentUser
)
from app.core.security import verify_password, create_access_token, create_refresh_token, decode_token
from app.core.errors import AuthenticationError, ValidationError, ErrorCode
from app.core.logging import get_logger
from app.db.models.user import User, UserStatus
from app.db.models.api_token import ApiToken
from sqlalchemy import select

logger = get_logger(__name__)

API_TOKEN_PREFIX = "qat_"


def _hash_api_token(token: str) -> str:
    """对 PAT 明文做 sha256 哈希（DB 只存哈希）"""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    """认证服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)

    async def register(self, request: RegisterRequest) -> User:
        """
        用户注册

        Args:
            request: 注册请求

        Returns:
            创建的用户

        Raises:
            ValidationError: 用户名或邮箱已存在
        """
        # 检查用户名是否已存在
        if await self.user_repo.username_exists(request.username):
            raise ValidationError(
                message="用户名已存在",
                details=[{"field": "username", "reason": "已被使用"}]
            )

        # 检查邮箱是否已存在
        if await self.user_repo.email_exists(request.email):
            raise ValidationError(
                message="邮箱已存在",
                details=[{"field": "email", "reason": "已被使用"}]
            )

        # 创建用户
        user = await self.user_repo.create(
            username=request.username,
            email=request.email,
            password=request.password,
            full_name=request.full_name
        )

        await self.db.commit()

        logger.info(f"User registered: {user.username}", extra={"user_id": user.id})

        return user

    async def login(self, request: LoginRequest, ip_address: str) -> Tuple[str, str, User]:
        """
        用户登录

        Args:
            request: 登录请求
            ip_address: 登录IP地址

        Returns:
            (access_token, refresh_token, user)

        Raises:
            AuthenticationError: 用户名或密码错误
        """
        # 查找用户
        user = await self.user_repo.get_by_username(request.username)
        if not user:
            raise AuthenticationError(message="用户名或密码错误")

        # 验证密码
        if not user.password_hash or not verify_password(request.password, user.password_hash):
            raise AuthenticationError(message="用户名或密码错误")

        # 检查用户状态
        if user.status != UserStatus.ACTIVE:
            if user.status == UserStatus.LOCKED:
                raise AuthenticationError(message="账号已被锁定", code=ErrorCode.PERMISSION_DENIED)
            else:
                raise AuthenticationError(message="账号未激活", code=ErrorCode.PERMISSION_DENIED)

        # 生成令牌
        access_token = create_access_token({"sub": str(user.id), "username": user.username})
        refresh_token = create_refresh_token({"sub": str(user.id)})

        # 更新最后登录信息
        await self.user_repo.update_last_login(user.id, ip_address)
        await self.db.commit()

        logger.info(f"User logged in: {user.username}", extra={"user_id": user.id})

        return access_token, refresh_token, user

    async def refresh_token(self, refresh_token: str) -> str:
        """
        刷新访问令牌

        Args:
            refresh_token: 刷新令牌

        Returns:
            新的访问令牌

        Raises:
            AuthenticationError: 令牌无效或过期
        """
        try:
            payload = decode_token(refresh_token)

            # 验证令牌类型
            if payload.get("type") != "refresh":
                raise AuthenticationError(message="无效的令牌类型")

            # 获取用户ID
            user_id = int(payload.get("sub"))

            # 验证用户是否存在
            user = await self.user_repo.get_by_id(user_id)
            if not user:
                raise AuthenticationError(message="用户不存在")

            # 检查用户状态
            if user.status != UserStatus.ACTIVE:
                raise AuthenticationError(message="账号不可用")

            # 生成新的访问令牌
            access_token = create_access_token({
                "sub": str(user.id),
                "username": user.username
            })

            return access_token

        except Exception as e:
            logger.warning(f"Failed to refresh token: {str(e)}")
            raise AuthenticationError(message="令牌无效或已过期", code=ErrorCode.TOKEN_INVALID)

    async def get_current_user(self, token: str) -> CurrentUser:
        """
        获取当前用户

        Args:
            token: 访问令牌（JWT 或以 qat_ 开头的个人访问令牌 PAT）

        Returns:
            当前用户信息

        Raises:
            AuthenticationError: 令牌无效
        """
        # 个人访问令牌（PAT）：以 qat_ 开头，走 DB 校验
        if token.startswith(API_TOKEN_PREFIX):
            return await self._authenticate_pat(token)

        try:
            payload = decode_token(token)

            # 验证令牌类型
            if payload.get("type") != "access":
                raise AuthenticationError(message="无效的令牌类型")

            # 获取用户ID
            user_id = int(payload.get("sub"))

            # 查询用户
            user = await self.user_repo.get_by_id(user_id)
            if not user:
                raise AuthenticationError(message="用户不存在")

            # 检查用户状态
            if user.status != UserStatus.ACTIVE:
                raise AuthenticationError(message="账号不可用")

            # TODO: 查询用户权限
            permissions = []
            if user.is_superuser:
                permissions = ["*"]  # 超级管理员拥有所有权限

            return CurrentUser(
                id=user.id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                avatar_url=user.avatar_url,
                status=user.status.value,
                is_superuser=user.is_superuser,
                permissions=permissions
            )

        except Exception as e:
            logger.warning(f"Failed to get current user: {str(e)}")
            raise AuthenticationError(message="令牌无效或已过期", code=ErrorCode.TOKEN_INVALID)

    # ============ 个人访问令牌（PAT） ============

    async def _authenticate_pat(self, token: str) -> CurrentUser:
        """校验个人访问令牌并返回当前用户"""
        token_hash = _hash_api_token(token)
        result = await self.db.execute(
            select(ApiToken).where(ApiToken.token_hash == token_hash)
        )
        api_token = result.scalar_one_or_none()

        if not api_token or not api_token.is_active:
            raise AuthenticationError(message="令牌无效", code=ErrorCode.TOKEN_INVALID)

        if api_token.expires_at is not None and api_token.expires_at < datetime.utcnow():
            raise AuthenticationError(message="令牌已过期", code=ErrorCode.TOKEN_EXPIRED)

        user = await self.user_repo.get_by_id(api_token.user_id)
        if not user:
            raise AuthenticationError(message="用户不存在", code=ErrorCode.TOKEN_INVALID)
        if user.status != UserStatus.ACTIVE:
            raise AuthenticationError(message="账号不可用", code=ErrorCode.TOKEN_INVALID)

        # 更新最后使用时间（best-effort，不阻塞认证）
        try:
            api_token.last_used_at = datetime.utcnow()
            await self.db.commit()
        except Exception:
            await self.db.rollback()

        permissions = ["*"] if user.is_superuser else []
        return CurrentUser(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            status=user.status.value,
            is_superuser=user.is_superuser,
            permissions=permissions,
        )

    async def create_api_token(
        self, user_id: int, name: str, expires_in_days: Optional[int]
    ) -> Tuple[ApiToken, str]:
        """创建个人访问令牌，返回 (记录, 明文token)。明文仅此一次可见。"""
        plain = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        api_token = ApiToken(
            user_id=user_id,
            name=name,
            token_hash=_hash_api_token(plain),
            token_prefix=plain[:12],
            expires_at=expires_at,
            is_active=True,
        )
        self.db.add(api_token)
        await self.db.commit()
        await self.db.refresh(api_token)
        logger.info(f"API token created: id={api_token.id} user_id={user_id} name={name}")
        return api_token, plain

    async def list_api_tokens(self, user_id: int) -> list[ApiToken]:
        """列出用户的所有 PAT（不含明文）"""
        result = await self.db.execute(
            select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.id.desc())
        )
        return list(result.scalars().all())

    async def revoke_api_token(self, user_id: int, token_id: int) -> None:
        """吊销（删除）指定 PAT"""
        result = await self.db.execute(
            select(ApiToken).where(
                ApiToken.id == token_id, ApiToken.user_id == user_id
            )
        )
        api_token = result.scalar_one_or_none()
        if not api_token:
            raise ValidationError(message="令牌不存在")
        await self.db.delete(api_token)
        await self.db.commit()
        logger.info(f"API token revoked: id={token_id} user_id={user_id}")

    async def feishu_login_or_register(
        self,
        feishu_open_id: str,
        feishu_union_id: Optional[str],
        name: str,
        email: str,
        avatar_url: Optional[str],
        ip_address: str
    ) -> Tuple[str, str, User]:
        """
        飞书登录或注册

        以邮箱为唯一标识：
        - 用户存在 -> 绑定飞书信息（若未绑定）+ 登录
        - 用户不存在 -> 注册新用户 + 以 viewer 角色加入所有项目 + 登录

        Args:
            feishu_open_id: 飞书OpenID
            feishu_union_id: 飞书UnionID
            name: 用户名
            email: 邮箱（唯一标识）
            avatar_url: 头像URL
            ip_address: IP地址

        Returns:
            (access_token, refresh_token, user)
        """
        # 优先用邮箱查找已有用户
        user = await self.user_repo.get_by_email(email)

        if not user:
            # 再用 feishu_open_id 查找（兼容历史数据）
            user = await self.user_repo.get_by_feishu_open_id(feishu_open_id)

        if not user:
            # 用户不存在，自动注册
            username = email.split('@')[0]
            if await self.user_repo.username_exists(username):
                username = f"{username}_{secrets.token_hex(4)}"

            user = await self.user_repo.create(
                username=username,
                email=email,
                full_name=name,
                feishu_open_id=feishu_open_id,
                feishu_union_id=feishu_union_id,
                avatar_url=avatar_url
            )

            # 将新用户以 viewer 角色加入所有活跃项目
            all_project_ids = await self.user_repo.get_all_project_ids()
            if all_project_ids:
                await self.user_repo.add_user_to_projects_as_viewer(user.id, all_project_ids)

            logger.info(f"User registered via Feishu: {user.username} (viewer in {len(all_project_ids)} projects)",
                        extra={"user_id": user.id})
        else:
            # 用户已存在，绑定/更新飞书信息
            if not user.feishu_open_id or user.feishu_open_id != feishu_open_id:
                await self.user_repo.update_feishu_info(
                    user, feishu_open_id, feishu_union_id, avatar_url, name
                )

            # 检查是否有尚未加入的新项目，自动加入为 viewer
            all_project_ids = await self.user_repo.get_all_project_ids()
            joined_project_ids = await self.user_repo.get_user_project_ids(user.id)
            new_project_ids = [pid for pid in all_project_ids if pid not in joined_project_ids]
            if new_project_ids:
                await self.user_repo.add_user_to_projects_as_viewer(user.id, new_project_ids)
                logger.info(f"Feishu user {user.username} auto-joined {len(new_project_ids)} new projects as viewer",
                            extra={"user_id": user.id})

        # 检查用户状态
        if user.status != UserStatus.ACTIVE:
            if user.status == UserStatus.LOCKED:
                raise AuthenticationError(message="账号已被锁定", code=ErrorCode.PERMISSION_DENIED)
            else:
                raise AuthenticationError(message="账号未激活", code=ErrorCode.PERMISSION_DENIED)

        # 生成令牌
        access_token = create_access_token({"sub": str(user.id), "username": user.username})
        refresh_token = create_refresh_token({"sub": str(user.id)})

        # 更新最后登录信息
        await self.user_repo.update_last_login(user.id, ip_address)
        await self.db.commit()

        logger.info(f"User logged in via Feishu: {user.username}", extra={"user_id": user.id})

        return access_token, refresh_token, user
