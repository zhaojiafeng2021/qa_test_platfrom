"""
数据库基础配置
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.core.config import settings


def _build_connect_args() -> dict:
    """构建 asyncmy connect_args。

    本地开发默认不需要额外参数；如需 SSL 等高级配置后续再补充。
    """
    return {}


# 创建异步引擎
# 注意：开发环境曾用 NullPool（每请求新建 TCP 连接、不复用），在高频轮询（执行队列 5s）下
# 连接建立开销会累积并耗尽单进程能力，连带拖慢其它模块接口。改用有界连接池复用连接。
# create_async_engine 默认使用 AsyncAdaptedQueuePool，无需显式指定 poolclass。
# pool_recycle=300 (5分钟) 防止长期空闲连接累积脏状态，避免主键冲突等问题。
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    pool_pre_ping=True,  # Test connections before using
    pool_size=10,
    max_overflow=20,
    pool_recycle=300,  # Recycle connections every 5 minutes to prevent stale session state
    connect_args=_build_connect_args(),
)

# 创建会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)

# 声明基类
Base = declarative_base()


# 同步引擎/会话工厂（仅测试用例和本地脚本使用）。
# 生产镜像只安装 asyncmy，不含 PyMySQL 时若在模块导入时创建 sync engine
# 会触发 ModuleNotFoundError 导致整个应用无法启动。
# 因此改为懒加载：只有真正调用 get_db_sync()/SessionLocal() 时才创建，
# 从而使 Web/Worker/Scheduler 等异步入口的启动完全不依赖 PyMySQL。
_sync_engine = None
_SessionLocal = None


def _get_sync_engine():
    """懒加载同步引擎（首次使用时创建，需要 PyMySQL）。"""
    global _sync_engine
    if _sync_engine is None:
        _sync_engine = create_engine(
            settings.database_url.replace("mysql+asyncmy://", "mysql+pymysql://"),
            echo=settings.debug,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            pool_recycle=300,
        )
    return _sync_engine


def _get_session_local():
    """懒加载同步会话工厂。"""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=_get_sync_engine(),
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _SessionLocal


def __getattr__(name):
    """模块级懒属性：保持 `from app.db.base import sync_engine / SessionLocal` 向后兼容。

    仅在真正访问这两个名字时才触发同步引擎创建（需要 PyMySQL）。
    """
    if name == "sync_engine":
        return _get_sync_engine()
    if name == "SessionLocal":
        return _get_session_local()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_db() -> AsyncSession:
    """
    获取数据库会话的依赖项（异步）
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


def get_db_sync() -> Session:
    """
    获取数据库会话的依赖项（同步，用于测试用例和脚本）
    """
    session = _get_session_local()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
