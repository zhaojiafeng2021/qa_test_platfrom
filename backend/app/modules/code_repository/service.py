"""代码源服务：CRUD + 远程分支列表 + 服务自动发现

分支：git ls-remote --heads（无需 clone）。
服务：维护一个 blob:none 的 bare 缓存仓库，fetch 后 git ls-tree 找 pom.xml / build.gradle。
"""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppException, ErrorCode
from app.core.logging import get_logger
from app.db.models.code_repository import CodeRepository
from app.modules.coverage_java.build_service import BuildError, _run_cmd

logger = get_logger(__name__)

BUILD_FILES = {"pom.xml": "maven", "build.gradle": "gradle", "build.gradle.kts": "gradle"}
_GIT_TIMEOUT = 120
_locks: dict[int, asyncio.Lock] = {}


_SHA_RE = re.compile(r"[0-9a-fA-F]{7,40}")


def _check_branch(branch: str) -> None:
    if not branch or branch.startswith("-"):
        raise _git_error("分支名不合法")


def _parse_commit_line(line: str) -> dict:
    sha, short_sha, author, committed_at, subject = (line.split("\x1f") + [""] * 5)[:5]
    return {
        "sha": sha, "short_sha": short_sha, "author": author,
        "committed_at": committed_at, "subject": subject,
    }


def _git_error(message: str, detail: str = "") -> AppException:
    tail = detail.strip().splitlines()[-3:] if detail else []
    return AppException(
        message=f"{message}{'：' + ' | '.join(tail) if tail else ''}",
        code=ErrorCode.INVALID_PARAMETER,
        http_status=400,
    )


async def _git(args: list[str], cwd: Path) -> str:
    try:
        # 私有仓库无凭据时直接失败，避免等待交互输入直到超时
        code, out = await _run_cmd(
            ["git", *args], cwd=cwd, env={"GIT_TERMINAL_PROMPT": "0"},
            timeout=_GIT_TIMEOUT, log_prefix="[repo]",
        )
    except BuildError as e:
        raise _git_error("Git 命令执行失败", e.message)
    if code != 0:
        raise _git_error(f"git {args[0]} 失败", out)
    return out


class CodeRepositoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.cache_root = Path(settings.coverage_workspace_dir) / "_repo_cache"

    # ─── CRUD ───

    async def list(self, project_id: int) -> list[CodeRepository]:
        result = await self.db.execute(
            select(CodeRepository)
            .where(CodeRepository.project_id == project_id, CodeRepository.is_deleted == False)  # noqa: E712
            .order_by(CodeRepository.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, project_id: int, repo_id: int) -> CodeRepository:
        result = await self.db.execute(
            select(CodeRepository).where(
                CodeRepository.id == repo_id,
                CodeRepository.project_id == project_id,
                CodeRepository.is_deleted == False,  # noqa: E712
            )
        )
        repo = result.scalar_one_or_none()
        if not repo:
            raise AppException(message=f"代码源不存在: {repo_id}", code=ErrorCode.RESOURCE_NOT_FOUND, http_status=404)
        return repo

    async def create(self, project_id: int, data: dict, user_id: int) -> CodeRepository:
        repo = CodeRepository(project_id=project_id, created_by=user_id, updated_by=user_id, **data)
        self.db.add(repo)
        await self.db.flush()
        await self.db.refresh(repo)
        await self.db.commit()
        return repo

    async def update(self, project_id: int, repo_id: int, data: dict, user_id: int) -> CodeRepository:
        repo = await self.get(project_id, repo_id)
        url_changed = "repo_url" in data and data["repo_url"] != repo.repo_url
        for k, v in data.items():
            setattr(repo, k, v)
        repo.updated_by = user_id
        await self.db.commit()
        await self.db.refresh(repo)
        if url_changed:
            shutil.rmtree(self._cache_dir(repo.id), ignore_errors=True)
        return repo

    async def delete(self, project_id: int, repo_id: int, user_id: int) -> None:
        repo = await self.get(project_id, repo_id)
        repo.soft_delete(user_id)
        await self.db.commit()
        shutil.rmtree(self._cache_dir(repo.id), ignore_errors=True)

    # ─── 远程查询 ───

    async def list_branches(self, repo: CodeRepository) -> list[dict]:
        self.cache_root.mkdir(parents=True, exist_ok=True)
        out = await _git(["ls-remote", "--heads", "--", repo.repo_url], cwd=self.cache_root)
        branches = []
        for line in out.splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 2 and parts[1].startswith("refs/heads/"):
                branches.append({"name": parts[1][len("refs/heads/"):], "commit_sha": parts[0]})
        default = repo.default_branch
        branches.sort(key=lambda b: (b["name"] != default, b["name"]))
        return branches

    async def discover_services(self, repo: CodeRepository, branch: str) -> list[dict]:
        _check_branch(branch)
        lock = _locks.setdefault(repo.id, asyncio.Lock())
        async with lock:
            cache = await self._fetch_cache(repo)
            out = await _git(["ls-tree", "-r", "--name-only", f"refs/heads/{branch}"], cwd=cache)
        return self._parse_services(out.splitlines(), repo_name=_repo_basename(repo.repo_url))

    async def list_commits(self, repo: CodeRepository, branch: str, limit: int = 30) -> list[dict]:
        """分支最近 N 条提交（供触发采集时下拉选择）"""
        _check_branch(branch)
        lock = _locks.setdefault(repo.id, asyncio.Lock())
        async with lock:
            cache = await self._fetch_cache(repo)
            out = await _git(
                ["log", f"refs/heads/{branch}", "-n", str(limit), "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%s"],
                cwd=cache,
            )
        return [_parse_commit_line(line) for line in out.splitlines() if line.strip()]

    async def resolve_commit(self, repo: CodeRepository, branch: str, commit_sha: Optional[str]) -> str:
        """返回完整 sha：不传时取分支 HEAD；传入时校验它属于该分支历史，否则 400"""
        _check_branch(branch)
        if commit_sha is not None and not _SHA_RE.fullmatch(commit_sha):
            raise _git_error("commit sha 格式不合法")
        lock = _locks.setdefault(repo.id, asyncio.Lock())
        async with lock:
            cache = await self._fetch_cache(repo)
            ref = f"refs/heads/{branch}"
            if commit_sha is None:
                return (await _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=cache)).strip()
            code, out = await _run_cmd(
                ["git", "rev-parse", "--verify", "--quiet", f"{commit_sha}^{{commit}}"],
                cwd=cache, timeout=_GIT_TIMEOUT, log_prefix="[repo]",
            )
            full_sha = out.strip()
            if code != 0 or not full_sha:
                raise _git_error(f"commit {commit_sha} 不存在")
            # exit 0 = 是祖先，1 = 不是，其他 = 出错
            code, out = await _run_cmd(
                ["git", "merge-base", "--is-ancestor", full_sha, ref],
                cwd=cache, timeout=_GIT_TIMEOUT, log_prefix="[repo]",
            )
            if code == 1:
                raise _git_error(f"commit {commit_sha} 不属于分支 {branch}")
            if code != 0:
                raise _git_error("git merge-base 失败", out)
            return full_sha

    async def changed_lines(self, repo: CodeRepository, base_branch: str, head_sha: str) -> tuple[str, dict[str, set[int]]]:
        """merge-base(base_branch, head_sha)..head_sha 的新增/修改行（bare 缓存仓库，blob 按需拉取）"""
        from app.modules.coverage_java.diff_service import DiffCoverageService

        _check_branch(base_branch)
        if not _SHA_RE.fullmatch(head_sha or ""):
            raise _git_error("commit sha 格式不合法")
        lock = _locks.setdefault(repo.id, asyncio.Lock())
        async with lock:
            cache = await self._fetch_cache(repo)
            # _run_cmd 合并了 stderr，sha 取最后一行
            out = await _git(["merge-base", f"refs/heads/{base_branch}", head_sha], cwd=cache)
            merge_base = out.strip().splitlines()[-1].strip()
            diff = await _git(
                ["-c", "core.quotepath=false", "diff", "-U0", "--no-color", "--no-ext-diff",
                 "--diff-filter=ACMR", f"{merge_base}..{head_sha}"],
                cwd=cache,
            )
        return merge_base, DiffCoverageService._parse_diff_output(diff)

    async def _fetch_cache(self, repo: CodeRepository) -> Path:
        cache = await self._ensure_cache(repo)
        await _git(["fetch", "--prune", "origin", "+refs/heads/*:refs/heads/*"], cwd=cache)
        return cache

    def _cache_dir(self, repo_id: int) -> Path:
        return self.cache_root / str(repo_id)

    async def _ensure_cache(self, repo: CodeRepository) -> Path:
        cache = self._cache_dir(repo.id)
        if (cache / "HEAD").exists():
            return cache
        shutil.rmtree(cache, ignore_errors=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        await _git(
            ["clone", "--bare", "--filter=blob:none", "--", repo.repo_url, str(cache)],
            cwd=self.cache_root,
        )
        return cache

    @staticmethod
    def _parse_services(files: list[str], repo_name: str) -> list[dict]:
        found: dict[str, str] = {}
        for f in files:
            p = PurePosixPath(f.strip())
            tool = BUILD_FILES.get(p.name)
            if not tool or "src" in p.parts:
                continue
            path = str(p.parent) if str(p.parent) != "." else "."
            found.setdefault(path, tool)
        services = [
            {"name": repo_name if path == "." else PurePosixPath(path).name, "path": path, "build_tool": tool}
            for path, tool in found.items()
        ]
        services.sort(key=lambda s: (s["path"] != ".", s["path"]))
        return services


def _repo_basename(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    return name[:-4] if name.endswith(".git") else name
