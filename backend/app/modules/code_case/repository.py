"""
代码用例 Repository 层
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.code_case import CodeCaseExecution, CodeCaseModule, CodeTestCase


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CodeCaseModuleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, name: str, parent_id: Optional[int], level: int,
                     full_path: str, user_id: Optional[int] = None,
                     sort_order: int = 0, project_id: Optional[int] = None) -> CodeCaseModule:
        now = _now()
        obj = CodeCaseModule(
            name=name, parent_id=parent_id, level=level, full_path=full_path,
            sort_order=sort_order, created_by=user_id, updated_by=user_id,
            created_at=now, updated_at=now, project_id=project_id,
        )
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get(self, module_id: int) -> Optional[CodeCaseModule]:
        r = await self.db.execute(
            select(CodeCaseModule).where(CodeCaseModule.id == module_id)
        )
        return r.scalar_one_or_none()

    async def find_by_parent_and_name(self, parent_id: Optional[int],
                                      name: str,
                                      project_id: Optional[int] = None) -> Optional[CodeCaseModule]:
        """同一父级下按名称查找（层级唯一性判断依据）"""
        stmt = select(CodeCaseModule).where(CodeCaseModule.name == name)
        stmt = stmt.where(CodeCaseModule.parent_id.is_(None)) if parent_id is None \
            else stmt.where(CodeCaseModule.parent_id == parent_id)
        if project_id is not None:
            stmt = stmt.where(CodeCaseModule.project_id == project_id)
        r = await self.db.execute(stmt)
        return r.scalars().first()

    async def list_all(self, project_id: Optional[int] = None,
                       used_only: bool = True) -> list[CodeCaseModule]:
        stmt = select(CodeCaseModule)
        if project_id is not None:
            stmt = stmt.where(CodeCaseModule.project_id == project_id)
        if used_only:
            stmt = stmt.where(CodeCaseModule.is_used.is_(True))
        r = await self.db.execute(
            stmt.order_by(CodeCaseModule.level, CodeCaseModule.sort_order, CodeCaseModule.id)
        )
        return list(r.scalars().all())

    async def list_children(self, parent_id: int) -> list[CodeCaseModule]:
        r = await self.db.execute(
            select(CodeCaseModule).where(CodeCaseModule.parent_id == parent_id)
        )
        return list(r.scalars().all())

    async def update(self, obj: CodeCaseModule, **kwargs) -> CodeCaseModule:
        kwargs["updated_at"] = _now()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: CodeCaseModule) -> None:
        await self.db.delete(obj)
        await self.db.flush()

    async def count_cases(self, module_id: int, include_deleted: bool = False,
                          project_id: Optional[int] = None) -> int:
        stmt = select(func.count()).select_from(CodeTestCase).where(
            CodeTestCase.module_id == module_id
        )
        if not include_deleted:
            stmt = stmt.where(CodeTestCase.is_deleted.is_(False))
        if project_id is not None:
            stmt = stmt.where(CodeTestCase.project_id == project_id)
        r = await self.db.execute(stmt)
        return int(r.scalar() or 0)


class CodeTestCaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> CodeTestCase:
        now = _now()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        obj = CodeTestCase(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get(self, case_id: int) -> Optional[CodeTestCase]:
        r = await self.db.execute(
            select(CodeTestCase).where(CodeTestCase.id == case_id)
        )
        return r.scalar_one_or_none()

    async def find_by_identity(self, file_path: str,
                               function_name: str) -> Optional[CodeTestCase]:
        """按 (文件路径, 函数名) 定位用例——扫描时的幂等键"""
        r = await self.db.execute(
            select(CodeTestCase).where(
                CodeTestCase.file_path == file_path,
                CodeTestCase.function_name == function_name,
            )
        )
        return r.scalars().first()

    async def list_all(self, include_deleted: bool = False) -> list[CodeTestCase]:
        stmt = select(CodeTestCase)
        if not include_deleted:
            stmt = stmt.where(CodeTestCase.is_deleted.is_(False))
        r = await self.db.execute(stmt)
        return list(r.scalars().all())

    async def update(self, obj: CodeTestCase, **kwargs) -> CodeTestCase:
        kwargs["updated_at"] = _now()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def paginate(self, module_id: Optional[int] = None,
                       module_ids: Optional[list[int]] = None,
                       level: Optional[str] = None,
                       keyword: Optional[str] = None,
                       project_id: Optional[int] = None,
                       page: int = 1, page_size: int = 20) -> tuple[int, list[CodeTestCase]]:
        """分页查询（默认过滤软删除）。project_id 有值时严格按项目过滤，不返回未归属用例。"""
        conds = [CodeTestCase.is_deleted.is_(False)]
        if project_id is not None:
            conds.append(CodeTestCase.project_id == project_id)
        if module_id is not None:
            conds.append(CodeTestCase.module_id == module_id)
        if module_ids:
            conds.append(CodeTestCase.module_id.in_(module_ids))
        if level:
            conds.append(CodeTestCase.level == level)
        if keyword:
            like = f"%{keyword}%"
            conds.append(or_(
                CodeTestCase.name.ilike(like),
                CodeTestCase.module.ilike(like),
                CodeTestCase.function_name.ilike(like),
            ))

        total_r = await self.db.execute(
            select(func.count()).select_from(CodeTestCase).where(*conds)
        )
        total = int(total_r.scalar() or 0)

        r = await self.db.execute(
            select(CodeTestCase).where(*conds)
            .order_by(CodeTestCase.module, CodeTestCase.level, CodeTestCase.id)
            .offset((page - 1) * page_size).limit(page_size)
        )
        return total, list(r.scalars().all())

    async def stats(self, project_id: Optional[int] = None) -> dict:
        """用例统计：总数 + 按等级 + 按状态。project_id 有值时严格按项目过滤，不统计未归属用例。"""
        base_conds = [CodeTestCase.is_deleted.is_(False)]
        if project_id is not None:
            base_conds.append(CodeTestCase.project_id == project_id)

        total_r = await self.db.execute(
            select(func.count()).select_from(CodeTestCase).where(*base_conds)
        )
        by_level_r = await self.db.execute(
            select(CodeTestCase.level, func.count())
            .where(*base_conds).group_by(CodeTestCase.level)
        )
        by_status_r = await self.db.execute(
            select(CodeTestCase.status, func.count())
            .where(*base_conds).group_by(CodeTestCase.status)
        )
        module_r = await self.db.execute(
            select(func.count(func.distinct(CodeTestCase.module_id))).where(*base_conds)
        )
        return {
            "total": int(total_r.scalar() or 0),
            "by_level": {k: int(v) for k, v in by_level_r.all()},
            "by_status": {k: int(v) for k, v in by_status_r.all()},
            "module_count": int(module_r.scalar() or 0),
        }

        total_r = await self.db.execute(
            select(func.count()).select_from(CodeTestCase).where(base)
        )
        by_level_r = await self.db.execute(
            select(CodeTestCase.level, func.count())
            .where(base).group_by(CodeTestCase.level)
        )
        by_status_r = await self.db.execute(
            select(CodeTestCase.status, func.count())
            .where(base).group_by(CodeTestCase.status)
        )
        module_r = await self.db.execute(
            select(func.count(func.distinct(CodeTestCase.module_id))).where(base)
        )
        return {
            "total": int(total_r.scalar() or 0),
            "by_level": {k: int(v) for k, v in by_level_r.all()},
            "by_status": {k: int(v) for k, v in by_status_r.all()},
            "module_count": int(module_r.scalar() or 0),
        }

    async def list_by_ids(self, case_ids: list[int]) -> list[CodeTestCase]:
        if not case_ids:
            return []
        r = await self.db.execute(
            select(CodeTestCase).where(
                CodeTestCase.id.in_(case_ids),
                CodeTestCase.is_deleted.is_(False),
            )
        )
        return list(r.scalars().all())

    async def list_by_module_ids(self, module_ids: list[int]) -> list[CodeTestCase]:
        if not module_ids:
            return []
        r = await self.db.execute(
            select(CodeTestCase).where(
                CodeTestCase.module_id.in_(module_ids),
                CodeTestCase.is_deleted.is_(False),
            ).order_by(CodeTestCase.module, CodeTestCase.id)
        )
        return list(r.scalars().all())


class CodeCaseExecutionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> CodeCaseExecution:
        now = _now()
        kwargs.setdefault("created_at", now)
        kwargs.setdefault("updated_at", now)
        obj = CodeCaseExecution(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get(self, exec_id: int) -> Optional[CodeCaseExecution]:
        r = await self.db.execute(
            select(CodeCaseExecution).where(CodeCaseExecution.id == exec_id)
        )
        return r.scalar_one_or_none()

    async def update(self, obj: CodeCaseExecution, **kwargs) -> CodeCaseExecution:
        kwargs["updated_at"] = _now()
        for k, v in kwargs.items():
            setattr(obj, k, v)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def list_by_batch(self, batch_id: str) -> list[CodeCaseExecution]:
        r = await self.db.execute(
            select(CodeCaseExecution)
            .where(CodeCaseExecution.batch_id == batch_id)
            .order_by(CodeCaseExecution.id)
        )
        return list(r.scalars().all())

    async def latest_for_cases(self, case_ids: list[int]) -> dict[int, CodeCaseExecution]:
        """每个用例的最近一次执行记录，用于列表展示最新结果"""
        if not case_ids:
            return {}
        r = await self.db.execute(
            select(CodeCaseExecution)
            .where(CodeCaseExecution.case_id.in_(case_ids))
            .order_by(CodeCaseExecution.case_id, CodeCaseExecution.id.desc())
        )
        latest: dict[int, CodeCaseExecution] = {}
        for row in r.scalars().all():
            latest.setdefault(row.case_id, row)
        return latest

    async def paginate(self, case_id: Optional[int] = None,
                       batch_id: Optional[str] = None,
                       status: Optional[str] = None,
                       page: int = 1, page_size: int = 20
                       ) -> tuple[int, list[CodeCaseExecution]]:
        conds = []
        if case_id is not None:
            conds.append(CodeCaseExecution.case_id == case_id)
        if batch_id:
            conds.append(CodeCaseExecution.batch_id == batch_id)
        if status:
            conds.append(CodeCaseExecution.status == status)

        total_r = await self.db.execute(
            select(func.count()).select_from(CodeCaseExecution).where(*conds)
        )
        r = await self.db.execute(
            select(CodeCaseExecution).where(*conds)
            .order_by(CodeCaseExecution.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return int(total_r.scalar() or 0), list(r.scalars().all())

    async def reap_stale(self, max_seconds: int) -> int:
        """
        把卡住的 pending/running 记录标记为 error

        API 进程在执行中途重启时，内存里的后台任务丢了，
        但库里的记录还停在 running，需要自愈。
        """
        cutoff = _now() - timedelta(seconds=max_seconds)
        r = await self.db.execute(
            select(CodeCaseExecution).where(
                CodeCaseExecution.status.in_(["pending", "running"]),
                CodeCaseExecution.created_at < cutoff,
            )
        )
        stale = list(r.scalars().all())
        for obj in stale:
            await self.update(
                obj, status="error", finished_at=_now(),
                message="执行中断（服务重启或进程异常退出）",
            )
        return len(stale)
