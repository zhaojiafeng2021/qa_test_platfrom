import subprocess
from pathlib import Path

from app.modules.coverage_java.diff_service import DiffCoverageService

JAVA_PATH = "order-service/src/main/java/com/example/Order.java"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout


def _write(repo: Path, rel: str, lines: list[str]) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_parse_diff_output():
    diff = (
        "diff --git a/src/main/java/A.java b/src/main/java/A.java\n"
        "--- a/src/main/java/A.java\n"
        "+++ b/src/main/java/A.java\n"
        "@@ -3 +3,2 @@\n"
        "-old\n"
        "+new1\n"
        "+new2\n"
        "@@ -10,0 +12 @@ ctx\n"
        "+added\n"
        "diff --git a/B.java b/B.java\n"
        "--- a/B.java\n"
        "+++ b/B.java\n"
        "@@ -5 +4,0 @@\n"
        "-deleted only\n"
    )
    assert DiffCoverageService._parse_diff_output(diff) == {"src/main/java/A.java": {3, 4, 12}}


def test_calculate_diff_coverage():
    changed = {
        JAVA_PATH: {1, 2, 3, 4},
        "README.md": {1},
    }
    line_cov = {
        "com/example/Order.java": {"lines": [
            {"line_no": 2, "status": "covered"},
            {"line_no": 3, "status": "partial"},
            {"line_no": 4, "status": "missed"},
        ]},
    }
    r = DiffCoverageService.calculate_diff_coverage(changed, line_cov)
    assert r["lines_total"] == 3
    assert r["lines_covered"] == 2
    assert r["line_rate"] == 66.67
    f = r["files"]["com/example/Order.java"]
    assert [l["status"] for l in f["changed_lines"]] == ["not_executable", "covered", "partial", "missed"]


def test_get_changed_lines_from_shallow_clone(tmp_path: Path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-b", "main")
    _write(origin, JAVA_PATH, ["a", "b", "c"])
    _git(origin, "add", "-A")
    _git(origin, "commit", "-m", "base")
    base_sha = _git(origin, "rev-parse", "HEAD").strip()

    _git(origin, "checkout", "-b", "feature")
    _write(origin, JAVA_PATH, ["a", "B", "c", "d"])
    _git(origin, "commit", "-am", "f1")
    _write(origin, JAVA_PATH, ["a", "B", "c", "d", "e"])
    _git(origin, "commit", "-am", "f2")

    # main 继续前进，不应影响 diff（merge-base 语义）
    _git(origin, "checkout", "main")
    _write(origin, "other.txt", ["x"])
    _git(origin, "add", "-A")
    _git(origin, "commit", "-m", "main moves")

    # 模拟采集时的浅克隆
    clone = tmp_path / "repo"
    _git(tmp_path, "clone", "--depth", "1", "--branch", "feature",
         origin.as_uri(), str(clone))

    merge_base, changed = DiffCoverageService.get_changed_lines(clone, "main")
    assert merge_base == base_sha
    assert changed == {JAVA_PATH: {2, 4, 5}}
