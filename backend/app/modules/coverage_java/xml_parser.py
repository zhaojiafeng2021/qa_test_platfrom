"""JaCoCo XML 报告解析器

输入：jacococli 生成的 XML 报告（含 <counter> 聚合 + <line> 行级数据）
输出：{
    "overall": {line_rate, branch_rate, lines_covered, ...},
    "files":   {file_path: {package, class_name, line_rate, lines: [{line_no, ci, mi, cb, mb, status}]}},
}
"""
from __future__ import annotations

from typing import Any
from xml.etree import ElementTree as ET

from app.core.logging import get_logger

logger = get_logger(__name__)


def _to_int(v: str | None, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _line_status(ci: int, mi: int, cb: int, mb: int) -> str:
    """根据 covered/missed instructions + branches 推断行覆盖状态"""
    if ci == 0 and mi == 0:
        return "unknown"
    if mi == 0 and mb == 0:
        return "covered"
    if ci == 0:
        return "missed"
    return "partial"


def parse_jacoco_xml(xml_content: bytes | str) -> dict[str, Any]:
    """解析 JaCoCo XML 报告

    Args:
        xml_content: XML 字符串或字节

    Returns:
        dict 结构见模块 docstring
    """
    if isinstance(xml_content, bytes):
        xml_content = xml_content.decode("utf-8")

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.error(f"Failed to parse JaCoCo XML: {e}")
        raise ValueError(f"Invalid JaCoCo XML: {e}") from e

    # ─── 1. 聚合 counter ───
    overall: dict[str, Any] = {}
    for counter in root.findall("counter"):
        ctype = counter.attrib.get("type", "")
        covered = _to_int(counter.attrib.get("covered"))
        missed = _to_int(counter.attrib.get("missed"))
        total = covered + missed
        rate = round(covered * 100.0 / total, 2) if total > 0 else 0.0

        if ctype == "LINE":
            overall["lines_covered"] = covered
            overall["lines_total"] = total
            overall["line_rate"] = rate
        elif ctype == "BRANCH":
            overall["branches_covered"] = covered
            overall["branches_total"] = total
            overall["branch_rate"] = rate
        elif ctype == "INSTRUCTION":
            overall["instructions_covered"] = covered
            overall["instructions_total"] = total
        elif ctype == "METHOD":
            overall["methods_covered"] = covered
            overall["methods_total"] = total
        elif ctype == "CLASS":
            overall["classes_covered"] = covered
            overall["classes_total"] = total

    # 兜底：如果 XML 里没有 BRANCH counter，默认给 0
    overall.setdefault("line_rate", 0.0)
    overall.setdefault("branch_rate", 0.0)
    overall.setdefault("lines_covered", 0)
    overall.setdefault("lines_total", 0)
    overall.setdefault("branches_covered", 0)
    overall.setdefault("branches_total", 0)

    # ─── 2. 按 package → sourcefile 提取行级数据 ───
    files: dict[str, dict[str, Any]] = {}
    for package in root.findall("package"):
        package_name = package.attrib.get("name", "").replace("/", ".")

        for sourcefile in package.findall("sourcefile"):
            file_name = sourcefile.attrib.get("name", "")
            package_dir = package.attrib.get("name", "")
            file_path = f"{package_dir}/{file_name}" if package_dir else file_name

            lines: list[dict[str, Any]] = []
            for line in sourcefile.findall("line"):
                line_no = _to_int(line.attrib.get("nr"))
                ci = _to_int(line.attrib.get("ci"))
                mi = _to_int(line.attrib.get("mi"))
                cb = _to_int(line.attrib.get("cb"))
                mb = _to_int(line.attrib.get("mb"))
                lines.append({
                    "line_no": line_no,
                    "covered_instructions": ci,
                    "missed_instructions": mi,
                    "covered_branches": cb,
                    "missed_branches": mb,
                    "status": _line_status(ci, mi, cb, mb),
                })

            # 按 sourcefile 的 counter 算行覆盖率
            file_line_covered = 0
            file_line_total = 0
            for counter in sourcefile.findall("counter"):
                if counter.attrib.get("type") == "LINE":
                    file_line_covered = _to_int(counter.attrib.get("covered"))
                    file_line_total = file_line_covered + _to_int(counter.attrib.get("missed"))
                    break

            files[file_path] = {
                "package": package_name,
                "file_name": file_name,
                "lines_total": file_line_total,
                "lines_covered": file_line_covered,
                "line_rate": round(file_line_covered * 100.0 / file_line_total, 2) if file_line_total > 0 else 0.0,
                "lines": lines,
            }

    return {
        "overall": overall,
        "files": files,
    }
