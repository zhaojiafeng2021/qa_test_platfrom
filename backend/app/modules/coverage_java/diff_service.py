"""增量覆盖率计算服务

基于 git diff merge-base 识别变更行,与 JaCoCo 行覆盖数据对比,输出:
- 变更代码中可执行行的覆盖率
- 按文件的变更行与覆盖状态映射
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_SRC_PREFIX_RE = re.compile(r"^(?:.*/)?src/main/java/")


def _git(repo_path: Path, *args: str, timeout: int = 300) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        timeout=timeout,
    ).stdout


class DiffCoverageService:
    """增量覆盖率服务"""

    @staticmethod
    def get_changed_lines(
        repo_path: Path,
        base_branch: str,
        head_ref: str = "HEAD",
    ) -> tuple[str, dict[str, set[int]]]:
        """计算 merge-base(origin/base_branch, head_ref)..head_ref 的新增/修改行

        采集时是 `git clone --depth N --branch X` 的浅克隆，本地没有 base 分支，
        这里先 fetch base 分支；找不到 merge-base 时逐步加深历史再重试。

        Returns:
            (merge_base_sha, {repo 相对路径: {新文件中的行号}})

        Raises:
            subprocess.CalledProcessError: git 命令失败
        """
        base_ref = f"refs/remotes/origin/{base_branch}"
        _git(repo_path, "fetch", "--depth", "200", "origin",
             f"+refs/heads/{base_branch}:{base_ref}", timeout=600)

        merge_base = DiffCoverageService._find_merge_base(repo_path, base_ref, head_ref)
        diff_output = _git(
            repo_path, "diff", "-U0", "--no-color", "--no-ext-diff",
            "--diff-filter=ACMR", f"{merge_base}..{head_ref}",
        )
        return merge_base, DiffCoverageService._parse_diff_output(diff_output)

    @staticmethod
    def _find_merge_base(repo_path: Path, base_ref: str, head_ref: str) -> str:
        for deepen in (None, "500", "unshallow"):
            if deepen == "unshallow":
                is_shallow = _git(repo_path, "rev-parse", "--is-shallow-repository").strip() == "true"
                if not is_shallow:
                    break
                _git(repo_path, "fetch", "--unshallow", "origin", timeout=1200)
            elif deepen:
                _git(repo_path, "fetch", f"--deepen={deepen}", "origin", timeout=600)
            try:
                return _git(repo_path, "merge-base", base_ref, head_ref).strip()
            except subprocess.CalledProcessError:
                logger.info(f"[diff_coverage] merge-base not found (deepen={deepen}), retrying")
        # 最后一次直接抛出，让上层拿到 stderr
        return _git(repo_path, "merge-base", base_ref, head_ref).strip()

    @staticmethod
    def _parse_diff_output(diff_text: str) -> dict[str, set[int]]:
        """解析 `git diff -U0` 输出，提取每个文件新版本中的新增/修改行号

        -U0 下 hunk 内只有 '+' / '-' 行（以及 '\\ No newline' 标记），
        行号只随 '+' 行递增。
        """
        file_changes: dict[str, set[int]] = {}
        current_file: Optional[str] = None
        current_line_no = 0
        in_hunk = False

        for line in diff_text.splitlines():
            if line.startswith("diff --git "):
                current_file = None
                in_hunk = False
                continue
            if not in_hunk and line.startswith("+++ "):
                path = line[4:]
                current_file = path[2:] if path.startswith("b/") else None
                if current_file is not None:
                    file_changes.setdefault(current_file, set())
                continue
            m = _HUNK_RE.match(line)
            if m:
                current_line_no = int(m.group(1))
                in_hunk = True
                continue
            if in_hunk and current_file is not None and line.startswith("+"):
                file_changes[current_file].add(current_line_no)
                current_line_no += 1

        return {f: lines for f, lines in file_changes.items() if lines}

    @staticmethod
    def calculate_diff_coverage(
        changed_lines: dict[str, set[int]],
        line_coverage: dict[str, dict],
    ) -> dict:
        """计算增量覆盖率

        分母只统计 JaCoCo 认为可执行的变更行；注释、空行等记为 not_executable。
        partial（部分分支未覆盖）计入已覆盖。

        Returns:
            DiffCoverageResponse 结构（不含 base/head 元信息）
        """
        files_result: dict[str, dict] = {}
        total_exec = 0
        total_covered = 0

        for file_path, changed_set in changed_lines.items():
            coverage_key = DiffCoverageService._normalize_path(file_path)
            file_coverage = line_coverage.get(coverage_key)
            if not file_coverage:
                # 非 Java 源码 / 测试代码 / 不属于本服务
                continue

            line_map = {item["line_no"]: item for item in file_coverage.get("lines", [])}
            details = []
            file_exec = 0
            file_covered = 0
            for line_no in sorted(changed_set):
                info = line_map.get(line_no)
                status = info["status"] if info else "not_executable"
                if status == "unknown":
                    status = "not_executable"
                if status != "not_executable":
                    file_exec += 1
                    if status in ("covered", "partial"):
                        file_covered += 1
                details.append({"line_no": line_no, "status": status})

            if file_exec == 0:
                # 只改了注释/空行，不影响增量覆盖率
                continue

            files_result[coverage_key] = {
                "changed_lines_total": file_exec,
                "changed_lines_covered": file_covered,
                "line_rate": round(file_covered * 100.0 / file_exec, 2),
                "changed_lines": details,
            }
            total_exec += file_exec
            total_covered += file_covered

        return {
            "line_rate": round(total_covered * 100.0 / total_exec, 2) if total_exec else 0.0,
            "lines_total": total_exec,
            "lines_covered": total_covered,
            "files": files_result,
        }

    @staticmethod
    def _normalize_path(git_path: str) -> str:
        """git 路径 → JaCoCo key

        - src/main/java/com/example/Foo.java               → com/example/Foo.java
        - order-service/src/main/java/com/example/Order.java → com/example/Order.java
        """
        return _SRC_PREFIX_RE.sub("", git_path)
