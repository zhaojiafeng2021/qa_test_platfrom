"""
飞书集成模块
提供飞书OAuth登录和API调用功能
"""
import httpx
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class FeishuClient:
    """飞书API客户端"""

    def __init__(self, db: Optional[AsyncSession] = None):
        """
        初始化飞书客户端

        Args:
            db: 数据库会话（用于从数据库读取配置）
        """
        self.db = db

        # 优先使用环境变量配置（向后兼容）
        self.app_id = settings.feishu_app_id
        self.app_secret = settings.feishu_app_secret
        self.redirect_uri = settings.feishu_redirect_uri

        # 飞书API端点
        self.base_url = "https://open.feishu.cn/open-apis"
        self.auth_url = "https://open.feishu.cn/open-apis/authen/v1"

        # 缓存app_access_token
        self._app_access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def _load_db_config(self):
        """从数据库加载配置（如果环境变量为空）"""
        if self.db and (not self.app_id or not self.app_secret or not self.redirect_uri):
            from app.modules.system_config.service import SystemConfigService
            config_service = SystemConfigService(self.db)
            feishu_config = await config_service.get_feishu_config()

            # 如果环境变量为空或空字符串，使用数据库配置
            if not self.app_id:
                self.app_id = feishu_config.get("app_id", "")
                logger.info(f"Loaded feishu.app_id from database: {self.app_id}")
            if not self.app_secret:
                self.app_secret = feishu_config.get("app_secret", "")
                logger.info(f"Loaded feishu.app_secret from database: {self.app_secret[:10]}...")
            if not self.redirect_uri:
                self.redirect_uri = feishu_config.get("redirect_uri", "")
                logger.info(f"Loaded feishu.redirect_uri from database: {self.redirect_uri}")

    async def get_app_access_token(self) -> str:
        """
        获取应用访问令牌（tenant_access_token）
        用于调用飞书API
        """
        # 从数据库加载配置（如果环境变量为空）
        await self._load_db_config()

        # 检查缓存的token是否有效
        if self._app_access_token and self._token_expires_at:
            if datetime.utcnow() < self._token_expires_at:
                return self._app_access_token

        # 获取新token
        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        data = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(f"Failed to get app access token: {result}")
                raise Exception(f"Failed to get app access token: {result.get('msg')}")

            # 缓存token（提前5分钟过期）
            self._app_access_token = result["tenant_access_token"]
            expires_in = result.get("expire", 7200)  # 默认2小时
            self._token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 300)

            return self._app_access_token

    async def get_authorization_url(self, state: str) -> str:
        """
        获取飞书OAuth授权地址

        Args:
            state: 状态参数，用于防止CSRF攻击

        Returns:
            授权URL
        """
        # 从数据库加载配置（如果环境变量为空）
        await self._load_db_config()

        params = {
            "app_id": self.app_id,
            "redirect_uri": self.redirect_uri,
            "state": state
        }

        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"https://open.feishu.cn/open-apis/authen/v1/authorize?{query_string}"

    async def get_access_token(self, code: str) -> Dict[str, Any]:
        """
        使用授权码获取用户访问令牌

        Args:
            code: 授权码

        Returns:
            包含access_token等信息的字典
        """
        url = f"{self.auth_url}/access_token"
        data = {
            "grant_type": "authorization_code",
            "code": code
        }

        app_access_token = await self.get_app_access_token()
        headers = {
            "Authorization": f"Bearer {app_access_token}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(f"Failed to get access token: {result}")
                raise Exception(f"Failed to get access token: {result.get('msg')}")

            return result["data"]

    async def get_user_info(self, user_access_token: str) -> Dict[str, Any]:
        """
        获取用户信息

        Args:
            user_access_token: 用户访问令牌

        Returns:
            用户信息字典
        """
        url = f"{self.auth_url}/user_info"
        headers = {
            "Authorization": f"Bearer {user_access_token}"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(f"Failed to get user info: {result}")
                raise Exception(f"Failed to get user info: {result.get('msg')}")

            return result["data"]

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """
        刷新用户访问令牌

        Args:
            refresh_token: 刷新令牌

        Returns:
            新的token信息
        """
        url = f"{self.auth_url}/refresh_access_token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }

        app_access_token = await self.get_app_access_token()
        headers = {
            "Authorization": f"Bearer {app_access_token}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(f"Failed to refresh access token: {result}")
                raise Exception(f"Failed to refresh access token: {result.get('msg')}")

            return result["data"]

    async def send_message(
        self,
        receive_id: str,
        content: Dict[str, Any],
        msg_type: str = "text",
        receive_id_type: str = "open_id"
    ) -> Dict[str, Any]:
        """
        发送消息（用于通知功能）

        Args:
            receive_id: 接收者ID
            content: 消息内容
            msg_type: 消息类型（text/post/card等）
            receive_id_type: ID类型（open_id/user_id/union_id等）

        Returns:
            发送结果
        """
        url = f"{self.base_url}/im/v1/messages"
        app_access_token = await self.get_app_access_token()

        headers = {
            "Authorization": f"Bearer {app_access_token}",
            "Content-Type": "application/json"
        }

        params = {
            "receive_id_type": receive_id_type
        }

        data = {
            "receive_id": receive_id,
            "msg_type": msg_type,
            "content": content
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=data, headers=headers, params=params)
            response.raise_for_status()
            result = response.json()

            if result.get("code") != 0:
                logger.error(f"Failed to send message: {result}")
                raise Exception(f"Failed to send message: {result.get('msg')}")

            return result["data"]


# 工厂函数：需要时创建带 db 的客户端实例
def get_feishu_client(db: Optional[AsyncSession] = None) -> FeishuClient:
    """获取飞书客户端实例"""
    return FeishuClient(db=db)


# 全局实例（向后兼容，不推荐使用）
feishu_client = FeishuClient()
