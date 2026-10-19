"""
环境管理数据访问层
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import Environment, Variable
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentUpdate,
    VariableCreate,
    VariableUpdate,
)


class EnvironmentRepository:
    """环境数据访问"""

    @staticmethod
    async def create(db: AsyncSession, project_id: int, data: EnvironmentCreate, user_id: int) -> Environment:
        """创建环境"""
        env = Environment(
            project_id=project_id,
            name=data.name,
            display_name=data.display_name,
            description=data.description,
            base_url=data.base_url,
            sort_order=data.sort_order,
            is_active=data.is_active,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(env)
        await db.commit()
        await db.refresh(env)
        return env

    @staticmethod
    async def get_by_id(db: AsyncSession, env_id: int) -> Optional[Environment]:
        """根据ID获取环境"""
        result = await db.execute(
            select(Environment).where(Environment.id == env_id, Environment.is_deleted == False)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_project(db: AsyncSession, project_id: int) -> List[Environment]:
        """获取项目的所有环境"""
        result = await db.execute(
            select(Environment)
            .where(Environment.project_id == project_id, Environment.is_deleted == False)
            .order_by(Environment.sort_order, Environment.id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_name(db: AsyncSession, project_id: int, name: str) -> Optional[Environment]:
        """根据名称获取环境"""
        result = await db.execute(
            select(Environment).where(
                and_(
                    Environment.project_id == project_id,
                    Environment.name == name,
                    Environment.is_deleted == False,
                )
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update(db: AsyncSession, env: Environment, data: EnvironmentUpdate, user_id: int) -> Environment:
        """更新环境"""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(env, field, value)
        env.updated_by = user_id
        await db.commit()
        await db.refresh(env)
        return env

    @staticmethod
    async def delete(db: AsyncSession, env: Environment, user_id: int) -> None:
        """软删除环境"""
        env.soft_delete(user_id)
        await db.commit()


class VariableRepository:
    """变量数据访问"""

    @staticmethod
    async def create(db: AsyncSession, project_id: int, data: VariableCreate, user_id: int) -> Variable:
        """创建变量"""
        var = Variable(
            project_id=project_id,
            environment_id=data.environment_id,
            scope=data.scope,
            key=data.key,
            value=data.value,
            description=data.description,
            is_secret=data.is_secret,
            is_active=data.is_active,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(var)
        await db.commit()
        await db.refresh(var)
        return var

    @staticmethod
    async def get_by_id(db: AsyncSession, var_id: int) -> Optional[Variable]:
        """根据ID获取变量"""
        result = await db.execute(
            select(Variable).where(Variable.id == var_id, Variable.is_deleted == False)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_project(
        db: AsyncSession,
        project_id: int,
        scope: Optional[str] = None,
        environment_id: Optional[int] = None
    ) -> List[Variable]:
        """获取项目的变量"""
        conditions = [Variable.project_id == project_id, Variable.is_deleted == False]
        if scope:
            conditions.append(Variable.scope == scope)
        if environment_id is not None:
            conditions.append(Variable.environment_id == environment_id)

        result = await db.execute(
            select(Variable).where(and_(*conditions)).order_by(Variable.key)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_by_key(
        db: AsyncSession,
        project_id: int,
        key: str,
        scope: str,
        environment_id: Optional[int] = None
    ) -> Optional[Variable]:
        """根据键名获取变量"""
        conditions = [
            Variable.project_id == project_id,
            Variable.key == key,
            Variable.scope == scope,
            Variable.is_deleted == False,
        ]
        if environment_id is not None:
            conditions.append(Variable.environment_id == environment_id)

        result = await db.execute(select(Variable).where(and_(*conditions)))
        return result.scalar_one_or_none()

    @staticmethod
    async def update(db: AsyncSession, var: Variable, data: VariableUpdate, user_id: int) -> Variable:
        """更新变量"""
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(var, field, value)
        var.updated_by = user_id
        await db.commit()
        await db.refresh(var)
        return var

    @staticmethod
    async def delete(db: AsyncSession, var: Variable, user_id: int) -> None:
        """软删除变量"""
        var.soft_delete(user_id)
        await db.commit()

    @staticmethod
    async def delete_by_environment(db: AsyncSession, environment_id: int, user_id: int) -> None:
        """软删除环境下的所有变量"""
        now = datetime.utcnow()
        await db.execute(
            update(Variable)
            .where(Variable.environment_id == environment_id, Variable.is_deleted == False)
            .values(is_deleted=True, deleted_at=now, updated_by=user_id)
        )
        await db.commit()
