"""
代码用例扫描器

基于 Python ast 静态解析 code_testcases 目录下的所有 .py 文件，
提取 @case 装饰器的元信息。不执行被扫描的代码，无 import 副作用。
"""
import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 扫描时跳过的目录
SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", ".pytest_cache"}
# 扫描时跳过的文件
SKIP_FILES = {"__init__.py", "conftest.py"}

DECORATOR_NAME = "case"


@dataclass
class ScannedCase:
    """扫描到的单个用例"""
    module: str
    name: str
    level: str
    description: str
    file_path: str          # 相对 code_testcases 根目录，统一用 /
    function_name: str
    code_snippet: str
    line_number: int
    project: str = ""       # 所属项目名称，空字符串表示全局共享


@dataclass
class ScanReport:
    """一次扫描的结果汇总"""
    cases: list[ScannedCase] = field(default_factory=list)
    scanned_files: int = 0
    errors: list[str] = field(default_factory=list)


def _literal(node: ast.AST) -> Optional[str]:
    """取字面量字符串；非字面量（变量、拼接等）返回 None"""
    try:
        val = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None
    return str(val) if isinstance(val, (str, int, float)) else None


def _decorator_name(node: ast.AST) -> Optional[str]:
    """取装饰器名，兼容 @case(...) / @xxx.case(...)"""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _parse_case_decorator(dec: ast.Call) -> Optional[dict]:
    """
    解析 @case(...) 的参数，返回 dict；module/name 缺失则返回 None。
    同时支持位置参数（module, name, level, description, project 顺序）和关键字参数。
    """
    positional = ["module", "name", "level", "description", "project"]
    parsed: dict[str, str] = {}

    for idx, arg in enumerate(dec.args):
        if idx < len(positional):
            v = _literal(arg)
            if v is not None:
                parsed[positional[idx]] = v

    for kw in dec.keywords:
        if kw.arg in positional:
            v = _literal(kw.value)
            if v is not None:
                parsed[kw.arg] = v

    if not parsed.get("module") or not parsed.get("name"):
        return None

    parsed.setdefault("level", "P1")
    parsed.setdefault("description", "")
    parsed.setdefault("project", "")
    return parsed


def _parse_file(abs_path: Path, root: Path) -> tuple[list[ScannedCase], Optional[str]]:
    """解析单个 .py 文件，返回 (用例列表, 错误信息)"""
    try:
        # utf-8-sig：自动去掉文件开头的 BOM (U+FEFF)，兼容 bic_code_testcase 远程仓库
        # 的 UTF-8 with BOM 编码文件；无 BOM 文件行为与 utf-8 完全一致
        source = abs_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            # Windows 中文环境部分 .py 可能用 gbk 保存，兼容一下
            source = abs_path.read_text(encoding="gbk")
        except Exception as e:
            return [], f"{abs_path.name}: 编码无法识别 ({e})"
    except OSError as e:
        return [], f"{abs_path.name}: 读取失败 ({e})"

    try:
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError as e:
        return [], f"{abs_path.name}: 语法错误 第{e.lineno}行 {e.msg}"

    source_lines = source.splitlines()
    rel_path = abs_path.relative_to(root).as_posix()
    found: list[ScannedCase] = []

    # 只扫顶层与类内的函数定义（含 async def）
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if _decorator_name(dec) != DECORATOR_NAME:
                continue
            meta = _parse_case_decorator(dec)
            if meta is None:
                found_at = f"{rel_path}:{node.lineno}"
                logger.warning("跳过 @case（module/name 缺失或非字面量）: %s", found_at)
                continue

            start = min(d.lineno for d in node.decorator_list) - 1
            end = getattr(node, "end_lineno", node.lineno)
            snippet = "\n".join(source_lines[start:end])

            found.append(ScannedCase(
                module=meta["module"],
                name=meta["name"],
                level=meta["level"],
                description=meta["description"],
                project=meta["project"],
                file_path=rel_path,
                function_name=node.name,
                code_snippet=snippet,
                line_number=node.lineno,
            ))
            break  # 一个函数只取一个 @case

    return found, None


def scan_code_testcases(root_dir: str | Path) -> ScanReport:
    """
    递归扫描目录下所有 .py 文件中的 @case 用例

    Args:
        root_dir: code_testcases 目录绝对路径

    Returns:
        ScanReport: 含用例列表、扫描文件数、解析错误
    """
    root = Path(root_dir)
    report = ScanReport()

    if not root.exists() or not root.is_dir():
        report.errors.append(f"用例目录不存在: {root}")
        logger.warning("代码用例目录不存在: %s", root)
        return report

    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue

        report.scanned_files += 1
        cases, err = _parse_file(path, root)
        if err:
            report.errors.append(err)
            logger.warning("解析失败: %s", err)
            continue
        report.cases.extend(cases)

    logger.info("扫描完成: %d 个文件, %d 个用例, %d 个错误",
                report.scanned_files, len(report.cases), len(report.errors))
    return report
