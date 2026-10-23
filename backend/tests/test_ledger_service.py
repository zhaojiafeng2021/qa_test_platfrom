"""P3：LedgerService

- 纯函数：行组装、方法索引、方向判断
- 端到端：临时 git 仓库 + javac + jacoco agent/cli + 内存 SQLite + 假 MinIO，
  走 init → same → forward → backward → 切分支开新一轮
"""
import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.db.models.coverage_java import (
    CoverageLedger,
    CoverageLedgerEvent,
    CoverageLedgerFile,
    JavaCoverageReport,
)
from app.modules.coverage_java.ledger_migrator import LineCoverage
from app.modules.coverage_java.java_method_parser import MethodUnit
from app.modules.coverage_java.ledger_service import (
    FILE_UNIT,
    CollectedResult,
    LedgerService,
    Side,
    assemble_lines,
    build_method_index,
    determine_direction,
    index_from_json,
    index_to_json,
    ledger_diff_coverage,
    lines_from_json,
    lines_to_items,
    lines_to_json,
    regression_methods,
)
from app.modules.coverage_java.report_service import JaCoCoReportService, parse_mismatch_classes

F = "com/example/Calc.java"


def _lc(ln, status, sources=(), ci=None, mi=0, cb=0, mb=0):
    ci = (1 if status != "missed" else 0) if ci is None else ci
    if status == "missed" and mi == 0:
        mi = 1
    return LineCoverage(line_no=ln, ci=ci, mi=mi, cb=cb, mb=mb, status=status, sources=list(sources))


# ─── 行组装 ───

def test_assemble_same_commit_sources_union():
    exec_lines = {F: {4: _lc(4, "covered", cb=2), 5: _lc(5, "covered"), 7: _lc(7, "covered")}}
    old = Side(carried={F: {4: _lc(4, "partial", ["unittest"], cb=1, mb=1), 5: _lc(5, "covered", ["unittest"])}})
    new = Side(carried={F: {4: _lc(4, "partial", ["runtime"], cb=1, mb=1), 7: _lc(7, "covered", ["runtime"])}})
    out = assemble_lines(exec_lines, [old, new])[F]
    assert out[4].sources == ["runtime", "unittest"] and (out[4].cb, out[4].mb) == (2, 0)
    assert out[5].sources == ["unittest"]
    assert out[7].sources == ["runtime"]


def test_assemble_bytecode_changed_inherits():
    """旧侧 exact 为空（class ID 变了）：exec missed 的行采用迁移数据，标 inherited"""
    exec_lines = {F: {4: _lc(4, "missed", mb=2), 5: _lc(5, "missed")}}
    old = Side(carried={F: {4: _lc(4, "covered", ["unittest"], cb=2), 5: _lc(5, "covered", ["unittest"])}}, exact={})
    new = Side(carried={F: {4: _lc(4, "missed", mb=2), 5: _lc(5, "missed")}})
    out = assemble_lines(exec_lines, [old, new])[F]
    assert out[4].status == "covered" and out[4].sources == ["inherited"] and out[4].cb == 2
    assert out[5].sources == ["inherited"]


def test_assemble_exact_hit_keeps_original_source():
    """旧侧在目标 class 上实测命中（class ID 未变）：保留原来源，不降级为 inherited"""
    exec_lines = {F: {5: _lc(5, "covered")}}
    old = Side(carried={F: {5: _lc(5, "covered", ["runtime"])}}, exact={F: {5: _lc(5, "covered")}})
    out = assemble_lines(exec_lines, [old])[F]
    assert out[5].sources == ["runtime"]


def test_assemble_drops_non_executable_and_reset_lines():
    exec_lines = {F: {5: _lc(5, "missed")}}
    old = Side(carried={F: {5: _lc(5, "missed"), 99: _lc(99, "covered", ["unittest"])}}, exact={})
    out = assemble_lines(exec_lines, [old])[F]
    assert set(out) == {5}
    assert out[5].status == "missed" and out[5].sources == []


def test_lines_json_roundtrip():
    lines = {4: _lc(4, "partial", ["unittest"], cb=1, mb=1)}
    back = lines_from_json(lines_to_json(lines))
    assert back[4].cb == 1 and back[4].sources == ["unittest"] and back[4].status == "partial"


# ─── 查询用纯函数 ───

def test_lines_to_items_keeps_sources():
    items = lines_to_items({5: _lc(5, "covered", ["inherited"]), 4: _lc(4, "partial", ["unittest"], cb=1, mb=1)})
    assert [i["line_no"] for i in items] == [4, 5]
    assert items[0]["covered_branches"] == 1 and items[0]["missed_branches"] == 1
    assert items[1]["sources"] == ["inherited"]


def test_ledger_diff_coverage_marks_sources():
    """删除行不在 head 中不计入；新增行未覆盖计入；继承覆盖单独统计"""
    lines = {F: {
        4: _lc(4, "covered", ["unittest"]),
        5: _lc(5, "covered", ["inherited"]),
        7: _lc(7, "missed"),
        8: _lc(8, "partial", ["runtime", "inherited"], cb=1, mb=1),
    }}
    changed = {"svc/src/main/java/" + F: {3, 4, 5, 7, 8}, "README.md": {1}}
    r = ledger_diff_coverage(changed, lines)
    assert (r["lines_total"], r["lines_covered"], r["lines_inherited"]) == (4, 3, 1)
    f = r["files"][F]
    assert f["changed_lines_inherited"] == 1
    by_line = {i["line_no"]: i for i in f["changed_lines"]}
    assert by_line[3] == {"line_no": 3, "status": "not_executable", "sources": []}
    assert by_line[5]["sources"] == ["inherited"]
    assert by_line[7]["status"] == "missed"


def test_regression_methods_recovered_and_dropped():
    index = {F: [
        MethodUnit(key="C#a()", fingerprint="x", start=3, end=5),
        MethodUnit(key="C#b()", fingerprint="y", start=7, end=9),
        MethodUnit(key="C#<init-fields>", fingerprint="z", lines=[2]),
    ]}
    lines = {F: {2: _lc(2, "missed"), 4: _lc(4, "covered", ["runtime"]), 8: _lc(8, "missed")}}
    resets = [("C#a()", "c1"), ("C#b()", "c1"), ("C#gone()", "c1"), ("C#b()", "c2"), ("C#<init-fields>", "c2")]
    out = regression_methods(resets, index, lines)
    assert [(m["key"], m["recovered"], m["reset_at_commit"]) for m in out] == [
        ("C#<init-fields>", False, "c2"),
        ("C#b()", False, "c2"),
        ("C#a()", True, "c1"),
    ]
    assert (out[1]["executable_lines"], out[1]["covered_lines"]) == (1, 0)
    assert (out[0]["start"], out[0]["end"]) == (2, 2)


# ─── 方法索引 ───

def test_method_index_roundtrip_and_file_fallback(tmp_path):
    pkg = tmp_path / "com" / "example"
    pkg.mkdir(parents=True)
    (pkg / "Calc.java").write_text(CALC_V1, encoding="utf-8")
    (pkg / "Broken.java").write_text("package com.example; public class Broken { void f( {", encoding="utf-8")
    index = build_method_index(tmp_path, [F, "com/example/Broken.java", "com/example/Missing.java"])
    assert "com/example/Missing.java" not in index
    assert [u.key for u in index["com/example/Broken.java"]] == [f"com.example.Broken#{FILE_UNIT}"]
    assert any(u.key == "com.example.Calc#sign(int)" for u in index[F])

    back = index_from_json(index_to_json(index, "abc"))
    assert [(u.key, u.fingerprint, u.start, u.end, u.lines) for u in back[F]] == \
        [(u.key, u.fingerprint, u.start, u.end, u.lines) for u in index[F]]


# ─── 方向判断 ───

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@needs_git
def test_determine_direction(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "a").write_text("1")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "1")
    c1 = _git(repo, "rev-parse", "HEAD")
    (repo / "a").write_text("2")
    _git(repo, "commit", "-am", "2")
    c2 = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "x", c1)
    (repo / "b").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "x", "--date", "2000-01-01T00:00:00")
    c3 = _git(repo, "rev-parse", "HEAD")

    run = lambda h, n: asyncio.run(determine_direction(repo, h, n))  # noqa: E731
    assert run(c1, c1) == ("same", True)
    assert run(c1, c2) == ("forward", True)
    assert run(c2, c1) == ("backward", False)
    direction, _ = run(c2, c3)
    assert direction == "diverged"
    assert run("0" * 40, c2) == ("diverged", True)


@needs_git
def test_code_repo_changed_lines_from_bare_cache(tmp_path):
    """增量 diff 走代码源 bare 缓存，不依赖采集 workspace"""
    from app.modules.code_repository.service import CodeRepositoryService

    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    (origin / "A.java").write_text("a\nb\nc\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "base")
    _git(origin, "checkout", "-b", "feature")
    (origin / "A.java").write_text("a\nB\nc\nd\n")
    (origin / "New.java").write_text("x\n")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "feat")
    head = _git(origin, "rev-parse", "HEAD")
    base = _git(origin, "rev-parse", "main")

    svc = CodeRepositoryService(db=None)
    svc.cache_root = tmp_path / "cache"
    repo = SimpleNamespace(id=987654, repo_url=str(origin))
    merge_base, changed = asyncio.run(svc.changed_lines(repo, "main", head))
    assert merge_base == base
    assert changed == {"A.java": {2, 4}, "New.java": {1}}


# ─── 端到端 ───

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
# sign 不变，main 改动 → class ID 变化，sign 的覆盖只能靠方法迁移继承
CALC_V2 = CALC_V1.replace(
    "System.out.println(sign(Integer.parseInt(args[0])));",
    "int v = Integer.parseInt(args[0]);\n        System.out.println(sign(v));",
)

_AGENT = Path(settings.jacoco_agent_jar_path) if settings.jacoco_agent_jar_path else None
_CLI = Path(settings.jacoco_cli_jar_path) if settings.jacoco_cli_jar_path else None
needs_jacoco = pytest.mark.skipif(
    not (shutil.which("git") and shutil.which("java") and shutil.which("javac")
         and _AGENT and _AGENT.is_file() and _CLI and _CLI.is_file()),
    reason="git/java/javac/jacoco jars not available",
)


class FakeMinio:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, object_name, file_data, content_type="application/octet-stream", metadata=None):
        self.objects[object_name] = file_data if isinstance(file_data, bytes) else file_data.read()
        return {"object_name": object_name}

    def download_file(self, object_name):
        return self.objects[object_name]


class Harness:
    def __init__(self, tmp: Path, session):
        self.tmp = tmp
        self.db = session
        self.report_service = JaCoCoReportService()
        self.report_service.minio = FakeMinio()
        self.ledgers = LedgerService(session, self.report_service)
        self.repo = tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-b", "main")
        self.step = 0

    def commit(self, source: str, msg: str) -> str:
        pkg = self.repo / "src" / "com" / "example"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "Calc.java").write_text(source, encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-m", msg)
        return _git(self.repo, "rev-parse", "HEAD")

    async def collect(self, commit: str, source: str, arg: str, branch: str = "main") -> CoverageLedger:
        self.step += 1
        _git(self.repo, "checkout", "-q", "--detach", commit)
        work = self.tmp / f"step{self.step}"
        classes, exec_file = work / "classes", work / "coverage.exec"
        src_dir = self.repo / "src"
        classes.mkdir(parents=True)
        subprocess.run(["javac", "-g", "-d", str(classes), str(src_dir / F)], check=True)
        subprocess.run(
            ["java", f"-javaagent:{_AGENT}=destfile={exec_file}", "-cp", str(classes), "com.example.Calc", arg],
            check=True, capture_output=True,
        )
        xml, log = await self.report_service.generate_report([exec_file], classes, src_dir, work / "report")
        parsed = self.report_service.parse_xml(xml)
        snapshot = self.report_service.upload_source_snapshot(1, self.step, "svc", src_dir, list(parsed["files"]))

        report = JavaCoverageReport(
            run_id=self.step, task_id=1, service_name="svc", commit_sha=commit, source=source,
            status="completed", source_snapshot_path=snapshot,
        )
        self.db.add(report)
        await self.db.flush()
        ledger = await self.ledgers.merge(
            CollectedResult(
                report=report, source=source, commit=commit, exec_file=exec_file,
                classfiles_dir=classes, sourcefiles_dir=src_dir, repo_dir=self.repo,
                parsed_files=parsed["files"], mismatch_classes=parse_mismatch_classes(log), work_dir=work,
            ),
            branch=branch,
        )
        await self.db.commit()
        return ledger

    async def lines(self, ledger: CoverageLedger) -> dict:
        return (await self.ledgers.load_lines(ledger.id))[F]

    async def last_event(self, ledger: CoverageLedger) -> CoverageLedgerEvent:
        res = await self.db.execute(
            select(CoverageLedgerEvent).where(CoverageLedgerEvent.ledger_id == ledger.id)
            .order_by(CoverageLedgerEvent.created_at.desc(), CoverageLedgerEvent.id.desc())
        )
        return res.scalars().first()


@needs_jacoco
def test_ledger_end_to_end(tmp_path):
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        tables = [t.__table__ for t in (JavaCoverageReport, CoverageLedger, CoverageLedgerFile, CoverageLedgerEvent)]
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        session = async_sessionmaker(engine, expire_on_commit=False)()
        h = Harness(tmp_path, session)
        c1 = h.commit(CALC_V1, "v1")
        c2 = h.commit(CALC_V2, "v2: only main changed")

        # 1. init：单测只走正分支
        led = await h.collect(c1, "unittest", "5")
        assert (led.round_no, led.head_commit, led.is_active) == (1, c1, True)
        assert (await h.last_event(led)).direction == "init"
        lines = await h.lines(led)
        assert lines[5].sources == ["unittest"] and lines[7].status == "missed"

        # 2. same：运行时走负分支，jacococli merge 后分支精确并集
        led = await h.collect(c1, "runtime", "-5")
        lines = await h.lines(led)
        assert (await h.last_event(led)).direction == "same"
        assert (lines[4].cb, lines[4].mb) == (2, 0)
        assert lines[5].sources == ["unittest"]
        assert lines[7].sources == ["runtime"]
        assert lines[10].sources == ["runtime", "unittest"]

        # 3. forward：c2 只改 main，单测只走正分支
        led = await h.collect(c2, "unittest", "5")
        ev = await h.last_event(led)
        assert (ev.direction, ev.from_commit, ev.to_commit) == ("forward", c1, c2)
        assert led.head_commit == c2
        assert ev.reset_methods_json == ["com.example.Calc#main(String[])"]
        assert ev.methods_kept >= 1
        lines = await h.lines(led)
        assert lines[5].sources == ["unittest"]          # 本次实测
        assert lines[7].status == "covered"              # sign 源码未变：继承运行时的负分支覆盖
        assert lines[7].sources == ["inherited"]
        assert (lines[4].cb, lines[4].mb) == (2, 0)
        assert lines[10].sources == ["unittest"]          # main 已改：只剩本次实测

        # 4. backward：旧环境晚到的 c1 数据，迁移到 head（c2），head 不变
        led = await h.collect(c1, "runtime", "-5")
        ev = await h.last_event(led)
        assert (ev.direction, ev.to_commit) == ("backward", c2)
        assert led.head_commit == c2
        lines = await h.lines(led)
        assert lines[7].status == "covered"

        # 5. 切换分支：旧轮次关闭只读，新一轮从本次结果开始
        old_id = led.id
        led = await h.collect(c2, "unittest", "5", branch="feature")
        ev = await h.last_event(led)
        assert (led.round_no, led.branch, ev.direction, ev.reason) == (2, "feature", "new_round", "branch_switch")
        old = await session.get(CoverageLedger, old_id)
        await session.refresh(old)
        assert old.is_active is False
        lines = await h.lines(led)
        assert lines[7].status == "missed"

        # 方法索引写回了 report
        rep = (await session.execute(select(JavaCoverageReport).order_by(JavaCoverageReport.run_id.desc()))).scalars().first()
        await session.refresh(rep)
        assert rep.method_index_path and rep.method_index_path in h.report_service.minio.objects

        # ─── P4 查询 ───
        old = await session.get(CoverageLedger, old_id)
        svc = h.ledgers
        # 需回归方法：forward 时 main 被清零，随后单测重新覆盖
        regs = await svc.regression_methods(old)
        assert [(m["key"], m["recovered"], m["reset_at_commit"]) for m in regs] == \
            [("com.example.Calc#main(String[])", True, c2)]
        # 新一轮没有 forward 事件
        assert await svc.regression_methods(led) == []

        files = await svc.list_file_summaries(old.id)
        assert [f["file_path"] for f in files] == [F] and files[0]["lines_total"] > 0
        assert (await svc.load_file(old.id, F))[7].sources == ["inherited"]
        assert await svc.load_file(old.id, "nope.java") is None

        events = await svc.list_events(old.id)
        assert [e.direction for e in events] == ["backward", "forward", "same", "init"]
        assert [l.round_no for l in await svc.list_rounds(1)] == [2, 1]

        # 手动开新一轮：下一次采集 reason=manual
        assert await svc.close_round(1, "svc") is True
        await session.commit()
        assert await svc.close_round(1, "svc") is False
        led = await h.collect(c2, "runtime", "-5", branch="feature")
        ev = await h.last_event(led)
        assert (led.round_no, ev.direction, ev.reason) == (3, "new_round", "manual")

        await session.close()
        await engine.dispose()

    asyncio.run(scenario())
