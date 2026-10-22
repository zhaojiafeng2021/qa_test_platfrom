"""运行时覆盖率采集：通过 JaCoCo tcpserver 模式 dump 被测应用的 .exec

被测应用启动参数需包含：
    -javaagent:/path/jacocoagent.jar=output=tcpserver,address=*,port=6300

本服务调用：
    java -jar jacococli.jar dump --address {host} --port {port} --destfile {exec} [--reset] --retry N
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.modules.coverage_java.build_service import BuildError

logger = get_logger(__name__)

DEFAULT_AGENT_PORT = 6300


class RuntimeDumpService:
    """从运行中的 JaCoCo agent（tcpserver）拉取覆盖率数据"""

    def __init__(self):
        self.jacoco_cli = Path(settings.jacoco_cli_jar_path)

    async def dump_coverage(
        self,
        host: str,
        port: int,
        output_exec_file: Path,
        reset: bool = False,
        retry: int = 3,
        timeout: int = 60,
    ) -> str:
        """dump 覆盖率到 output_exec_file，返回 jacococli 输出日志

        Raises:
            BuildError(stage="test"): 连接失败 / 超时 / 产物为空（复用 test 阶段，前端无需新增 stage）
        """
        output_exec_file.parent.mkdir(parents=True, exist_ok=True)
        if output_exec_file.exists():
            output_exec_file.unlink()

        cmd = [
            "java", "-jar", str(self.jacoco_cli), "dump",
            "--address", host,
            "--port", str(port),
            "--destfile", str(output_exec_file),
            "--retry", str(retry),
        ]
        if reset:
            cmd.append("--reset")

        display = " ".join(cmd)
        logger.info(f"[dump] Running: {display}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError as e:
            raise BuildError("test", f"java not found: {e}") from e

        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise BuildError("test", f"dump timeout after {timeout}s ({host}:{port})")

        log = f"$ {display}\n" + (stdout.decode("utf-8", errors="replace") if stdout else "")
        if proc.returncode != 0:
            raise BuildError(
                "test",
                f"dump from {host}:{port} failed (exit={proc.returncode})，"
                f"请确认应用已用 output=tcpserver 启动且端口可达",
                build_log=log,
            )
        if not output_exec_file.exists() or output_exec_file.stat().st_size == 0:
            raise BuildError("test", f"dump from {host}:{port} produced empty .exec", build_log=log)

        logger.info(f"[dump] {host}:{port} -> {output_exec_file} ({output_exec_file.stat().st_size} bytes)")
        return log
