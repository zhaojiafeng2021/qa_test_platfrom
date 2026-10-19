"""MinIO 文件存储客户端封装。"""
from __future__ import annotations

import io
from datetime import timedelta
from typing import BinaryIO

import urllib3
from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# MinIO 不可用时快速失败：短超时 + 不重试，避免默认 5 次重试（~30s）拖慢
# 报告生成的本地 fallback。连接被拒绝时约 1-2s 内失败并落本地。
_FAST_FAIL_HTTP = urllib3.PoolManager(
    timeout=urllib3.Timeout(connect=2.0, read=5.0),
    retries=urllib3.Retry(total=0, connect=0, read=0, redirect=0),
    maxsize=10,
)


class MinioClient:
    """MinIO客户端封装，提供上传、下载和预签名URL功能。"""

    def __init__(self):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
            http_client=_FAST_FAIL_HTTP,
        )
        self.bucket = settings.minio_bucket
        self._bucket_ensured = False

    def _ensure_bucket(self):
        """确保存储桶存在，不存在则创建（懒加载，第一次使用时调用）。"""
        if self._bucket_ensured:
            return
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"MinIO bucket '{self.bucket}' created")
            else:
                logger.debug(f"MinIO bucket '{self.bucket}' already exists")
            self._bucket_ensured = True
        except S3Error as e:
            logger.error(f"Failed to ensure MinIO bucket: {e}")
            raise

    def upload_file(
        self,
        object_name: str,
        file_data: BinaryIO | bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> dict:
        """
        上传文件到MinIO。

        Args:
            object_name: 对象路径（如 "reports/2024/report_123.html"）
            file_data: 文件数据（文件对象或字节）
            content_type: MIME类型
            metadata: 自定义元数据

        Returns:
            上传结果，包含 etag, version_id
        """
        self._ensure_bucket()  # 懒加载
        try:
            if isinstance(file_data, bytes):
                file_data = io.BytesIO(file_data)
                length = len(file_data.getvalue())
            else:
                # 获取文件大小
                file_data.seek(0, 2)  # 移到末尾
                length = file_data.tell()
                file_data.seek(0)  # 重置到开头

            result = self.client.put_object(
                bucket_name=self.bucket,
                object_name=object_name,
                data=file_data,
                length=length,
                content_type=content_type,
                metadata=metadata,
            )
            logger.info(f"Uploaded file to MinIO: {object_name} (etag={result.etag})")
            return {
                "object_name": object_name,
                "etag": result.etag,
                "version_id": result.version_id,
                "bucket": self.bucket,
            }
        except S3Error as e:
            logger.error(f"Failed to upload file to MinIO: {object_name}, error: {e}")
            raise

    def download_file(self, object_name: str) -> bytes:
        """
        从MinIO下载文件。

        Args:
            object_name: 对象路径

        Returns:
            文件字节内容
        """
        self._ensure_bucket()  # 懒加载
        try:
            response = self.client.get_object(self.bucket, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            logger.info(f"Downloaded file from MinIO: {object_name}")
            return data
        except S3Error as e:
            logger.error(f"Failed to download file from MinIO: {object_name}, error: {e}")
            raise

    def get_presigned_url(
        self, object_name: str, expires: timedelta = timedelta(days=7)
    ) -> str:
        """
        生成预签名下载URL（有效期默认7天）。

        Args:
            object_name: 对象路径
            expires: 过期时间

        Returns:
            预签名URL
        """
        self._ensure_bucket()  # 懒加载
        try:
            url = self.client.presigned_get_object(
                bucket_name=self.bucket,
                object_name=object_name,
                expires=expires,
            )
            logger.debug(f"Generated presigned URL for: {object_name}")
            return url
        except S3Error as e:
            logger.error(f"Failed to generate presigned URL: {object_name}, error: {e}")
            raise

    def delete_file(self, object_name: str):
        """
        删除MinIO中的文件。

        Args:
            object_name: 对象路径
        """
        self._ensure_bucket()  # 懒加载
        try:
            self.client.remove_object(self.bucket, object_name)
            logger.info(f"Deleted file from MinIO: {object_name}")
        except S3Error as e:
            logger.error(f"Failed to delete file from MinIO: {object_name}, error: {e}")
            raise

    def file_exists(self, object_name: str) -> bool:
        """
        检查文件是否存在。

        Args:
            object_name: 对象路径

        Returns:
            是否存在
        """
        self._ensure_bucket()  # 懒加载
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error as e:
            if e.code == "NoSuchKey":
                return False
            logger.error(f"Failed to check file existence: {object_name}, error: {e}")
            raise


# 全局单例
_minio_client: MinioClient | None = None


def get_minio_client() -> MinioClient:
    """获取MinIO客户端单例。"""
    global _minio_client
    if _minio_client is None:
        _minio_client = MinioClient()
    return _minio_client
