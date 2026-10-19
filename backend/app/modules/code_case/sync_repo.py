"""
代码用例 Git 仓库同步模块（方案 A：扫描入口 Pull）

功能：
1. 首次部署：Volume 为空 → git clone
2. 后续扫描：git pull（带节流，默认 60s 内不重复 pull）
3. 并发保护：线程锁，防止多请求同时 pull
4. 环境变量注入：同步后注入 CRED_DB_*，供用例执行时 credential_helper 读取
5. 依赖自动安装：同步后检测 requirements.txt 变化，自动 pip install

使用方式：
    from app.modules.code_case.sync_repo import ensure_latest
    result = ensure_latest()
    # result = {"synced": True, "commit": "a786b8c", "message": "pull 成功"}
"""
import hashlib
import os
import sys
import time
import logging
import subprocess
import threading
from urllib.parse import urlparse

from app.core.config import settings

logger = logging.getLogger(__name__)

# 上次 pull 时间戳（模块级缓存）
_last_pull_ts: float = 0.0
# 并发锁
_lock = threading.Lock()

# 依赖 hash 缓存文件名（存在 code_testcases 根目录下）
_REQ_HASH_FILE = ".deps_hash"


def _build_authed_url(repo_url: str, token: str) -> str:
    """把 Token 嵌入 HTTPS URL：https://oauth2:{token}@git.tec-do.com/..."""
    if not token:
        return repo_url
    parsed = urlparse(repo_url)
    return f"{parsed.scheme}://oauth2:{token}@{parsed.netloc}{parsed.path}"


def _get_target_dir() -> str:
    """获取 code_testcases 目标目录"""
    if settings.code_testcases_dir:
        return settings.code_testcases_dir
    # 回退：项目根目录下的 code_testcases（本地 windows / 源目录部署通用）
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "code_testcases")


def _get_commit_hash(repo_dir: str) -> str:
    """获取当前 commit 短 hash"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _inject_cred_env() -> None:
    """同步完成后注入 CRED_DB_* 环境变量，供 credential_helper 读取。

    只在 settings.cred_db_host 被显式配置（非默认 localhost）时才注入 CRED_DB_*，
    否则只保留 DATABASE_URL，让 credential_helper 走 DATABASE_URL 回退解析。
    防止默认值 localhost 覆盖掉 credential_helper 的回退逻辑。
    """
    # DATABASE_URL 必须保留（Apollo 注入的，credential_helper 回退解析要用）
    db_url = os.environ.get("DATABASE_URL") or settings.database_url
    if db_url:
        os.environ["DATABASE_URL"] = db_url

    # 只有当 cred_db_host 被显式配置（非默认 localhost）时才注入 CRED_DB_*
    # 否则让 credential_helper 走 DATABASE_URL 回退，避免误连 localhost
    if settings.cred_db_host and settings.cred_db_host != "localhost":
        os.environ["CRED_DB_TYPE"] = settings.cred_db_type
        os.environ["CRED_DB_HOST"] = settings.cred_db_host
        os.environ["CRED_DB_PORT"] = str(settings.cred_db_port)
        os.environ["CRED_DB_USER"] = settings.cred_db_user
        if settings.cred_db_password:
            os.environ["CRED_DB_PASSWORD"] = settings.cred_db_password
        os.environ["CRED_DB_DATABASE"] = settings.cred_db_database
        logger.info("已注入 CRED_DB_* 环境变量（显式配置 host=%s）", settings.cred_db_host)
    else:
        logger.info("未注入 CRED_DB_*（默认 localhost），credential_helper 将走 DATABASE_URL 回退解析")

def _verify_packages_importable(req_file: str) -> tuple[bool, str]:
    """验证 requirements.txt 中的包是否真正可导入。

    解决 pod 重启后 site-packages 重置但 .deps_hash 仍在 PVC 的问题：
    即使 hash 匹配，也要确认包确实装在当前容器的 site-packages 里。

    Returns:
        tuple[bool, str]: (是否全部可导入, 缺失描述)
    """
    import importlib.util
    import re

    # 常见包名 → import 名映射（不一致的包在这里维护）
    IMPORT_MAP = {
        "pymysql": "pymysql",
        "psycopg2-binary": "psycopg2",
        "python-dotenv": "dotenv",
        "python-jose": "jose",
        "pyyaml": "yaml",
        "python-multipart": "multipart",
        "email-validator": "email_validator",
    }

    missing = []
    try:
        with open(req_file, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 提取包名（去掉版本号、extras、环境标记）
                name = re.split(r"[>=<!\[\(;]", line)[0].strip().lower()
                if not name:
                    continue
                import_name = IMPORT_MAP.get(name, name.replace("-", "_"))
                if importlib.util.find_spec(import_name) is None:
                    missing.append(name)
    except Exception as e:
        return False, f"验证异常: {e}"

    if missing:
        return False, f"缺少: {', '.join(missing)}"
    return True, "全部可导入"

def _install_dependencies(repo_dir: str) -> tuple[bool, str]:
    """
    检测 requirements.txt 变化并自动 pip install。

    改进点（修复 pod 重启后依赖丢失问题）：
    1. hash 匹配时额外验证包是否真正可导入，防止 PVC 上 hash 缓存
       与 site-packages 实际状态不一致
    2. pip install 成功后再次验证，确认包确实装上才写 hash

    Returns:
        tuple[bool, str]: (是否执行了安装, 描述信息)
    """
    req_file = os.path.join(repo_dir, "requirements.txt")
    if not os.path.isfile(req_file):
        return False, "无 requirements.txt，跳过依赖安装"

    try:
        with open(req_file, "rb") as f:
            current_hash = hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logger.error("读取 requirements.txt 失败: %s", e)
        return False, f"读取 requirements.txt 失败: {e}"

    hash_file = os.path.join(repo_dir, _REQ_HASH_FILE)
    cached_hash = ""
    if os.path.isfile(hash_file):
        try:
            with open(hash_file, "r") as f:
                cached_hash = f.read().strip()
        except Exception:
            pass

    # 1. hash 匹配 → 再验证包是否真正可导入（防止 pod 重启后 hash 在但包丢了）
    if current_hash == cached_hash:
        all_ok, verify_msg = _verify_packages_importable(req_file)
        if all_ok:
            return False, "requirements.txt 无变化且依赖已安装，跳过"
        logger.warning("hash 匹配但依赖缺失（可能是 pod 重启导致），重新安装: %s", verify_msg)
        # 不 return，继续往下走重新安装

    # 2. hash 不同 或 包缺失 → 执行安装
    logger.info("requirements.txt 变化或依赖缺失，开始安装依赖...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
        capture_output=True, text=True, timeout=120
    )

    if result.returncode != 0:
        logger.error("pip install 失败: %s", result.stderr)
        return False, f"pip install 失败: {result.stderr.strip()}"

    # 3. 安装后验证包是否真正可导入（防止 pip returncode=0 但包没装上）
    all_ok, verify_msg = _verify_packages_importable(req_file)
    if not all_ok:
        logger.error("pip install 返回成功但依赖仍不可导入: %s", verify_msg)
        return False, f"安装后验证失败: {verify_msg}"

    # 4. 验证通过才写 hash
    with open(hash_file, "w") as f:
        f.write(current_hash)

    logger.info("依赖安装并验证完成: %s", result.stdout.strip().split("\n")[-1] if result.stdout else "")
    return True, f"依赖安装成功 (hash={current_hash[:8]})"


def ensure_latest() -> dict:
    """
    确保本地 code_testcases 是仓库最新版本。

    流程：
    - code_repo_enabled=False → 跳过，返回未启用
    - 目标目录无 .git → 首次 clone
    - 目标目录有 .git → git pull（节流：throttle_seconds 内不重复）
    - 同步后注入 CRED_DB_* 环境变量

    Returns:
        {
            "synced": bool,       # True=本次有更新, False=未启用/节流跳过/无更新
            "commit": str,        # 当前 commit 短 hash
            "message": str,       # 描述信息
        }
    """
    # 未启用 Git 同步
    if not settings.code_repo_enabled:
        return {"synced": False, "commit": "", "message": "Git 同步未启用"}

    if not settings.code_repo_url:
        return {"synced": False, "commit": "", "message": "未配置 code_repo_url"}

    global _last_pull_ts
    with _lock:
        now = time.time()
        # 节流：throttle_seconds 内不重复 pull
        if now - _last_pull_ts < settings.code_repo_throttle_seconds:
            target = _get_target_dir()
            commit = _get_commit_hash(target) if os.path.exists(os.path.join(target, ".git")) else ""
            return {"synced": False, "commit": commit, "message": f"节流跳过，距上次 pull 不足 {settings.code_repo_throttle_seconds}s"}

        target_dir = _get_target_dir()
        os.makedirs(target_dir, exist_ok=True)
        git_dir = os.path.join(target_dir, ".git")

        authed_url = _build_authed_url(settings.code_repo_url, settings.code_repo_token)

        if not os.path.exists(git_dir):
            # ===== 首次 clone =====
            backup = None
            # 目标目录非空且无 .git：先 clone 到临时目录，成功后再替换，
            # 避免 os.rename 因为文件句柄被锁而 WinError 5
            if os.listdir(target_dir):
                tmp_dir = "%s.tmp_%d" % (target_dir, int(time.time()))
                backup = "%s.bak_%d" % (target_dir, int(time.time()))
                logger.info("目标目录非空且无 .git，先 clone 到临时目录: %s", tmp_dir)
                os.makedirs(tmp_dir, exist_ok=True)
                clone_target = tmp_dir
            else:
                clone_target = target_dir

            logger.info("首次 clone: %s -> %s", settings.code_repo_url, clone_target)
            result = subprocess.run(
                ["git", "clone", "--branch", settings.code_repo_branch, authed_url, clone_target],
                capture_output=True, text=True, timeout=120
            )
            _last_pull_ts = now
            _inject_cred_env()
            if result.returncode != 0:
                logger.error("git clone 失败: %s", result.stderr)
                # 清理临时目录
                import shutil
                if clone_target != target_dir and os.path.exists(clone_target):
                    shutil.rmtree(clone_target, ignore_errors=True)
                return {"synced": False, "commit": "", "message": "clone 失败: %s" % result.stderr.strip()}

            # clone 成功：如果走了临时目录分支，就把旧目录备份，临时目录转正
            if clone_target != target_dir:
                ok_replaced = False
                import shutil
                try:
                    os.rename(target_dir, backup)
                    ok_replaced = True
                except Exception as e:
                    logger.warning("os.rename 备份旧目录失败(%s)，改用 shutil.copytree + rmtree", e)
                    try:
                        shutil.copytree(target_dir, backup)
                        shutil.rmtree(target_dir)
                        ok_replaced = True
                    except Exception as e2:
                        logger.warning("备份旧目录仍失败，放弃替换，但代码已 clone 到: %s (错误: %s)", clone_target, e2)
                if ok_replaced:
                    try:
                        os.rename(clone_target, target_dir)
                    except Exception as e:
                        logger.warning("临时目录 rename 失败(%s)，用 shutil.move", e)
                        shutil.move(clone_target, target_dir)

            commit = _get_commit_hash(target_dir)
            logger.info("clone 成功: %s (原目录备份=%s)", commit, backup)
            deps_installed, deps_msg = _install_dependencies(target_dir)
            return {"synced": True, "commit": commit,
                    "message": "首次 clone 成功: %s (原目录备份=%s) | %s" % (commit, backup, deps_msg)}

        else:
            # ===== 后续 pull =====
            # 先更新 remote URL（防止 Token 轮换后旧 URL 失效）
            subprocess.run(
                ["git", "remote", "set-url", "origin", authed_url],
                cwd=target_dir, capture_output=True, text=True, timeout=10
            )
            # 重置本地改动（防止 pull 冲突，Volume 里的代码应该以仓库为准）
            subprocess.run(
                ["git", "checkout", "."],
                cwd=target_dir, capture_output=True, text=True, timeout=30
            )
            logger.info(f"git pull: {settings.code_repo_branch}")
            result = subprocess.run(
                ["git", "pull", "origin", settings.code_repo_branch],
                cwd=target_dir, capture_output=True, text=True, timeout=60
            )
            _last_pull_ts = now
            _inject_cred_env()
            if result.returncode != 0:
                logger.error(f"git pull 失败: {result.stderr}")
                return {"synced": False, "commit": "", "message": f"pull 失败: {result.stderr.strip()}"}
            commit = _get_commit_hash(target_dir)
            if "Already up to date" in result.stdout:
                deps_installed, deps_msg = _install_dependencies(target_dir)
                return {"synced": False, "commit": commit, "message": "已是最新，无更新 | %s" % deps_msg}
            logger.info(f"pull 成功: {commit}")
            deps_installed, deps_msg = _install_dependencies(target_dir)
            return {"synced": True, "commit": commit, "message": f"pull 成功: {commit} | {deps_msg}"}
