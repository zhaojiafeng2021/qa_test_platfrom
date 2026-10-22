"""Java 项目构建服务：git clone → 检测构建工具 → 注入 JaCoCo agent → 跑测试 → 收集 .exec

设计原则：
- 所有子进程调用都用 asyncio.create_subprocess_exec，不阻塞事件循环
- 每个服务的构建目录：{workspace}/{task_id}/{run_id}/{service_name}/
- 构建日志实时收集到内存，结束后写入 .log 文件
- 失败时抛 BuildError，由上层（CoverageJavaService）捕获并写库
"""
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class BuildError(Exception):
    """构建失败（git clone / mvn / gradle / jacoco 任一步失败）"""

    def __init__(self, stage: str, message: str, build_log: str = ""):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.build_log = build_log


def _find_mvn() -> str:
    """优先使用 MAVEN_HOME 配置，其次 PATH"""
    if settings.maven_home:
        bin_dir = Path(settings.maven_home) / "bin"
        for name in (("mvn.cmd",) if os.name == "nt" else ("mvn",)):
            candidate = bin_dir / name
            if candidate.is_file():
                return str(candidate)
    return shutil.which("mvn") or shutil.which("mvn.cmd") or "mvn"


@dataclass
class BuildResult:
    """构建产物"""
    exec_file: Path                 # jacoco .exec 二进制
    classfiles_dir: Path            # 编译后的 class 文件目录
    sourcefiles_dir: Path           # 源码目录
    build_log: str                  # 完整构建日志
    commit_sha: Optional[str] = None
    extra: dict = field(default_factory=dict)


async def _run_cmd(
    cmd: list[str] | str,
    cwd: Path,
    env: Optional[dict] = None,
    timeout: int = 1800,
    log_prefix: str = "",
) -> tuple[int, str]:
    """异步执行子进程，返回 (exit_code, combined_output)

    cmd 可以是 list（走 create_subprocess_exec）或 str（走 create_subprocess_shell）。
    Windows 下 cmd /c 有引号剥离规则，批处理命令建议用 str 形式。
    """
    import os
    display = cmd if isinstance(cmd, str) else " ".join(cmd)
    logger.info(f"{log_prefix} Running: {display} (cwd={cwd})")
    merged_env = {**os.environ, **(env or {})}

    try:
        if isinstance(cmd, str):
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=str(cwd),
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                env=merged_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise BuildError("build", f"Command timeout after {timeout}s: {display}")
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        return proc.returncode or 0, output
    except FileNotFoundError as e:
        raise BuildError("build", f"Command not found: {display} ({e})") from e


async def _get_commit_sha(repo_dir: Path) -> Optional[str]:
    """获取当前 HEAD 的 commit SHA"""
    code, out = await _run_cmd(
        ["git", "rev-parse", "HEAD"], cwd=repo_dir, timeout=10, log_prefix="[git]"
    )
    if code == 0:
        return out.strip().splitlines()[0] if out.strip() else None
    return None


class JavaBuildService:
    """Java 项目构建 + JaCoCo agent 注入"""

    def __init__(self):
        self.jacoco_agent = Path(settings.jacoco_agent_jar_path)
        self.workspace_root = Path(settings.coverage_workspace_dir)

    def _service_workspace(self, task_id: int, run_id: int, service_name: str) -> Path:
        return self.workspace_root / str(task_id) / str(run_id) / service_name

    async def clone_repo(
        self,
        repo_url: str,
        branch: str,
        workspace: Path,
    ) -> tuple[Path, str]:
        """克隆仓库到 workspace/repo；返回 (repo_dir, clone_log)"""
        repo_dir = workspace / "repo"
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        workspace.mkdir(parents=True, exist_ok=True)

        code, log = await _run_cmd(
            ["git", "clone", "--depth", "50", "--branch", branch, repo_url, "repo"],
            cwd=workspace,
            timeout=600,
            log_prefix="[clone]",
        )
        if code != 0:
            raise BuildError("clone", f"git clone failed: exit={code}", build_log=log)
        return repo_dir, log

    def _detect_build_tool(self, service_dir: Path) -> str:
        """检测 maven / gradle / unknown"""
        if (service_dir / "pom.xml").exists():
            return "maven"
        if (service_dir / "build.gradle").exists() or (service_dir / "build.gradle.kts").exists():
            return "gradle"
        return "unknown"

    async def run_build(
        self,
        task_id: int,
        run_id: int,
        service: dict,
        repo_url: str,
        branch: str,
    ) -> BuildResult:
        """对单个服务执行完整构建流程

        Args:
            task_id, run_id: 用于生成 workspace 路径
            service: {"name": "order-service", "path": "services/order", "module": "order"}
            repo_url: 仓库 URL（https）
            branch: 目标分支

        Returns:
            BuildResult
        """
        service_name = service["name"]
        workspace = self._service_workspace(task_id, run_id, service_name)

        # ─── 1. git clone ───
        logger.info(f"[{service_name}] Cloning {repo_url}#{branch}")
        repo_dir, clone_log = await self.clone_repo(repo_url, branch, workspace)
        commit_sha = await _get_commit_sha(repo_dir)

        # ─── 2. 检测构建工具 ───
        service_dir = repo_dir / service["path"]
        if not service_dir.exists():
            raise BuildError(
                "clone",
                f"service path not found in repo: {service['path']}",
                build_log=clone_log,
            )
        build_tool = self._detect_build_tool(service_dir)
        if build_tool == "unknown":
            raise BuildError(
                "build",
                f"no pom.xml or build.gradle found under {service['path']}",
                build_log=clone_log,
            )
        logger.info(f"[{service_name}] Detected build tool: {build_tool}")

        # ─── 3. 注入 JaCoCo agent + 跑测试 ───
        exec_file = workspace / "coverage.exec"
        jacoco_agent_arg = f"-javaagent:{self.jacoco_agent}=destfile={exec_file}"

        if build_tool == "maven":
            # - MAVEN_OPTS 只作用于 Maven 自身 JVM，surefire fork 的子 JVM 必须通过 -DargLine 注入
            # - Windows 下 mvn 是 .cmd，用 create_subprocess_shell + 单字符串命令行最稳
            mvn_bin = _find_mvn()
            if mvn_bin.lower().endswith((".cmd", ".bat")):
                cmd: list[str] | str = (
                    f'"{mvn_bin}" clean test -B -DskipTests=false '
                    f'"-DargLine={jacoco_agent_arg}"'
                )
            else:
                cmd = [mvn_bin, "clean", "test", "-B", "-DskipTests=false", f"-DargLine={jacoco_agent_arg}"]
            env: dict = {}
            classfiles_dir = service_dir / "target" / "classes"
            sourcefiles_dir = service_dir / "src" / "main" / "java"
        else:  # gradle
            if (service_dir / "gradlew").exists():
                gradle_bin = str(service_dir / ("gradlew.bat" if (service_dir / "gradlew.bat").exists() else "gradlew"))
            else:
                gradle_bin = shutil.which("gradle") or "gradle"
            if gradle_bin.lower().endswith((".cmd", ".bat")):
                cmd = f'"{gradle_bin}" test jacocoTestReport'
            else:
                cmd = [gradle_bin, "test", "jacocoTestReport"]
            env = {"GRADLE_OPTS": jacoco_agent_arg}
            classfiles_dir = service_dir / "build" / "classes" / "java" / "main"
            sourcefiles_dir = service_dir / "src" / "main" / "java"

        logger.info(f"[{service_name}] Running build: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
        build_code, build_log = await _run_cmd(
            cmd,
            cwd=service_dir,
            env=env,
            timeout=settings.coverage_java_default_timeout,
            log_prefix=f"[build:{service_name}]",
        )

        full_log = f"{clone_log}\n\n===== BUILD =====\n\n{build_log}"

        if build_code != 0:
            raise BuildError(
                "build",
                f"{build_tool} build failed: exit={build_code}",
                build_log=full_log,
            )

        # ─── 4. 校验 .exec 文件是否生成 ───
        if not exec_file.exists() or exec_file.stat().st_size == 0:
            raise BuildError(
                "build",
                "JaCoCo .exec file not generated or empty (agent not injected?)",
                build_log=full_log,
            )

        return BuildResult(
            exec_file=exec_file,
            classfiles_dir=classfiles_dir,
            sourcefiles_dir=sourcefiles_dir,
            build_log=full_log,
            commit_sha=commit_sha,
            extra={"build_tool": build_tool, "service_dir": str(service_dir)},
        )

    async def run_compile(
        self,
        task_id: int,
        run_id: int,
        service: dict,
        repo_url: str,
        branch: str,
    ) -> BuildResult:
        """运行时模式：clone + 只编译（不跑测试），产出 class/源码目录供 jacococli report 使用。

        exec_file 指向 workspace/coverage.exec，由 RuntimeDumpService 负责写入。
        注意：编译产物须与被测应用部署的 class 一致（同 commit、同 JDK），否则 JaCoCo 会因 class id 不匹配而丢覆盖。
        """
        service_name = service["name"]
        workspace = self._service_workspace(task_id, run_id, service_name)

        repo_dir, clone_log = await self.clone_repo(repo_url, branch, workspace)
        commit_sha = await _get_commit_sha(repo_dir)

        service_dir = repo_dir / service["path"]
        if not service_dir.exists():
            raise BuildError("clone", f"service path not found in repo: {service['path']}", build_log=clone_log)
        build_tool = self._detect_build_tool(service_dir)

        if build_tool == "maven":
            mvn_bin = _find_mvn()
            if mvn_bin.lower().endswith((".cmd", ".bat")):
                cmd: list[str] | str = f'"{mvn_bin}" clean compile -B'
            else:
                cmd = [mvn_bin, "clean", "compile", "-B"]
            classfiles_dir = service_dir / "target" / "classes"
        elif build_tool == "gradle":
            if (service_dir / "gradlew").exists():
                gradle_bin = str(service_dir / ("gradlew.bat" if (service_dir / "gradlew.bat").exists() else "gradlew"))
            else:
                gradle_bin = shutil.which("gradle") or "gradle"
            if gradle_bin.lower().endswith((".cmd", ".bat")):
                cmd = f'"{gradle_bin}" classes'
            else:
                cmd = [gradle_bin, "classes"]
            classfiles_dir = service_dir / "build" / "classes" / "java" / "main"
        else:
            raise BuildError("build", f"no pom.xml or build.gradle found under {service['path']}", build_log=clone_log)

        build_code, build_log = await _run_cmd(
            cmd,
            cwd=service_dir,
            timeout=settings.coverage_java_default_timeout,
            log_prefix=f"[compile:{service_name}]",
        )
        full_log = f"{clone_log}\n\n===== COMPILE =====\n\n{build_log}"
        if build_code != 0:
            raise BuildError("build", f"{build_tool} compile failed: exit={build_code}", build_log=full_log)

        return BuildResult(
            exec_file=workspace / "coverage.exec",
            classfiles_dir=classfiles_dir,
            sourcefiles_dir=service_dir / "src" / "main" / "java",
            build_log=full_log,
            commit_sha=commit_sha,
            extra={"build_tool": build_tool, "service_dir": str(service_dir)},
        )
