"""覆盖率累积账本编排

每次单服务采集写完 report 后调用 LedgerService.merge()：
1. 取 task+service 的 active 账本；没有或分支不同 → 开新一轮
2. git 判断方向，确定目标 commit T
3. exec 层：jacococli merge(账本 merged exec, 本次 exec)，用 T 的 class 出报告
4. 方法层：按方法索引把"另一侧"行数据迁移到 T（排除 class 不一致的类）
5. 行合并（assemble_lines）
6. 重算汇总，写 ledger / ledger_files / event

纯函数部分（索引构建、方向判断、行组装）不依赖 DB，便于单测。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import subprocess
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppException, ErrorCode
from app.core.logging import get_logger
from app.db.models.coverage_java import (
    CoverageLedger,
    CoverageLedgerEvent,
    CoverageLedgerFile,
    CoverageTask,
    JavaCoverageReport,
)
from app.modules.coverage_java.build_service import JavaBuildService, _run_cmd
from app.modules.coverage_java.diff_service import DiffCoverageService
from app.modules.coverage_java.java_method_parser import JavaMethodParser, MethodUnit
from app.modules.coverage_java.ledger_merger import LedgerMerger
from app.modules.coverage_java.ledger_migrator import LedgerMigrator, LineCoverage, MigrationStats
from app.modules.coverage_java.report_service import JaCoCoReportService

logger = get_logger(__name__)

# {file_path: {line_no: LineCoverage}}
LineMap = dict[str, dict[int, LineCoverage]]
# {file_path: [MethodUnit]}
MethodIndex = dict[str, list[MethodUnit]]

_COVERED = ("covered", "partial")
FILE_UNIT = "<file>"


class LedgerError(Exception):
    """账本合并失败（不影响单次报告）"""


# ──────────────────────────────────────────────
# 行数据转换
# ──────────────────────────────────────────────

def lines_from_parsed(files: dict, source: Optional[str]) -> LineMap:
    """xml_parser 的 files 结构 → LineMap；已覆盖行标记来源，unknown 行丢弃"""
    result: LineMap = {}
    for path, info in files.items():
        lines: dict[int, LineCoverage] = {}
        for ln in info.get("lines", []):
            status = ln["status"]
            if status == "unknown":
                continue
            lines[ln["line_no"]] = LineCoverage(
                line_no=ln["line_no"],
                ci=ln["covered_instructions"], mi=ln["missed_instructions"],
                cb=ln["covered_branches"], mb=ln["missed_branches"],
                status=status,
                sources=[source] if source and status in _COVERED else [],
            )
        result[path] = lines
    return result


def lines_to_json(lines: dict[int, LineCoverage]) -> dict:
    return {
        str(ln): {"ci": c.ci, "mi": c.mi, "cb": c.cb, "mb": c.mb, "status": c.status, "sources": list(c.sources)}
        for ln, c in sorted(lines.items())
    }


def lines_from_json(data: dict) -> dict[int, LineCoverage]:
    return {
        int(ln): LineCoverage(
            line_no=int(ln), ci=v.get("ci", 0), mi=v.get("mi", 0), cb=v.get("cb", 0), mb=v.get("mb", 0),
            status=v.get("status", "missed"), sources=list(v.get("sources") or []),
        )
        for ln, v in (data or {}).items()
    }


# ──────────────────────────────────────────────
# 方法索引
# ──────────────────────────────────────────────

def _path_to_fqn(file_path: str) -> str:
    return file_path[:-5].replace("/", ".") if file_path.endswith(".java") else file_path.replace("/", ".")


def _file_unit(file_path: str, source: str) -> MethodUnit:
    """解析失败时降级为文件级单元：整个文件指纹相同才继承"""
    lines = source.splitlines()
    fp = hashlib.sha1("\n".join(l.strip() for l in lines).encode("utf-8")).hexdigest()
    return MethodUnit(key=f"{_path_to_fqn(file_path)}#{FILE_UNIT}", fingerprint=fp, start=1, end=max(len(lines), 1))


def _read_source(path: Path) -> Optional[str]:
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def build_method_index(sourcefiles_dir: Path, file_paths: list[str]) -> MethodIndex:
    """解析报告涉及的源码文件，生成方法索引"""
    parser = JavaMethodParser()
    index: MethodIndex = {}
    for rel in file_paths:
        src_path = sourcefiles_dir / rel
        if not src_path.is_file():
            continue
        source = _read_source(src_path)
        units = parser.parse_file(source, rel)
        index[rel] = units if units is not None else [_file_unit(rel, source)]
    return index


def index_to_json(index: MethodIndex, commit: Optional[str]) -> dict:
    files = {}
    for path, units in index.items():
        items = []
        for u in units:
            item = {"key": u.key, "fp": u.fingerprint}
            if u.lines is not None:
                item["lines"] = u.lines
            else:
                item["start"], item["end"] = u.start, u.end
            items.append(item)
        files[path] = items
    return {"commit": commit, "files": files}


def index_from_json(data: dict) -> MethodIndex:
    return {
        path: [
            MethodUnit(key=i["key"], fingerprint=i["fp"], start=i.get("start"), end=i.get("end"), lines=i.get("lines"))
            for i in items
        ]
        for path, items in (data or {}).get("files", {}).items()
    }


def migrate_lines(
    old_index: MethodIndex,
    new_index: MethodIndex,
    old_lines: LineMap,
    exclude_classes: set[str],
    keep_sources: bool = True,
) -> tuple[LineMap, MigrationStats]:
    """按文件逐个迁移，汇总统计"""
    migrator = LedgerMigrator()
    total = MigrationStats()
    result: LineMap = {}
    for path in set(old_index) | set(new_index):
        migrated, stats = migrator.migrate(
            old_index.get(path, []), new_index.get(path, []), old_lines.get(path, {}),
            exclude_classes, keep_sources=keep_sources,
        )
        if migrated:
            result[path] = migrated
        total.methods_kept += stats.methods_kept
        total.methods_reset += stats.methods_reset
        total.methods_removed += stats.methods_removed
        total.methods_added += stats.methods_added
        total.reset_methods.extend(stats.reset_methods)
    total.reset_methods.sort()
    return result, total


# ──────────────────────────────────────────────
# 行组装
# ──────────────────────────────────────────────

@dataclass
class Side:
    """参与合并的一方（旧账本 / 本次结果），行号已对齐到目标 commit T

    carried: 对齐到 T 的行数据，带原始 sources
    exact:   该方 exec 单独对 T 的 class 出的报告。None 表示该方本就在 T 上（carried 即精确）；
             否则只有 exact 中已覆盖的行算实测，其余已覆盖行是方法迁移来的近似值（inherited）
    """
    carried: LineMap
    exact: Optional[LineMap] = None

    def is_exact(self, path: str, ln: int) -> bool:
        if self.exact is None:
            return True
        ex = self.exact.get(path, {}).get(ln)
        return bool(ex and ex.status in _COVERED)


def assemble_lines(exec_lines: LineMap, sides: list[Side]) -> LineMap:
    """合并 exec 报告与各方行数据，得到账本行数据

    - 行集合以 exec_lines（merged exec 对 T 的 class 出的报告）为准，落在非可执行行上的迁移数据丢弃
    - exec 已覆盖的行：计数取 exec（精确），sources = 各方在该行实测命中的来源并集
    - 某方在该行有覆盖但不是实测（字节码变了、方法源码没变）：按 inherited 并入（LedgerMerger 规则）
    """
    merger = LedgerMerger()
    result: LineMap = {}
    for path, exec_file in exec_lines.items():
        attributed: dict[int, LineCoverage] = {}
        approx: dict[int, LineCoverage] = {}
        for ln, cov in exec_file.items():
            srcs: set[str] = set()
            for s in sides:
                carried = s.carried.get(path, {}).get(ln)
                if not carried or carried.status not in _COVERED:
                    continue
                if cov.status in _COVERED and s.is_exact(path, ln):
                    srcs.update(x for x in carried.sources if x != "inherited")
                    continue
                inherited = replace(carried, line_no=ln, sources=["inherited"])
                prev = approx.get(ln)
                approx[ln] = inherited if prev is None else merger.merge_file({ln: prev}, {ln: inherited})[ln]
            if cov.status in _COVERED and not srcs:
                # exec 实测命中但无法归属（如来源被排除的类）：保守标记为 inherited
                srcs.add("inherited")
            attributed[ln] = replace(cov, sources=sorted(srcs))

        merged = merger.merge_file(attributed, approx)
        for ln, cov in merged.items():
            base = attributed[ln]
            # 实测已覆盖且继承数据没有带来额外覆盖：不标 inherited
            if base.status in _COVERED and cov.ci <= base.ci and cov.cb <= base.cb:
                merged[ln] = replace(cov, sources=base.sources)
        result[path] = merged
    return result


def summarize(lines: LineMap) -> dict:
    s = LedgerMerger().compute_ledger_summary(lines)
    return {
        "line_rate": round(s.line_rate * 100, 2),
        "branch_rate": round(s.branch_rate * 100, 2),
        "lines_covered": s.lines_covered,
        "lines_total": s.lines_total,
        "branches_covered": s.branches_covered,
        "branches_total": s.branches_total,
        "source_stats": {
            "unittest_lines": s.unittest_lines,
            "runtime_lines": s.runtime_lines,
            "inherited_lines": s.inherited_lines,
        },
    }


# ──────────────────────────────────────────────
# 查询用纯函数
# ──────────────────────────────────────────────

def lines_to_items(lines: dict[int, LineCoverage]) -> list[dict]:
    """账本行 → 接口行结构（字段名与单次报告的 line_coverage 一致，多一个 sources）"""
    return [
        {
            "line_no": ln,
            "covered_instructions": c.ci, "missed_instructions": c.mi,
            "covered_branches": c.cb, "missed_branches": c.mb,
            "status": c.status, "sources": list(c.sources),
        }
        for ln, c in sorted(lines.items())
    ]


def ledger_diff_coverage(changed_lines: dict[str, set[int]], lines: LineMap) -> dict:
    """基于账本行数据算增量覆盖率；每个变更行附带 sources，另统计仅靠继承覆盖的行数"""
    line_coverage = {
        path: {"lines": [{"line_no": ln, "status": c.status} for ln, c in file_lines.items()]}
        for path, file_lines in lines.items()
    }
    result = DiffCoverageService.calculate_diff_coverage(changed_lines, line_coverage)
    inherited = 0
    for path, f in result["files"].items():
        file_lines = lines.get(path, {})
        file_inherited = 0
        for item in f["changed_lines"]:
            cov = file_lines.get(item["line_no"])
            item["sources"] = list(cov.sources) if cov else []
            if item["status"] in _COVERED and item["sources"] == ["inherited"]:
                file_inherited += 1
        f["changed_lines_inherited"] = file_inherited
        inherited += file_inherited
    result["lines_inherited"] = inherited
    return result


def _unit_lines(u: MethodUnit) -> list[int]:
    if u.lines is not None:
        return list(u.lines)
    return list(range(u.start, u.end + 1)) if u.start and u.end else []


def regression_methods(resets: list[tuple[str, str]], index: MethodIndex, lines: LineMap) -> list[dict]:
    """需回归方法：本轮因代码变更被清零的方法，标出是否已被重新覆盖

    resets: 按时间先后的 (method_key, 清零时的 to_commit)；同一方法多次清零取最后一次。
    head 中已不存在的方法（后来被删除/重命名）不再列出。
    """
    reset_at = dict(resets)
    result = []
    for path, units in index.items():
        file_lines = lines.get(path, {})
        for u in units:
            if u.key not in reset_at:
                continue
            exe = [file_lines[ln] for ln in _unit_lines(u) if ln in file_lines]
            covered = sum(1 for c in exe if c.status in _COVERED)
            result.append({
                "key": u.key, "file_path": path,
                "start": u.start if u.lines is None else min(u.lines, default=None),
                "end": u.end if u.lines is None else max(u.lines, default=None),
                "reset_at_commit": reset_at[u.key],
                "executable_lines": len(exe), "covered_lines": covered,
                "recovered": covered > 0,
            })
    result.sort(key=lambda m: (m["recovered"], m["file_path"], m["start"] or 0))
    return result


# ──────────────────────────────────────────────
# 方向判断
# ──────────────────────────────────────────────

async def _git(repo_dir: Path, *args: str) -> tuple[int, str]:
    return await _run_cmd(["git", *args], cwd=repo_dir, timeout=60, log_prefix="[ledger-git]")


async def _commit_time(repo_dir: Path, sha: str) -> int:
    code, out = await _git(repo_dir, "show", "-s", "--format=%ct", sha)
    try:
        return int(out.strip().splitlines()[-1]) if code == 0 else 0
    except (ValueError, IndexError):
        return 0


async def determine_direction(repo_dir: Path, head: str, new: str) -> tuple[str, bool]:
    """返回 (direction, target_is_new)

    same / forward（head 是 new 的祖先）/ backward（new 是 head 的祖先）/
    diverged（互不为祖先，以 commit 时间较新的一方为目标；head 在本地仓库找不到时以 new 为目标）
    """
    if head == new:
        return "same", True
    code, _ = await _git(repo_dir, "merge-base", "--is-ancestor", head, new)
    if code == 0:
        return "forward", True
    code, _ = await _git(repo_dir, "merge-base", "--is-ancestor", new, head)
    if code == 0:
        return "backward", False
    head_t, new_t = await _commit_time(repo_dir, head), await _commit_time(repo_dir, new)
    return "diverged", not (head_t > new_t)


# ──────────────────────────────────────────────
# 编排
# ──────────────────────────────────────────────

@dataclass
class CollectedResult:
    """一次单服务采集在 worker 工作区里的产物"""
    report: JavaCoverageReport
    source: str
    commit: str
    exec_file: Path
    classfiles_dir: Path
    sourcefiles_dir: Path
    repo_dir: Path
    parsed_files: dict
    mismatch_classes: list[str]
    work_dir: Path


def _zip_dir(root: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in root.rglob("*.class"):
            zf.write(f, arcname=str(f.relative_to(root)).replace("\\", "/"))
    return buf.getvalue()


def _unzip(data: bytes, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest)
    return dest


class LedgerService:
    """账本读写与合并编排"""

    def __init__(self, db: AsyncSession, report_service: Optional[JaCoCoReportService] = None):
        self.db = db
        self.report_service = report_service or JaCoCoReportService()

    @property
    def minio(self):
        return self.report_service.minio

    # ─── 查询 ───

    async def get_active(self, task_id: int, service_name: str) -> Optional[CoverageLedger]:
        result = await self.db.execute(
            select(CoverageLedger).where(
                CoverageLedger.task_id == task_id,
                CoverageLedger.service_name == service_name,
                CoverageLedger.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_latest(self, task_id: int, service_name: str) -> Optional[CoverageLedger]:
        result = await self.db.execute(
            select(CoverageLedger)
            .where(CoverageLedger.task_id == task_id, CoverageLedger.service_name == service_name)
            .order_by(CoverageLedger.round_no.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def load_lines(self, ledger_id: int) -> LineMap:
        result = await self.db.execute(
            select(CoverageLedgerFile).where(CoverageLedgerFile.ledger_id == ledger_id)
        )
        return {f.file_path: lines_from_json(f.lines_json) for f in result.scalars().all()}

    async def list_rounds(self, task_id: int) -> list[CoverageLedger]:
        result = await self.db.execute(
            select(CoverageLedger)
            .where(CoverageLedger.task_id == task_id)
            .order_by(CoverageLedger.service_name, CoverageLedger.round_no.desc())
        )
        return list(result.scalars().all())

    async def list_events(self, ledger_id: int, limit: int = 100) -> list[CoverageLedgerEvent]:
        """合并历史，新的在前"""
        result = await self.db.execute(
            select(CoverageLedgerEvent)
            .where(CoverageLedgerEvent.ledger_id == ledger_id)
            .order_by(CoverageLedgerEvent.created_at.desc(), CoverageLedgerEvent.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_file_summaries(self, ledger_id: int) -> list[dict]:
        result = await self.db.execute(
            select(
                CoverageLedgerFile.file_path, CoverageLedgerFile.lines_covered, CoverageLedgerFile.lines_total,
            )
            .where(CoverageLedgerFile.ledger_id == ledger_id)
            .order_by(CoverageLedgerFile.file_path)
        )
        return [
            {
                "file_path": path,
                "lines_covered": covered,
                "lines_total": total,
                "line_rate": round(covered * 100.0 / total, 2) if total else 0.0,
            }
            for path, covered, total in result.all()
        ]

    async def load_file(self, ledger_id: int, file_path: str) -> Optional[dict[int, LineCoverage]]:
        result = await self.db.execute(
            select(CoverageLedgerFile.lines_json).where(
                CoverageLedgerFile.ledger_id == ledger_id, CoverageLedgerFile.file_path == file_path,
            )
        )
        row = result.first()
        return lines_from_json(row[0]) if row else None

    async def regression_methods(self, ledger: CoverageLedger) -> list[dict]:
        """本轮所有"代码变更导致清零"的方法（只看 head 前进的事件），按 head 的方法索引核对是否已重新覆盖"""
        if not ledger.method_index_path:
            return []
        result = await self.db.execute(
            select(CoverageLedgerEvent.reset_methods_json, CoverageLedgerEvent.to_commit)
            .where(
                CoverageLedgerEvent.ledger_id == ledger.id,
                CoverageLedgerEvent.direction.in_(("forward", "diverged")),
                CoverageLedgerEvent.from_commit != CoverageLedgerEvent.to_commit,
            )
            .order_by(CoverageLedgerEvent.created_at, CoverageLedgerEvent.id)
        )
        resets = [(key, to_commit) for keys, to_commit in result.all() for key in (keys or [])]
        if not resets:
            return []
        index = index_from_json(self._download_json(ledger.method_index_path))
        return regression_methods(resets, index, await self.load_lines(ledger.id))

    async def changed_lines(self, task: CoverageTask, ledger: CoverageLedger) -> tuple[str, dict[str, set[int]]]:
        """merge-base(base, head)..head 的变更行

        优先用代码源的 bare 缓存仓库（不依赖采集 workspace 是否保留）；
        未关联代码源时退回到推进 head 的那次采集的 workspace。
        """
        base = task.diff_base_branch
        if task.repo_id:
            from app.modules.code_repository.service import CodeRepositoryService
            repo_svc = CodeRepositoryService(self.db)
            repo = await repo_svc.get(task.project_id, task.repo_id)
            return await repo_svc.changed_lines(repo, base, ledger.head_commit)

        repo_path = await self._head_workspace(ledger)
        try:
            return await asyncio.to_thread(
                DiffCoverageService.get_changed_lines, repo_path, base, ledger.head_commit,
            )
        except subprocess.CalledProcessError as e:
            raise AppException(
                message=f"git 命令执行失败: {(e.stderr or '').strip() or e}",
                code=ErrorCode.INTERNAL_ERROR, http_status=500,
            )
        except subprocess.TimeoutExpired as e:
            raise AppException(message=f"git 命令超时: {e.cmd}", code=ErrorCode.INTERNAL_ERROR, http_status=500)

    async def _head_workspace(self, ledger: CoverageLedger) -> Path:
        result = await self.db.execute(
            select(JavaCoverageReport)
            .join(CoverageLedgerEvent, CoverageLedgerEvent.report_id == JavaCoverageReport.id)
            .where(CoverageLedgerEvent.ledger_id == ledger.id, JavaCoverageReport.commit_sha == ledger.head_commit)
            .order_by(CoverageLedgerEvent.created_at.desc(), CoverageLedgerEvent.id.desc())
        )
        build = JavaBuildService()
        for report in result.scalars().all():
            repo_path = build._service_workspace(report.task_id, report.run_id, report.service_name) / "repo"
            if (repo_path / ".git").exists():
                return repo_path
        raise AppException(
            message="任务未关联代码源，且 head commit 对应的采集 workspace 已被清理，请重新触发采集",
            code=ErrorCode.RESOURCE_NOT_FOUND, http_status=404,
        )

    async def close_round(self, task_id: int, service_name: str) -> bool:
        """手动结束当前轮次；下一次采集以 reason=manual 开新一轮"""
        result = await self.db.execute(
            update(CoverageLedger)
            .where(
                CoverageLedger.task_id == task_id,
                CoverageLedger.service_name == service_name,
                CoverageLedger.is_active == True,  # noqa: E712
            )
            .values(is_active=False)
        )
        await self.db.flush()
        return (result.rowcount or 0) > 0

    # ─── 合并 ───

    async def merge(self, r: CollectedResult, branch: str) -> CoverageLedger:
        """把一次采集结果并入账本；调用方负责 commit / 回滚"""
        report = r.report
        new_index = build_method_index(r.sourcefiles_dir, list(r.parsed_files.keys()))
        index_obj = f"coverage/{report.task_id}/{report.run_id}/{report.service_name}/method-index.json"
        self._upload_json(index_obj, index_to_json(new_index, r.commit))
        await self.db.execute(
            update(JavaCoverageReport).where(JavaCoverageReport.id == report.id).values(method_index_path=index_obj)
        )

        ledger = await self.get_active(report.task_id, report.service_name)
        if ledger is not None and ledger.branch != branch:
            ledger.is_active = False
            await self.db.flush()
            ledger = None

        if ledger is None:
            return await self._start_round(r, branch, new_index, index_obj)
        return await self._merge_into(ledger, r, new_index, index_obj)

    async def _start_round(
        self, r: CollectedResult, branch: str, new_index: MethodIndex, index_obj: str,
    ) -> CoverageLedger:
        report = r.report
        prev = await self.get_latest(report.task_id, report.service_name)
        if prev is None:
            round_no, direction, reason = 1, "init", None
        else:
            round_no = prev.round_no + 1
            direction = "new_round"
            reason = "branch_switch" if prev.branch != branch else "manual"

        ledger = CoverageLedger(
            task_id=report.task_id, service_name=report.service_name, branch=branch,
            round_no=round_no, is_active=True, head_commit=r.commit,
        )
        self.db.add(ledger)
        await self.db.flush()

        lines = lines_from_parsed(r.parsed_files, r.source)
        self._store_head_artifacts(ledger, r, index_obj)
        ledger.merged_exec_path = self._upload_exec(ledger.id, report.id, r.exec_file)
        await self._write(ledger, lines, r, direction, reason, None, MigrationStats())
        logger.info(f"[ledger] {report.service_name} round {round_no} started ({direction}, reason={reason})")
        return ledger

    async def _merge_into(
        self, ledger: CoverageLedger, r: CollectedResult, new_index: MethodIndex, index_obj: str,
    ) -> CoverageLedger:
        report = r.report
        exclude = set(r.mismatch_classes)
        from_commit = ledger.head_commit
        direction, target_is_new = await determine_direction(r.repo_dir, ledger.head_commit, r.commit)

        work = r.work_dir / "ledger"
        work.mkdir(parents=True, exist_ok=True)
        old_exec = work / "ledger-old.exec"
        old_exec.write_bytes(self.minio.download_file(ledger.merged_exec_path))
        merged_exec = await self.report_service.merge_exec([old_exec, r.exec_file], work / "merged.exec")

        old_lines = await self.load_lines(ledger.id)
        old_index = index_from_json(self._download_json(ledger.method_index_path)) if ledger.method_index_path else {}
        new_lines = lines_from_parsed(r.parsed_files, r.source)

        if target_is_new:
            # 目标 = 本次 commit：旧账本迁移过来
            classes, sources = r.classfiles_dir, r.sourcefiles_dir
            exec_lines = await self._report_lines(merged_exec, classes, sources, work / "r-merged")
            if direction == "same":
                old_side, stats = Side(carried=old_lines), MigrationStats()
            else:
                carried, stats = migrate_lines(old_index, new_index, old_lines, exclude)
                exact = await self._report_lines(old_exec, classes, sources, work / "r-old")
                old_side = Side(carried=carried, exact=exact)
            sides = [old_side, Side(carried=new_lines)]
        else:
            # 目标 = 账本 head（backward / diverged 且账本更新）：本次结果迁移到 head
            classes = _unzip(self.minio.download_file(ledger.classfiles_path), work / "head-classes")
            sources = work / "head-sources"
            if ledger.source_snapshot_path:
                _unzip(self.minio.download_file(ledger.source_snapshot_path), sources)
            sources.mkdir(parents=True, exist_ok=True)
            exec_lines = await self._report_lines(merged_exec, classes, sources, work / "r-merged")
            carried, stats = migrate_lines(new_index, old_index, new_lines, exclude)
            exact = await self._report_lines(r.exec_file, classes, sources, work / "r-new")
            sides = [Side(carried=old_lines), Side(carried=carried, exact=exact)]

        lines = assemble_lines(exec_lines, sides)
        if target_is_new:
            self._store_head_artifacts(ledger, r, index_obj)
        ledger.merged_exec_path = self._upload_exec(ledger.id, report.id, merged_exec)
        await self._write(ledger, lines, r, direction, None, from_commit, stats)
        logger.info(
            f"[ledger] {report.service_name} merged report {report.id}: {direction}, "
            f"{from_commit[:8]} → {ledger.head_commit[:8]}, reset={stats.methods_reset}"
        )
        return ledger

    # ─── 内部 ───

    async def _report_lines(self, exec_file: Path, classes: Path, sources: Path, out: Path) -> LineMap:
        xml, _ = await self.report_service.generate_report([exec_file], classes, sources, out)
        return lines_from_parsed(self.report_service.parse_xml(xml)["files"], None)

    def _store_head_artifacts(self, ledger: CoverageLedger, r: CollectedResult, index_obj: str) -> None:
        """账本 head 前进到本次 commit：记录其方法索引、class 包、源码快照"""
        report = r.report
        cls_obj = f"coverage/{report.task_id}/{report.run_id}/{report.service_name}/classes.zip"
        self.minio.upload_file(cls_obj, _zip_dir(r.classfiles_dir), content_type="application/zip")
        ledger.head_commit = r.commit
        ledger.method_index_path = index_obj
        ledger.classfiles_path = cls_obj
        ledger.source_snapshot_path = report.source_snapshot_path

    def _upload_exec(self, ledger_id: int, report_id: int, exec_file: Path) -> str:
        # 每次合并写新对象，DB 回滚时旧路径仍有效
        obj = f"coverage/ledgers/{ledger_id}/{report_id}/merged.exec"
        self.minio.upload_file(obj, exec_file.read_bytes(), content_type="application/octet-stream")
        return obj

    def _upload_json(self, obj: str, data: dict) -> None:
        self.minio.upload_file(obj, json.dumps(data, ensure_ascii=False).encode("utf-8"), content_type="application/json")

    def _download_json(self, obj: str) -> dict:
        return json.loads(self.minio.download_file(obj).decode("utf-8"))

    async def _write(
        self,
        ledger: CoverageLedger,
        lines: LineMap,
        r: CollectedResult,
        direction: str,
        reason: Optional[str],
        from_commit: Optional[str],
        stats: MigrationStats,
    ) -> None:
        merger = LedgerMerger()
        rate_before = ledger.line_rate
        await self.db.execute(delete(CoverageLedgerFile).where(CoverageLedgerFile.ledger_id == ledger.id))
        for path, file_lines in lines.items():
            covered, total, _ = merger.compute_file_summary(file_lines)
            self.db.add(CoverageLedgerFile(
                ledger_id=ledger.id, file_path=path, lines_json=lines_to_json(file_lines),
                lines_covered=covered, lines_total=total,
            ))

        for k, v in summarize(lines).items():
            setattr(ledger, k, v)

        self.db.add(CoverageLedgerEvent(
            ledger_id=ledger.id,
            report_id=r.report.id,
            source=r.source,
            from_commit=from_commit,
            to_commit=ledger.head_commit,
            direction=direction,
            reason=reason,
            mismatch_classes_json=r.mismatch_classes or None,
            methods_kept=stats.methods_kept,
            methods_reset=stats.methods_reset,
            methods_removed=stats.methods_removed,
            methods_added=stats.methods_added,
            reset_methods_json=stats.reset_methods or None,
            line_rate_before=rate_before,
            line_rate_after=ledger.line_rate,
        ))
        await self.db.flush()
