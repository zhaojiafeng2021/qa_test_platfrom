"""P2：jacococli merge / 按指定 class 出报告 / class 不一致警告

解析部分是纯函数；exec 层用例需要 java、javac 和 jacoco jar，缺失时跳过。
"""
import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.modules.coverage_java.report_service import JaCoCoReportService, parse_mismatch_classes


# ─── 警告解析 ───

def test_parse_mismatch_classes():
    log = (
        "[INFO] Loading execution data file a.exec.\n"
        "[WARN] Execution data for class com/example/Foo does not match.\n"
        "[WARN] Execution data for class com/example/Outer$Inner does not match.\n"
        "[WARN] Execution data for class com/example/Outer$1 does not match.\n"
        "[WARN] Execution data for class com/example/Outer$Inner$2 does not match.\n"
        "[WARN] Execution data for class com/example/Foo does not match.\n"
        "[INFO] Analyzing 3 classes.\n"
    )
    assert parse_mismatch_classes(log) == [
        "com.example.Foo",
        "com.example.Outer",
        "com.example.Outer.Inner",
    ]


def test_parse_mismatch_classes_lambda_and_default_package():
    log = (
        "Execution data for class Main does not match.\n"
        "Execution data for class com/x/Svc$$Lambda$14 does not match.\n"
    )
    assert parse_mismatch_classes(log) == ["Main", "com.x.Svc"]


def test_parse_mismatch_classes_none():
    assert parse_mismatch_classes("") == []
    assert parse_mismatch_classes("[INFO] Analyzing 3 classes.") == []


# ─── exec 层集成 ───

_AGENT = Path(settings.jacoco_agent_jar_path) if settings.jacoco_agent_jar_path else None
_CLI = Path(settings.jacoco_cli_jar_path) if settings.jacoco_cli_jar_path else None
jacoco = pytest.mark.skipif(
    not (shutil.which("java") and shutil.which("javac") and _AGENT and _AGENT.is_file() and _CLI and _CLI.is_file()),
    reason="java/javac/jacoco jars not available",
)

CALC_V1 = """package com.example;
public class Calc {
    public static int sign(int x) {
        if (x > 0) {
            return 1;
        }
        return -1;
    }
    public static void main(String[] args) {
        System.out.println(sign(Integer.parseInt(args[0])));
    }
}
"""

# 方法 sign 不变，只在 main 里多一行：字节码变化 → class ID 不同
CALC_V2 = CALC_V1.replace(
    "System.out.println(sign(Integer.parseInt(args[0])));",
    "int v = Integer.parseInt(args[0]);\n        System.out.println(sign(v));",
)


def _compile(src_root: Path, out: Path, source: str) -> None:
    pkg = src_root / "com" / "example"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "Calc.java").write_text(source, encoding="utf-8")
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(["javac", "-g", "-d", str(out), str(pkg / "Calc.java")], check=True)


def _run(classes: Path, exec_file: Path, arg: str) -> None:
    subprocess.run(
        ["java", f"-javaagent:{_AGENT}=destfile={exec_file}", "-cp", str(classes), "com.example.Calc", arg],
        check=True, capture_output=True,
    )


@pytest.fixture
def v1(tmp_path):
    src, classes = tmp_path / "src1", tmp_path / "classes1"
    _compile(src, classes, CALC_V1)
    pos, neg = tmp_path / "pos.exec", tmp_path / "neg.exec"
    _run(classes, pos, "5")
    _run(classes, neg, "-5")
    return src, classes, pos, neg


def _sign_counters(svc: JaCoCoReportService, xml: Path) -> dict:
    lines = svc.parse_xml(xml)["files"]["com/example/Calc.java"]["lines"]
    return {
        ln["line_no"]: {"cb": ln["covered_branches"], "mb": ln["missed_branches"], "status": ln["status"]}
        for ln in lines
    }


@jacoco
def test_merge_gives_exact_branch_union(v1, tmp_path):
    src, classes, pos, neg = v1
    svc = JaCoCoReportService()

    xml_pos, _ = asyncio.run(svc.generate_report([pos], classes, src, tmp_path / "r_pos"))
    line4 = _sign_counters(svc, xml_pos)[4]
    assert (line4["cb"], line4["mb"]) == (1, 1)

    merged = asyncio.run(svc.merge_exec([pos, neg], tmp_path / "merged.exec"))
    xml, log = asyncio.run(svc.generate_report([merged], classes, src, tmp_path / "r_merged"))
    lines = _sign_counters(svc, xml)
    assert (lines[4]["cb"], lines[4]["mb"]) == (2, 0)
    assert lines[5]["status"] == "covered"
    assert lines[7]["status"] == "covered"
    assert parse_mismatch_classes(log) == []


@jacoco
def test_report_against_changed_class_warns(v1, tmp_path):
    _, _, pos, _ = v1
    src2, classes2 = tmp_path / "src2", tmp_path / "classes2"
    _compile(src2, classes2, CALC_V2)
    svc = JaCoCoReportService()

    xml, log = asyncio.run(svc.generate_report([pos], classes2, src2, tmp_path / "r_v2"))
    assert parse_mismatch_classes(log) == ["com.example.Calc"]
    # class ID 不一致时 JaCoCo 丢弃旧数据：全部 missed，交给方法迁移补齐
    assert all(v["status"] == "missed" for v in _sign_counters(svc, xml).values())


@jacoco
def test_generate_xml_html_returns_warnings(v1, tmp_path):
    src, classes, pos, _ = v1
    svc = JaCoCoReportService()
    xml, html_dir, mismatch = asyncio.run(svc.generate_xml_html(pos, classes, src, tmp_path / "r"))
    assert xml.is_file() and html_dir.is_dir()
    assert mismatch == []
