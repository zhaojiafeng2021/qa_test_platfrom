"""P2：commit 列表 / 归属校验 / clone 后 checkout 指定 commit

用本地临时 git 仓库做远端，不依赖网络。
"""
import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.errors import AppException
from app.modules.code_repository.service import CodeRepositoryService, _parse_commit_line
from app.modules.coverage_java.build_service import BuildError, JavaBuildService

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def remote(tmp_path):
    """main: c1 → c2；feature: c1 → c3"""
    repo = tmp_path / "remote"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "a.txt").write_text("v1")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "first")
    c1 = _git(repo, "rev-parse", "HEAD")
    (repo / "a.txt").write_text("v2")
    _git(repo, "commit", "-am", "second")
    c2 = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "feature", c1)
    (repo / "b.txt").write_text("f")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feature work")
    c3 = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "main")
    return SimpleNamespace(path=repo, url=repo.as_uri(), c1=c1, c2=c2, c3=c3)


@pytest.fixture
def repo_svc(tmp_path):
    svc = CodeRepositoryService(db=None)
    svc.cache_root = tmp_path / "_repo_cache"
    return svc


def _repo(remote):
    return SimpleNamespace(id=1, repo_url=remote.url)


def test_parse_commit_line():
    line = "\x1f".join(["a" * 40, "aaaaaaa", "Alice", "2026-10-22T10:00:00+08:00", "fix: x\x1fy"])
    c = _parse_commit_line(line)
    assert c["sha"] == "a" * 40
    assert c["short_sha"] == "aaaaaaa"
    assert c["author"] == "Alice"
    assert c["subject"] == "fix: x"


def test_list_commits_newest_first(remote, repo_svc):
    commits = asyncio.run(repo_svc.list_commits(_repo(remote), "main"))
    assert [c["sha"] for c in commits] == [remote.c2, remote.c1]
    assert commits[0]["subject"] == "second"
    assert commits[0]["short_sha"] == remote.c2[: len(commits[0]["short_sha"])]


def test_list_commits_limit(remote, repo_svc):
    commits = asyncio.run(repo_svc.list_commits(_repo(remote), "main", limit=1))
    assert [c["sha"] for c in commits] == [remote.c2]


def test_resolve_commit_default_head(remote, repo_svc):
    assert asyncio.run(repo_svc.resolve_commit(_repo(remote), "main", None)) == remote.c2


def test_resolve_commit_ancestor_short_sha(remote, repo_svc):
    sha = asyncio.run(repo_svc.resolve_commit(_repo(remote), "main", remote.c1[:10]))
    assert sha == remote.c1


def test_resolve_commit_other_branch_rejected(remote, repo_svc):
    with pytest.raises(AppException) as e:
        asyncio.run(repo_svc.resolve_commit(_repo(remote), "main", remote.c3))
    assert e.value.http_status == 400
    assert "不属于分支" in e.value.message


def test_resolve_commit_unknown_rejected(remote, repo_svc):
    with pytest.raises(AppException) as e:
        asyncio.run(repo_svc.resolve_commit(_repo(remote), "main", "deadbeef" * 5))
    assert "不存在" in e.value.message


@pytest.mark.parametrize("bad", ["--all", "HEAD~1", "abc", "g" * 40])
def test_resolve_commit_bad_format_rejected(remote, repo_svc, bad):
    with pytest.raises(AppException):
        asyncio.run(repo_svc.resolve_commit(_repo(remote), "main", bad))


def test_clone_checkout_specified_commit(remote, tmp_path):
    repo_dir, _, head = asyncio.run(
        JavaBuildService().clone_repo(remote.url, "main", tmp_path / "ws", commit_sha=remote.c1)
    )
    assert head == remote.c1
    assert (repo_dir / "a.txt").read_text() == "v1"


def test_clone_without_commit_uses_branch_head(remote, tmp_path):
    repo_dir, _, head = asyncio.run(JavaBuildService().clone_repo(remote.url, "main", tmp_path / "ws"))
    assert head == remote.c2
    assert (repo_dir / "a.txt").read_text() == "v2"


def test_clone_checkout_missing_commit_fails(remote, tmp_path):
    with pytest.raises(BuildError) as e:
        asyncio.run(
            JavaBuildService().clone_repo(remote.url, "main", tmp_path / "ws", commit_sha="deadbeef" * 5)
        )
    assert e.value.stage == "clone"
