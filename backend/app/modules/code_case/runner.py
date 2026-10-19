"""
代码用例执行 runner（独立子进程入口）

由 executor 以 `python -m app.modules.code_case.runner <file> <func>` 方式调用。
放在子进程执行而不是进程内，原因：
  1. 用例里的死循环/sys.exit 不会拖垮 API 进程，超时可强制 kill
  2. stdout/stderr 重定向不会串到并发请求（异步进程内重定向是全局的）
  3. 用例的 import 副作用不污染 API 进程

结果以单行 JSON 打到 stdout 的哨兵标记之后，便于父进程稳定解析。

判定语义对齐 django 项目 common/executor.py：
  无异常        -> passed
  AssertionError -> failed（断言失败）
  其他异常       -> error（执行错误）
"""
import importlib.util
import io
import json
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

RESULT_SENTINEL = "__QA_CODE_CASE_RESULT__"

class _Tee(io.TextIOBase):
    """同时写内存缓冲区和原始 stdout/stderr。

    print 内容既进 buf（最终存 DB、前端执行详情可见），
    又实时透传到子进程真实 stdout（父进程流式读取后打到 worker 日志）。
    """
    def __init__(self, buf: io.StringIO, original):
        self._buf = buf
        self._original = original

    def write(self, s):
        self._buf.write(s)
        try:
            self._original.write(s)
            self._original.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        self._buf.flush()
        try:
            self._original.flush()
        except Exception:
            pass


def _load_module(file_path: Path):
    """按文件路径加载模块（不依赖包结构）"""
    module_name = f"_qa_code_case_{abs(hash(str(file_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块: {file_path}")
    # 用例所在目录加入 sys.path，支持用例 import 同目录辅助模块
    # （如 payment/test_pay_channel.py 里 from pay_channel_check import *）
    case_dir = str(file_path.parent.resolve())
    if case_dir not in sys.path:
        sys.path.insert(0, case_dir)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_func(module, function_name: str):
    """
    定位目标函数

    指定了函数名就必须精确命中：找不到直接报错，不回退到同文件其它用例，
    否则会拿别的用例的执行结果冒充本用例（张冠李戴）。
    仅在未指定函数名时，才回退到唯一一个带 @case 标记的函数。
    """
    if function_name:
        func = getattr(module, function_name, None)
        if callable(func):
            return func, function_name
        raise RuntimeError(
            f"文件中未找到函数 {function_name}()，代码可能已变更，请重新扫描代码"
        )

    marked = [
        (attr, getattr(module, attr)) for attr in dir(module)
        if not attr.startswith("__")
        and callable(getattr(module, attr, None))
        and getattr(getattr(module, attr), "_is_test_case", False)
    ]
    if len(marked) == 1:
        return marked[0][1], marked[0][0]
    if not marked:
        raise RuntimeError("未找到可执行的测试函数，请重新扫描代码")
    raise RuntimeError(
        f"未指定函数名，且文件中有 {len(marked)} 个用例函数，无法确定执行目标"
    )


def run(file_path: str, function_name: str) -> dict:
    buf = io.StringIO()
    status = "passed"
    message = ""
    tb = ""
    start = time.perf_counter()

    try:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"用例文件不存在: {file_path}")

        tee_out = _Tee(buf, sys.__stdout__)
        tee_err = _Tee(buf, sys.__stderr__)
        with redirect_stdout(tee_out), redirect_stderr(tee_err):
            print(f"[INFO] 加载文件: {file_path}")
            module = _load_module(path)
            func, resolved = _resolve_func(module, function_name)
            print(f"[INFO] 执行函数: {resolved}")
            print()
            result = func()
            # 支持 async def 用例
            if hasattr(result, "__await__"):
                import asyncio
                asyncio.run(result)
            print()
            print("[INFO] 测试通过")

    except AssertionError as e:
        status = "failed"
        message = f"断言失败: {e}" if str(e) else "断言失败"
        tb = traceback.format_exc()
    except Exception as e:
        status = "error"
        message = f"执行错误: {type(e).__name__}: {e}"
        tb = traceback.format_exc()

    duration_ms = int((time.perf_counter() - start) * 1000)
    logs = buf.getvalue()
    if tb:
        logs = f"{logs}\n[TRACEBACK]\n{tb}"

    return {
        "status": status,
        "message": message,
        "logs": logs,
        "traceback": tb,
        "duration_ms": duration_ms,
    }


def main() -> int:
    if len(sys.argv) < 2:
        payload = {
            "status": "error",
            "message": "用法: runner.py <file_path> [function_name]",
            "logs": "", "traceback": "", "duration_ms": 0,
        }
    else:
        payload = run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")

    sys.stdout.write(f"\n{RESULT_SENTINEL}{json.dumps(payload, ensure_ascii=False)}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
