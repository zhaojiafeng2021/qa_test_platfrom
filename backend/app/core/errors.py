"""
统一错误码和异常定义
错误码格式: 4/5 + 01-99 + 1001-9999
- 401xxxx: 认证错误
- 403xxxx: 权限错误
- 404xxxx: 资源不存在
- 409xxxx: 并发冲突
- 422xxxx: 参数验证错误
- 429xxxx: 速率限制
- 500xxxx: 服务器错误
- 510xxxx: 执行引擎错误
"""
from typing import Any, Dict, Optional, List
from fastapi import HTTPException, status


class ErrorCode:
    """错误码常量"""

    # 成功
    SUCCESS = 0

    # 认证错误 401xxxx
    UNAUTHORIZED = 4010001
    TOKEN_EXPIRED = 4010002
    TOKEN_INVALID = 4010003
    TOKEN_MISSING = 4010004

    # 权限错误 403xxxx
    PERMISSION_DENIED = 4030001
    PROJECT_ACCESS_DENIED = 4030002
    RESOURCE_ACCESS_DENIED = 4030003

    # 资源错误 404xxxx
    RESOURCE_NOT_FOUND = 4040001
    PROJECT_NOT_FOUND = 4040002
    API_NOT_FOUND = 4040003
    CASE_NOT_FOUND = 4040004
    PLAN_NOT_FOUND = 4040005
    EXECUTION_NOT_FOUND = 4040006

    # 并发冲突 409xxxx
    REVISION_CONFLICT = 4090001
    DUPLICATE_RESOURCE = 4090002

    # 参数错误 422xxxx
    VALIDATION_ERROR = 4220001
    INVALID_PARAMETER = 4220002
    MISSING_PARAMETER = 4220003

    # 速率限制 429xxxx
    RATE_LIMIT_EXCEEDED = 4290001

    # 服务器错误 500xxxx
    INTERNAL_ERROR = 5000001
    DATABASE_ERROR = 5000002
    REDIS_ERROR = 5000003
    MINIO_ERROR = 5000004

    # 执行引擎错误 510xxxx
    EXECUTION_ERROR = 5100001
    COMPILATION_ERROR = 5100002
    ASSERTION_FAILED = 5100003
    VARIABLE_NOT_FOUND = 5100004
    TIMEOUT_ERROR = 5100005
    HTTP_REQUEST_ERROR = 5100006


class AppException(Exception):
    """应用异常基类"""

    def __init__(
        self,
        code: int,
        message: str,
        details: Optional[Any] = None,
        http_status: int = status.HTTP_400_BAD_REQUEST
    ):
        self.code = code
        self.message = message
        self.details = details
        self.http_status = http_status
        super().__init__(message)


class AuthenticationError(AppException):
    """认证错误"""

    def __init__(self, message: str = "认证失败", code: int = ErrorCode.UNAUTHORIZED):
        super().__init__(
            code=code,
            message=message,
            http_status=status.HTTP_401_UNAUTHORIZED
        )


class PermissionDeniedError(AppException):
    """权限错误"""

    def __init__(self, message: str = "权限不足", code: int = ErrorCode.PERMISSION_DENIED):
        super().__init__(
            code=code,
            message=message,
            http_status=status.HTTP_403_FORBIDDEN
        )


class ResourceNotFoundError(AppException):
    """资源不存在错误"""

    def __init__(self, message: str = "资源不存在", code: int = ErrorCode.RESOURCE_NOT_FOUND):
        super().__init__(
            code=code,
            message=message,
            http_status=status.HTTP_404_NOT_FOUND
        )


class RevisionConflictError(AppException):
    """版本冲突错误"""

    def __init__(self, message: str = "版本冲突，请刷新后重试"):
        super().__init__(
            code=ErrorCode.REVISION_CONFLICT,
            message=message,
            http_status=status.HTTP_409_CONFLICT
        )


class ValidationError(AppException):
    """参数验证错误"""

    def __init__(self, message: str = "参数验证失败", details: Optional[List[Dict]] = None):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            details=details,
            http_status=status.HTTP_422_UNPROCESSABLE_ENTITY
        )


class RateLimitExceededError(AppException):
    """速率限制错误"""

    def __init__(self, message: str = "请求过于频繁，请稍后重试", retry_after: Optional[int] = None):
        super().__init__(
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            message=message,
            details={"retry_after": retry_after} if retry_after is not None else None,
            http_status=status.HTTP_429_TOO_MANY_REQUESTS,
        )


class ExecutionError(AppException):
    """执行引擎错误"""

    def __init__(self, message: str = "执行失败", code: int = ErrorCode.EXECUTION_ERROR):
        super().__init__(
            code=code,
            message=message,
            http_status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def error_response(
    code: int,
    message: str,
    details: Optional[Any] = None,
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """构建统一错误响应"""
    response = {
        "code": code,
        "message": message,
    }

    if details is not None:
        response["details"] = details

    if request_id:
        response["request_id"] = request_id

    return response


def success_response(
    data: Any = None,
    message: str = "ok",
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """构建统一成功响应"""
    response = {
        "code": ErrorCode.SUCCESS,
        "message": message,
        "data": data
    }

    if request_id:
        response["request_id"] = request_id

    return response
