"""
安全工具模块
提供密码哈希、JWT令牌、加密等功能
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import secrets

from jose import JWTError, jwt
from passlib.context import CryptContext
from cryptography.fernet import Fernet
import base64
import hashlib

from .config import settings


# 密码哈希上下文
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """对密码进行哈希"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    创建访问令牌

    Args:
        data: 要编码的数据
        expires_delta: 过期时间增量

    Returns:
        JWT令牌字符串
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

    return encoded_jwt


def create_refresh_token(data: Dict[str, Any]) -> str:
    """
    创建刷新令牌

    Args:
        data: 要编码的数据

    Returns:
        JWT令牌字符串
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=settings.jwt_refresh_token_expire_days)

    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "refresh",
        "jti": secrets.token_urlsafe(32)  # JWT ID，用于撤销
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

    return encoded_jwt


def decode_token(token: str) -> Dict[str, Any]:
    """
    解码令牌

    Args:
        token: JWT令牌字符串

    Returns:
        解码后的数据

    Raises:
        JWTError: 令牌无效或过期
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm]
    )
    return payload


def generate_random_token(length: int = 32) -> str:
    """生成随机令牌"""
    return secrets.token_urlsafe(length)


def create_param_file_download_token(project_id: int, file_id: int, expires_minutes: int = 60) -> str:
    """生成参数化文件下载的短期签名令牌。

    用于远程负载机 Agent 主动拉取参数化文件（方案B），Agent 没有用户登录态，
    不能走 get_current_user 的 JWT 校验，因此单独签发一个限定 project_id/file_id、
    短时效的令牌，由下载接口专门校验（不复用访问令牌的权限体系）。
    """
    to_encode = {
        "type": "param_file_download",
        "project_id": project_id,
        "file_id": file_id,
        "exp": datetime.utcnow() + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_param_file_download_token(token: str, project_id: int, file_id: int) -> bool:
    """校验参数化文件下载令牌是否有效且匹配指定的 project_id/file_id。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return False
    return (
        payload.get("type") == "param_file_download"
        and payload.get("project_id") == project_id
        and payload.get("file_id") == file_id
    )


class DataEncryptor:
    """数据加密器，用于加密敏感数据"""

    def __init__(self):
        # 将配置的密钥转换为32字节密钥
        key = hashlib.sha256(settings.encryption_key.encode()).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, plain_text: str) -> str:
        """
        加密文本

        Args:
            plain_text: 明文

        Returns:
            加密后的文本
        """
        if not plain_text:
            return ""

        encrypted = self.fernet.encrypt(plain_text.encode())
        return encrypted.decode()

    def decrypt(self, encrypted_text: str) -> str:
        """
        解密文本

        Args:
            encrypted_text: 密文

        Returns:
            解密后的明文
        """
        if not encrypted_text:
            return ""

        decrypted = self.fernet.decrypt(encrypted_text.encode())
        return decrypted.decode()


# 全局加密器实例
encryptor = DataEncryptor()


def encrypt_sensitive_data(data: str) -> str:
    """加密敏感数据"""
    return encryptor.encrypt(data)


def decrypt_sensitive_data(data: str) -> str:
    """解密敏感数据"""
    return encryptor.decrypt(data)


def generate_request_id() -> str:
    """生成请求ID"""
    # 使用类似ULID的格式：时间戳 + 随机数
    timestamp = datetime.utcnow().strftime("%y%m%d%H%M%S")
    random_part = secrets.token_hex(6)
    return f"req_{timestamp}_{random_part}"
