"""
环境管理业务逻辑层
"""
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.environment.repository import EnvironmentRepository, VariableRepository
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentUpdate,
    EnvironmentInfo,
    VariableCreate,
    VariableUpdate,
    VariableInfo,
    VariableInfoMasked,
)
from app.core.errors import ErrorCode, ValidationError, ResourceNotFoundError


class EnvironmentService:
    """环境管理服务"""

    @staticmethod
    async def create_environment(
        db: AsyncSession,
        project_id: int,
        data: EnvironmentCreate,
        user_id: int
    ) -> EnvironmentInfo:
        """创建环境"""
        # 检查环境名称是否重复
        existing = await EnvironmentRepository.get_by_name(db, project_id, data.name)
        if existing:
            raise ValidationError(
                ErrorCode.VALIDATION_ERROR,
                f"环境名称 '{data.name}' 已存在"
            )

        env = await EnvironmentRepository.create(db, project_id, data, user_id)
        return EnvironmentInfo.model_validate(env)

    @staticmethod
    async def get_environment(db: AsyncSession, env_id: int) -> EnvironmentInfo:
        """获取环境详情"""
        env = await EnvironmentRepository.get_by_id(db, env_id)
        if not env:
            raise ValidationError(ErrorCode.NOT_FOUND, "环境不存在")
        return EnvironmentInfo.model_validate(env)

    @staticmethod
    async def list_environments(db: AsyncSession, project_id: int) -> List[EnvironmentInfo]:
        """获取项目的所有环境"""
        envs = await EnvironmentRepository.get_by_project(db, project_id)
        return [EnvironmentInfo.model_validate(e) for e in envs]

    @staticmethod
    async def update_environment(
        db: AsyncSession,
        env_id: int,
        data: EnvironmentUpdate,
        user_id: int
    ) -> EnvironmentInfo:
        """更新环境"""
        env = await EnvironmentRepository.get_by_id(db, env_id)
        if not env:
            raise ValidationError(ErrorCode.NOT_FOUND, "环境不存在")

        env = await EnvironmentRepository.update(db, env, data, user_id)
        return EnvironmentInfo.model_validate(env)

    @staticmethod
    async def delete_environment(db: AsyncSession, env_id: int, user_id: int) -> None:
        """删除环境"""
        env = await EnvironmentRepository.get_by_id(db, env_id)
        if not env:
            raise ValidationError(ErrorCode.NOT_FOUND, "环境不存在")

        # 软删除环境下的所有变量
        await VariableRepository.delete_by_environment(db, env_id, user_id)

        # 软删除环境
        await EnvironmentRepository.delete(db, env, user_id)


class VariableService:
    """变量管理服务"""

    @staticmethod
    async def create_variable(
        db: AsyncSession,
        project_id: int,
        data: VariableCreate,
        user_id: int
    ) -> VariableInfo:
        """创建变量"""
        # 验证scope和environment_id的关系
        if data.scope == "environment" and not data.environment_id:
            raise ValidationError(ErrorCode.VALIDATION_ERROR, "环境变量必须指定environment_id")
        if data.scope == "global" and data.environment_id:
            raise ValidationError(ErrorCode.VALIDATION_ERROR, "全局变量不能指定environment_id")

        # 验证环境是否存在
        if data.environment_id:
            env = await EnvironmentRepository.get_by_id(db, data.environment_id)
            if not env or env.project_id != project_id:
                raise ValidationError(ErrorCode.NOT_FOUND, "环境不存在")

        # 检查变量键名是否重复
        existing = await VariableRepository.get_by_key(
            db, project_id, data.key, data.scope, data.environment_id
        )
        if existing:
            raise ValidationError(
                ErrorCode.VALIDATION_ERROR,
                f"变量 '{data.key}' 在该作用域下已存在"
            )

        var = await VariableRepository.create(db, project_id, data, user_id)
        return VariableInfo.model_validate(var)

    @staticmethod
    async def get_variable(db: AsyncSession, var_id: int, mask_secret: bool = False) -> VariableInfo | VariableInfoMasked:
        """获取变量详情"""
        var = await VariableRepository.get_by_id(db, var_id)
        if not var:
            raise ValidationError(ErrorCode.NOT_FOUND, "变量不存在")

        var_info = VariableInfo.model_validate(var)
        if mask_secret:
            return VariableInfoMasked.from_variable(var_info)
        return var_info

    @staticmethod
    async def list_variables(
        db: AsyncSession,
        project_id: int,
        scope: Optional[str] = None,
        environment_id: Optional[int] = None,
        mask_secret: bool = False
    ) -> List[VariableInfo] | List[VariableInfoMasked]:
        """获取项目的变量列表"""
        variables = await VariableRepository.get_by_project(db, project_id, scope, environment_id)
        var_list = [VariableInfo.model_validate(v) for v in variables]

        if mask_secret:
            return [VariableInfoMasked.from_variable(v) for v in var_list]
        return var_list

    @staticmethod
    async def update_variable(
        db: AsyncSession,
        var_id: int,
        data: VariableUpdate,
        user_id: int
    ) -> VariableInfo:
        """更新变量"""
        var = await VariableRepository.get_by_id(db, var_id)
        if not var:
            raise ValidationError(ErrorCode.NOT_FOUND, "变量不存在")

        var = await VariableRepository.update(db, var, data, user_id)
        return VariableInfo.model_validate(var)

    @staticmethod
    async def delete_variable(db: AsyncSession, var_id: int, user_id: int) -> None:
        """删除变量"""
        var = await VariableRepository.get_by_id(db, var_id)
        if not var:
            raise ValidationError(ErrorCode.NOT_FOUND, "变量不存在")

        await VariableRepository.delete(db, var, user_id)
