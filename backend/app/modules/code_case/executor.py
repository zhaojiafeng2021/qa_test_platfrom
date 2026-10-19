"""
代码用例执行器

以子进程方式调用 runner 执行单个用例，带超时强制终止。
参考 django 项目 common/executor.py 的判定语义，但改为子进程隔离。
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from app.modules.code_case.runner import RESULT_SENTINEL

logger = logging.getLogger(__name__)

# 单个用例默认超时（秒）
DEFAULT_TIMEOUT_SECONDS = 60
# 日志与堆栈截断上限，避免超大输出打满数据库
MAX_LOG_CHARS = 100_000
MAX_TRACEBACK_CHARS = 20_000


def _truncate(text: str, limit: int) -> str:
    if not text or len(text) <= limit:
        return text or ""
    return text[:limit] + f"\n... [输出过长，已截断，共 {len(text)} 字符]"


def _backend_root() -> Path:
    """backend 根目录：app/modules/code_case/executor.py -> parents[3]"""
    return Path(__file__).resolve().parents[3]



async def _read_output(proc) -> tuple[bytes, bytes]:
    """流式读取子进程输出：逐行透传到 worker 日志（print 实时可见），
    同时缓存完整输出用于解析哨兵结果。"""

    async def _pump(stream, tag: str) -> bytes:
        chunks = []
        while True:
            line = await stream.readline()
            if not line:
                break
            chunks.append(line)
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            if text and not text.startswith(RESULT_SENTINEL):
                logger.info("[code-case %s] %s", tag, text)
        return b"".join(chunks)

    out_task = asyncio.create_task(_pump(proc.stdout, "out"))
    err_task = asyncio.create_task(_pump(proc.stderr, "err"))
    stdout_b = await out_task
    stderr_b = await err_task
    return stdout_b, stderr_b


async def execute_case(abs_file_path: str, function_name: str,
                       timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """
    在子进程中执行单个用例

    Returns:
        dict: status(passed/failed/error/timeout), message, logs, traceback, duration_ms
    """
    backend_root = _backend_root()
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    
    # 获取 code_testcases 目录（用例仓库根目录）
    from app.modules.code_case.service import get_code_testcases_dir
    code_testcases_dir = str(get_code_testcases_dir())
    
    # 让子进程能 import app.* 和 code_testcases.*
    # 用例里会 from common.credential_helper import ... 需要 code_testcases 在 sys.path 上
    path_parts = [str(backend_root), code_testcases_dir]
    existing = env.get("PYTHONPATH", "")
    if existing:
        path_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(path_parts)

    cmd = [sys.executable, "-m", "app.modules.code_case.runner",
           abs_file_path, function_name or ""]

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(backend_root),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                _read_output(proc), timeout=timeout
            )
        except asyncio.TimeoutError:
            _kill(proc)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
            return {
                "status": "timeout",
                "message": f"执行超时（超过 {timeout} 秒已强制终止）",
                "logs": "", "traceback": "", "duration_ms": timeout * 1000,
            }
    except Exception as e:
        logger.exception("启动执行子进程失败")
        return {
            "status": "error",
            "message": f"启动执行子进程失败: {type(e).__name__}: {e}",
            "logs": "", "traceback": "", "duration_ms": 0,
        }

    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")

    result = _parse_result(stdout)
    if result is None:
        # 子进程异常退出（段错误、sys.exit、语法错误等），没吐出结果
        return {
            "status": "error",
            "message": f"执行子进程异常退出（returncode={proc.returncode}）",
            "logs": _truncate(stdout + ("\n" + stderr if stderr else ""), MAX_LOG_CHARS),
            "traceback": _truncate(stderr, MAX_TRACEBACK_CHARS),
            "duration_ms": 0,
        }

    if stderr.strip():
        result["logs"] = (result.get("logs") or "") + f"\n[STDERR]\n{stderr}"

    result["logs"] = _truncate(result.get("logs") or "", MAX_LOG_CHARS)
    result["traceback"] = _truncate(result.get("traceback") or "", MAX_TRACEBACK_CHARS)
    result["message"] = (result.get("message") or "")[:1000]
    return result


def _parse_result(stdout: str):
    """从 stdout 中取哨兵标记后的 JSON 结果"""
    idx = stdout.rfind(RESULT_SENTINEL)
    if idx < 0:
        return None
    raw = stdout[idx + len(RESULT_SENTINEL):].strip()
    line = raw.splitlines()[0] if raw else ""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "status" not in data:
        return None
    # 结果 JSON 之前的内容是用例自身的输出，一并保留
    prefix = stdout[:idx].rstrip()
    if prefix and not data.get("logs"):
        data["logs"] = prefix
    return data


def _kill(proc) -> None:
    """终止子进程；Windows 下 kill 即 TerminateProcess"""
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    except Exception:
        logger.warning("终止执行子进程失败", exc_info=True)
