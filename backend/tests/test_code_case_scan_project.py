"""
按项目扫描代码用例：只同步当前项目，其他项目/全局用例不受影响
"""
import asyncio
import textwrap
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import ResourceNotFoundError
from app.db.base import Base
from app.db.models.code_case import CodeCaseModule, CodeTestCase
from app.db.models.project import Project
from app.modules.code_case import service as cc_service
from app.modules.code_case.repository import CodeTestCaseRepository
from app.modules.code_case.service import CodeCaseScanService


def _case(func: str, name: str, project: str = "") -> str:
    proj = f', project="{project}"' if project else ""
    return textwrap.dedent(f'''
        @case(module="订单-下单", name="{name}", level="P1"{proj})
        def {func}():
            assert True
    ''')


def _write(root: Path, body: str) -> None:
    (root / "test_cases.py").write_text("from x import case\n" + body, encoding="utf-8")


async def _setup(tmp_path, monkeypatch):
    root = tmp_path / "code_testcases"
    root.mkdir()
    monkeypatch.setattr(cc_service, "get_code_testcases_dir", lambda: root)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    tables = [t.__table__ for t in (Project, CodeCaseModule, CodeTestCase)]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    db = async_sessionmaker(engine, expire_on_commit=False)()
    a = Project(code="A", name="项目A", owner_id=1)
    b = Project(code="B", name="项目B", owner_id=1)
    db.add_all([a, b])
    await db.commit()
    return root, db, engine, a.id, b.id


async def _by_func(db) -> dict[str, CodeTestCase]:
    return {c.function_name: c for c in await CodeTestCaseRepository(db).list_all(include_deleted=True)}


def test_scan_only_current_project(tmp_path, monkeypatch):
    async def run():
        root, db, engine, pa, pb = await _setup(tmp_path, monkeypatch)
        try:
            _write(root, _case("test_a1", "A1", "项目A") + _case("test_b1", "B1", "项目B")
                   + _case("test_g1", "G1"))

            r = await CodeCaseScanService(db).scan(project_id=pa)
            assert (r.created, r.skipped, r.project_id) == (1, 2, pa)
            cases = await _by_func(db)
            assert set(cases) == {"test_a1"}
            assert cases["test_a1"].project_id == pa

            # 全量扫描补齐其他项目和全局用例
            r = await CodeCaseScanService(db).scan()
            assert (r.created, r.updated, r.skipped) == (2, 1, 0)

            # 磁盘上删掉 B1 和 A1：按 A 扫描只软删 A1，B1 保持不变
            _write(root, _case("test_g1", "G1"))
            r = await CodeCaseScanService(db).scan(project_id=pa)
            assert (r.deleted, r.skipped) == (1, 1)
            cases = await _by_func(db)
            assert cases["test_a1"].is_deleted is True
            assert cases["test_b1"].is_deleted is False
            assert cases["test_g1"].is_deleted is False
        finally:
            await db.close()
            await engine.dispose()

    asyncio.run(run())


def test_scan_project_moves_case_out(tmp_path, monkeypatch):
    """原属当前项目的用例 @case 改到别的项目，按当前项目扫描时随之迁出"""
    async def run():
        root, db, engine, pa, pb = await _setup(tmp_path, monkeypatch)
        try:
            _write(root, _case("test_x", "X", "项目A"))
            await CodeCaseScanService(db).scan(project_id=pa)

            _write(root, _case("test_x", "X", "项目B"))
            r = await CodeCaseScanService(db).scan(project_id=pa)
            assert (r.updated, r.deleted, r.skipped) == (1, 0, 0)
            assert (await _by_func(db))["test_x"].project_id == pb
        finally:
            await db.close()
            await engine.dispose()

    asyncio.run(run())


def test_scan_unknown_project(tmp_path, monkeypatch):
    async def run():
        _, db, engine, _, _ = await _setup(tmp_path, monkeypatch)
        try:
            with pytest.raises(ResourceNotFoundError):
                await CodeCaseScanService(db).scan(project_id=999)
        finally:
            await db.close()
            await engine.dispose()

    asyncio.run(run())
