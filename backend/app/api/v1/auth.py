"""
认证相关API路由
"""
import secrets
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import RedirectResponse, JSONResponse

from app.api.deps import get_auth_service, get_current_user, get_client_ip
from app.db.base import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.auth.service import AuthService
from app.modules.auth.schemas import (
    LoginRequest,
    RegisterRequest,
    RefreshTokenRequest,
    UserInfo,
    CurrentUser,
    ApiTokenCreateRequest,
    ApiTokenCreateResponse,
    ApiTokenInfo,
)
from app.core.errors import success_response, AuthenticationError, ErrorCode
from app.core.redis_client import redis_client
from app.core.config import settings
from app.core.logging import get_logger, request_id_var
from app.integrations.feishu import feishu_client

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", summary="用户注册")
async def register(
    request: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    用户注册（本地账号）

    - **username**: 用户名（3-50字符）
    - **email**: 邮箱
    - **password**: 密码（6-100字符）
    - **full_name**: 全名（可选）
    """
    user = await auth_service.register(request)

    return success_response(
        data={
            "user": UserInfo.model_validate(user).model_dump()
        },
        message="注册成功",
        request_id=request_id_var.get()
    )


@router.post("/login", summary="用户登录")
async def login(
    request: LoginRequest,
    req: Request,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    用户登录（本地账号）

    - **username**: 用户名
    - **password**: 密码

    返回访问令牌和刷新令牌
    """
    ip_address = get_client_ip(req)
    access_token, refresh_token, user = await auth_service.login(request, ip_address)

    return success_response(
        data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": UserInfo.model_validate(user).model_dump()
        },
        message="登录成功",
        request_id=request_id_var.get()
    )


@router.post("/refresh", summary="刷新访问令牌")
async def refresh_token(
    request: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    使用刷新令牌获取新的访问令牌

    - **refresh_token**: 刷新令牌
    """
    access_token = await auth_service.refresh_token(request.refresh_token)

    return success_response(
        data={
            "access_token": access_token,
            "token_type": "bearer"
        },
        message="令牌刷新成功",
        request_id=request_id_var.get()
    )


@router.post("/logout", summary="退出登录")
async def logout(
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    退出登录

    需要在Header中提供有效的访问令牌
    """
    # TODO: 将refresh_token加入黑名单
    logger.info(f"User logged out: {current_user.username}", extra={"user_id": current_user.id})

    return success_response(
        message="退出成功",
        request_id=request_id_var.get()
    )


@router.get("/me", summary="获取当前用户信息")
async def get_me(
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    获取当前登录用户的信息和权限

    需要在Header中提供有效的访问令牌
    """
    return success_response(
        data=current_user.model_dump(),
        request_id=request_id_var.get()
    )


@router.post("/tokens", summary="创建个人访问令牌(PAT)")
async def create_api_token(
    request: ApiTokenCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    创建个人访问令牌，用于 CICD 等机器账号长期认证。

    - **name**: 令牌名称/用途标识
    - **expires_in_days**: 有效天数；不传或 null 表示永不过期

    返回的 token 明文仅此一次可见，请妥善保存。
    """
    api_token, plain = await auth_service.create_api_token(
        current_user.id, request.name, request.expires_in_days
    )
    return success_response(
        data=ApiTokenCreateResponse(
            id=api_token.id,
            name=api_token.name,
            token=plain,
            token_prefix=api_token.token_prefix,
            expires_at=api_token.expires_at,
            created_at=api_token.created_at,
        ).model_dump(),
        message="令牌创建成功",
        request_id=request_id_var.get(),
    )


@router.get("/tokens", summary="获取个人访问令牌列表")
async def list_api_tokens(
    current_user: CurrentUser = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """获取当前用户的所有个人访问令牌（不含明文）。"""
    tokens = await auth_service.list_api_tokens(current_user.id)
    return success_response(
        data=[ApiTokenInfo.model_validate(t).model_dump() for t in tokens],
        request_id=request_id_var.get(),
    )


@router.delete("/tokens/{token_id}", summary="吊销个人访问令牌")
async def revoke_api_token(
    token_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    """吊销（删除）指定的个人访问令牌。"""
    await auth_service.revoke_api_token(current_user.id, token_id)
    return success_response(message="令牌已吊销", request_id=request_id_var.get())


@router.get("/feishu/login", summary="获取飞书登录地址")
async def feishu_login(
    db: AsyncSession = Depends(get_db),
    redirect: str = Query(None, description="登录成功后重定向的路径")
):
    """
    获取飞书OAuth授权地址

    前端跳转到此地址进行飞书授权登录

    Args:
        redirect: 登录成功后要跳转的前端路径（如 /e2e_project/dashboard）
    """
    from app.integrations.feishu import get_feishu_client

    # 生成随机state防止CSRF
    state = secrets.token_urlsafe(32)

    # 将state存储到Redis（10分钟有效，给用户足够的授权时间）
    # 同时存储 redirect 路径
    state_data = {"redirect": redirect} if redirect else {}
    await redis_client.setex(f"feishu_state:{state}", 600, str(state_data))

    # 生成授权URL（从数据库读取配置）
    feishu_client = get_feishu_client(db)
    authorization_url = await feishu_client.get_authorization_url(state)

    response_data = success_response(
        data={
            "authorization_url": authorization_url,
            "state": state
        },
        request_id=request_id_var.get()
    )

    # 禁止缓存，每次都生成新的 state
    response = JSONResponse(content=response_data)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    return response


@router.get("/feishu/callback", summary="飞书登录回调")
async def feishu_callback(
    req: Request,
    code: str = Query(..., description="授权码"),
    state: str = Query(..., description="状态参数"),
    auth_service: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db)
):
    """
    飞书OAuth登录回调

    飞书授权后会重定向到此接口，携带授权码
    验证成功后重定向到前端并携带令牌
    """
    from app.integrations.feishu import get_feishu_client
    import json

    # 验证state
    state_key = f"feishu_state:{state}"
    state_value = await redis_client.get(state_key)
    if not state_value:
        raise AuthenticationError(
            message="无效的state参数，可能存在CSRF攻击或已过期",
            code=ErrorCode.TOKEN_INVALID
        )

    # 解析 redirect 路径
    try:
        state_data = eval(state_value) if state_value != "1" else {}
        redirect_path = state_data.get("redirect") if isinstance(state_data, dict) else None
    except:
        redirect_path = None

    # 删除已使用的state
    await redis_client.delete(state_key)

    try:
        # 使用带数据库会话的 feishu_client
        feishu_client = get_feishu_client(db)

        # 使用授权码获取用户访问令牌
        logger.info(f"Fetching access token with code: {code[:10]}...")
        token_data = await feishu_client.get_access_token(code)
        user_access_token = token_data["access_token"]
        logger.info(f"Access token obtained: {user_access_token[:10]}...")

        # 获取用户信息
        logger.info("Fetching user info from Feishu")
        user_info = await feishu_client.get_user_info(user_access_token)
        logger.info(f"Feishu user_info: open_id={user_info.get('open_id')}, email={user_info.get('email')}, name={user_info.get('name')}")

        # 提取用户信息
        feishu_open_id = user_info.get("open_id")
        feishu_union_id = user_info.get("union_id")
        name = user_info.get("name", "飞书用户")
        email = user_info.get("email") or f"{feishu_open_id}@feishu.local"
        avatar_url = user_info.get("avatar_url")

        # 登录或注册
        logger.info(f"Attempting login/register for email: {email}")
        ip_address = get_client_ip(req)
        access_token, refresh_token, user = await auth_service.feishu_login_or_register(
            feishu_open_id=feishu_open_id,
            feishu_union_id=feishu_union_id,
            name=name,
            email=email,
            avatar_url=avatar_url,
            ip_address=ip_address
        )
        logger.info(f"Login/register successful for user_id={user.id}")

        # 将登录信息存储到 Redis（7天有效）
        # 存储用户基本信息，供后续验证使用
        session_key = f"user_session:{user.id}"
        session_data = {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "is_superuser": user.is_superuser,
            "login_at": datetime.utcnow().isoformat(),
            "login_ip": ip_address
        }
        await redis_client.setex(session_key, 7 * 24 * 3600, json.dumps(session_data))
        logger.info(f"User session stored in Redis for 7 days: user_id={user.id}")

        # 推导前端地址（从请求 Host 头）
        host = req.headers.get("host", "localhost:5173")
        scheme = "https" if req.headers.get("x-forwarded-proto") == "https" else "http"
        frontend_url = f"{scheme}://{host}"
        logger.info(f"Frontend URL resolved: {frontend_url}")

        # 构建回调 URL，如果有 redirect 参数则附加
        callback_path = "/auth/callback"
        redirect_url = (
            f"{frontend_url}{callback_path}"
            f"?access_token={access_token}"
            f"&refresh_token={refresh_token}"
        )
        if redirect_path:
            # URL encode redirect_path
            from urllib.parse import quote
            redirect_url += f"&redirect={quote(redirect_path)}"

        logger.info(f"Redirecting to: {redirect_url[:100]}...")
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logger.error(f"Feishu callback failed: {str(e)}", exc_info=True)
        # 错误时也从请求推导前端地址
        host = req.headers.get("host", "localhost:5173")
        scheme = "https" if req.headers.get("x-forwarded-proto") == "https" else "http"
        frontend_url = f"{scheme}://{host}"
        return RedirectResponse(url=f"{frontend_url}/login?error=feishu_login_failed")
