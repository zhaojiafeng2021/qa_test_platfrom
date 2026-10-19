"""上传文件安全校验（WP-11 安全基线）。

对上传的 UploadFile 做统一校验：
- 扩展名白名单
- 文件大小上限（settings.max_upload_bytes）

读取内容后返回 bytes，供调用方继续解析（保持既有 json.loads 逻辑不变）。
校验失败抛 ValidationError（统一 4220001）。
"""
from __future__ import annotations

import os

from fastapi import UploadFile

from app.core.config import settings
from app.core.errors import ValidationError


def _check_extension(filename: str | None, allowed_exts: tuple[str, ...]) -> None:
    name = filename or ""
    ext = os.path.splitext(name)[1].lower()
    if ext not in allowed_exts:
        raise ValidationError(
            message=f"不支持的文件类型 '{ext or '未知'}'，仅允许 {', '.join(allowed_exts)}"
        )


async def read_upload_checked(
    file: UploadFile,
    allowed_exts: tuple[str, ...],
    max_bytes: int | None = None,
) -> bytes:
    """校验扩展名与大小后读取上传内容。

    Args:
        file: FastAPI UploadFile
        allowed_exts: 允许的小写扩展名，如 (".json", ".xmind")
        max_bytes: 大小上限；None 时用 settings.max_upload_bytes

    Returns:
        文件二进制内容
    """
    limit = max_bytes if max_bytes is not None else settings.max_upload_bytes

    _check_extension(file.filename, allowed_exts)

    # 若 starlette 已知大小，先做预检（快速拒绝，避免读入超大文件）
    size_hint = getattr(file, "size", None)
    if size_hint is not None and size_hint > limit:
        raise ValidationError(
            message=f"文件过大（{size_hint} 字节），上限 {limit} 字节"
        )

    content = await file.read()
    if len(content) > limit:
        raise ValidationError(
            message=f"文件过大（{len(content)} 字节），上限 {limit} 字节"
        )
    return content
