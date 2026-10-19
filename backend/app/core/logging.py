"""
结构化日志配置
"""
import logging
import sys
import json
from datetime import datetime
from typing import Any, Dict
from contextvars import ContextVar

from .config import settings


# 上下文变量，用于存储请求ID等
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")
project_id_var: ContextVar[str] = ContextVar("project_id", default="")


class StructuredFormatter(logging.Formatter):
    """结构化JSON日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "service": settings.app_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 添加上下文信息
        if request_id := request_id_var.get():
            log_data["request_id"] = request_id
        if user_id := user_id_var.get():
            log_data["user_id"] = user_id
        if project_id := project_id_var.get():
            log_data["project_id"] = project_id

        # 添加异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # 添加额外字段
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            log_data.update(extra)

        return json.dumps(log_data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """文本格式化器（开发环境使用）"""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname
        message = record.getMessage()

        log_line = f"[{timestamp}] {level:8s} {message}"

        # 添加上下文
        context_parts = []
        if request_id := request_id_var.get():
            context_parts.append(f"req={request_id}")
        if user_id := user_id_var.get():
            context_parts.append(f"user={user_id}")
        if project_id := project_id_var.get():
            context_parts.append(f"project={project_id}")

        if context_parts:
            log_line += f" [{', '.join(context_parts)}]"

        # 添加异常信息
        if record.exc_info:
            log_line += "\n" + self.formatException(record.exc_info)

        return log_line


def setup_logging():
    """配置日志"""
    # 设置日志级别
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # 创建handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    # 设置格式化器
    if settings.log_format == "json":
        formatter = StructuredFormatter()
    else:
        formatter = TextFormatter()

    handler.setFormatter(formatter)

    # 配置根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # 降低第三方库日志级别
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("arq").setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器"""
    return logging.getLogger(name)
