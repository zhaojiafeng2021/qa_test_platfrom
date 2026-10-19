"""
代码用例装饰器

复用 django 项目 common/decorators.py 的设计，新增必传的 module 参数，
用于标记用例的模块归属层级。
"""
from functools import wraps
from typing import Callable

# 模块层级分隔符
MODULE_SEPARATOR = "-"

VALID_LEVELS = ("P0", "P1", "P2", "P3")


def case(module: str, name: str, level: str = "P1", description: str = "", project: str = ""):
    """
    代码用例装饰器

    Args:
        module: 用例模块归属层级（必传），用 "-" 分层，
                如 "支付中心-支付渠道-支付宝" 表示三级：
                支付中心(父级) -> 支付渠道(子级) -> 支付宝(最小层级)
        name: 用例名称
        level: 用例等级 P0/P1/P2/P3
            - P0: 核心功能，必须通过
            - P1: 重要功能
            - P2: 一般功能
            - P3: 低优先级功能
        description: 用例描述
        project: 所属项目名称（可选），与平台项目名称匹配；
                 不传则用例在所有项目下均可见（全局共享）

    Example:
        @case(module="支付中心-支付渠道-支付宝", name="支付宝下单成功",
              level="P0", description="验证支付宝渠道正常下单", project="支付平台")
        def test_alipay_order():
            assert True
    """
    if not module or not str(module).strip():
        raise ValueError("@case 的 module 参数必传，用于标记用例模块归属层级")
    if not name or not str(name).strip():
        raise ValueError("@case 的 name 参数必传")

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        wrapper._case_module = module
        wrapper._case_name = name
        wrapper._case_level = level
        wrapper._case_description = description
        wrapper._case_project = project
        wrapper._is_test_case = True
        return wrapper

    return decorator


def parse_module_path(module: str) -> list[str]:
    """
    将模块层级字符串拆成各级名称列表

    "支付中心-支付渠道-支付宝" -> ["支付中心", "支付渠道", "支付宝"]
    空白段会被丢弃，两端空格会被去掉。
    """
    if not module:
        return []
    return [seg.strip() for seg in str(module).split(MODULE_SEPARATOR) if seg.strip()]


def get_case_info(func: Callable) -> dict:
    """获取用例元信息"""
    return {
        "module": getattr(func, "_case_module", ""),
        "name": getattr(func, "_case_name", func.__name__),
        "level": getattr(func, "_case_level", "P1"),
        "description": getattr(func, "_case_description", ""),
        "project": getattr(func, "_case_project", ""),
    }


def is_test_case(func: Callable) -> bool:
    """判断函数是否为代码用例"""
    return getattr(func, "_is_test_case", False)
