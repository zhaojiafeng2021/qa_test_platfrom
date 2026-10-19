"""
项目相关的数据库操作
"""
from datetime import datetime, timedelta
from typing import Optional, Sequence
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.project import Project, ProjectStatus
from app.db.models.project_member import ProjectMember, ProjectRole
from app.db.models.user import User
from app.db.models.environment import Environment
from app.db.models.code_case import CodeTestCase, CodeCaseExecution
from app.db.models.test_plan import TestPlan, PlanRun


class ProjectRepository:
    """项目数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, project_id: int) -> Optional[Project]:
        """根据ID获取项目（排除已删除）"""
        result = await self.db.execute(
            select(Project).where(
                and_(Project.id == project_id, Project.status != ProjectStatus.DELETED)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Optional[Project]:
        """根据项目代码获取项目"""
        result = await self.db.execute(
            select(Project).where(
                and_(Project.code == code, Project.status != ProjectStatus.DELETED)
            )
        )
        return result.scalar_one_or_none()

    async def code_exists(self, code: str) -> bool:
        """检查项目代码是否存在"""
        result = await self.db.execute(
            select(Project.id).where(Project.code == code)
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        code: str,
        name: str,
        owner_id: int,
        description: Optional[str] = None,
        icon: Optional[str] = None,
        color: Optional[str] = None,
    ) -> Project:
        """创建项目"""
        project = Project(
            code=code,
            name=name,
            owner_id=owner_id,
            description=description,
            icon=icon,
            color=color,
            status=ProjectStatus.ACTIVE,
            created_by=owner_id,
            updated_by=owner_id,
        )
        self.db.add(project)
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def update(self, project: Project, updated_by: int, **fields) -> Project:
        """更新项目"""
        for key, value in fields.items():
            setattr(project, key, value)
        project.updated_by = updated_by
        await self.db.flush()
        await self.db.refresh(project)
        return project

    async def soft_delete(self, project: Project) -> None:
        """软删除项目（标记为deleted状态）"""
        project.status = ProjectStatus.DELETED
        await self.db.flush()

    async def list_for_user(
        self,
        user_id: int,
        is_superuser: bool,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[Sequence[Project], int]:
        """
        列出用户可见的项目
        - 超管：可见全部
        - 普通用户：可见其为成员的项目 + 公开项目(is_public=true)

        Returns:
            (项目列表, 总数)
        """
        conditions = [Project.status != ProjectStatus.DELETED]

        if status:
            conditions = [Project.status == status]

        if keyword:
            conditions.append(Project.name.ilike(f"%{keyword}%"))

        base = select(Project).where(and_(*conditions))

        # 非超管：返回其为成员的项目 + 公开项目
        if not is_superuser:
            member_subq = select(ProjectMember.project_id).where(
                ProjectMember.user_id == user_id
            )
            base = base.where(
                or_(
                    Project.id.in_(member_subq),  # 用户是成员
                    Project.is_public == True      # 或者是公开项目
                )
            )

        # 统计总数
        count_result = await self.db.execute(
            select(func.count()).select_from(base.subquery())
        )
        total = count_result.scalar_one()

        # 分页查询
        result = await self.db.execute(
            base.order_by(Project.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return result.scalars().all(), total


    async def get_dashboard_summary(self, project_id: int) -> dict:
        """Return real project aggregates used by the dashboard (code-case platform)."""
        now = datetime.utcnow()
        week_start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        async def count(model, *conditions) -> int:
            result = await self.db.execute(
                select(func.count()).select_from(model).where(*conditions)
            )
            return int(result.scalar_one())

        code_case_count = await count(
            CodeTestCase,
            CodeTestCase.is_deleted == False,
            CodeTestCase.project_id == project_id,
        )
        code_case_weekly_added = await count(
            CodeTestCase,
            CodeTestCase.is_deleted == False,
            CodeTestCase.created_at >= week_start,
            CodeTestCase.project_id == project_id,
        )
        test_plan_count = await count(
            TestPlan,
            TestPlan.project_id == project_id,
            TestPlan.is_deleted == False,
        )
        environment_count = await count(Environment, Environment.project_id == project_id)

        execution_count = await count(
            CodeCaseExecution,
            CodeCaseExecution.case_id.in_(
                select(CodeTestCase.id).where(CodeTestCase.project_id == project_id)
            ),
        )

        recent_completed = (
            select(CodeCaseExecution.status)
            .where(
                CodeCaseExecution.case_id.in_(
                    select(CodeTestCase.id).where(CodeTestCase.project_id == project_id)
                ),
                CodeCaseExecution.status.in_(("passed", "failed", "error", "timeout")),
            )
            .order_by(CodeCaseExecution.created_at.desc())
            .limit(50)
        )
        completed_statuses = list((await self.db.execute(recent_completed)).scalars().all())
        passed_execution_count = sum(status == "passed" for status in completed_statuses)
        completed_execution_count = len(completed_statuses)
        recent_pass_rate = (
            round(passed_execution_count * 100 / completed_execution_count, 1)
            if completed_execution_count
            else 0
        )

        recent_stmt = (
            select(CodeCaseExecution)
            .where(
                CodeCaseExecution.case_id.in_(
                    select(CodeTestCase.id).where(CodeTestCase.project_id == project_id)
                )
            )
            .order_by(CodeCaseExecution.created_at.desc())
            .limit(8)
        )
        executions = (await self.db.execute(recent_stmt)).scalars().all()
        recent_executions = [
            {
                "id": execution.id,
                "case_id": execution.case_id,
                "case_name": execution.case_name,
                "module": execution.module,
                "level": execution.level,
                "status": execution.status,
                "duration_ms": execution.duration_ms,
                "created_at": execution.created_at,
            }
            for execution in executions
        ]

        recent_plan_runs_stmt = (
            select(PlanRun)
            .where(PlanRun.project_id == project_id)
            .order_by(PlanRun.created_at.desc())
            .limit(5)
        )
        plan_runs = (await self.db.execute(recent_plan_runs_stmt)).scalars().all()
        recent_plan_runs = [
            {
                "id": run.id,
                "plan_id": run.plan_id,
                "status": run.status,
                "total_items": run.total_items,
                "passed_items": run.passed_items,
                "failed_items": run.failed_items,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
            }
            for run in plan_runs
        ]

        return {
            "code_case_count": code_case_count,
            "code_case_weekly_added": code_case_weekly_added,
            "test_plan_count": test_plan_count,
            "environment_count": environment_count,
            "execution_count": execution_count,
            "completed_execution_count": completed_execution_count,
            "passed_execution_count": passed_execution_count,
            "recent_pass_rate": recent_pass_rate,
            "recent_executions": recent_executions,
            "recent_plan_runs": recent_plan_runs,
        }

    # ============ 成员 ============
    async def get_member(self, project_id: int, user_id: int) -> Optional[ProjectMember]:
        """获取项目成员"""
        result = await self.db.execute(
            select(ProjectMember).where(
                and_(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == user_id,
                    ProjectMember.is_deleted == False,
                )
            )
        )
        return result.scalar_one_or_none()

    async def add_member(
        self,
        project_id: int,
        user_id: int,
        role: ProjectRole,
        invited_by: Optional[int] = None,
        role_id: Optional[int] = None,
    ) -> ProjectMember:
        """添加项目成员"""
        member = ProjectMember(
            project_id=project_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
            role_id=role_id,
        )
        self.db.add(member)
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def update_member_role(
        self,
        member: ProjectMember,
        role: ProjectRole,
        role_id: Optional[int] = None,
    ) -> ProjectMember:
        """更新成员角色"""
        member.role = role
        member.role_id = role_id
        await self.db.flush()
        await self.db.refresh(member)
        return member

    async def remove_member(self, member: ProjectMember) -> None:
        """移除成员（软删除）"""
        member.soft_delete()
        await self.db.flush()

    async def list_members(self, project_id: int) -> Sequence[tuple[ProjectMember, User]]:
        """列出项目成员（含用户信息）"""
        result = await self.db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id, ProjectMember.is_deleted == False)
            .order_by(ProjectMember.created_at.asc())
        )
        return result.all()

    async def count_members(self, project_id: int) -> int:
        """统计项目成员数"""
        result = await self.db.execute(
            select(func.count()).select_from(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.is_deleted == False,
            )
        )
        return result.scalar_one()

    async def count_owners(self, project_id: int) -> int:
        """统计项目负责人数量"""
        result = await self.db.execute(
            select(func.count()).select_from(ProjectMember).where(
                and_(
                    ProjectMember.project_id == project_id,
                    ProjectMember.role == ProjectRole.OWNER,
                    ProjectMember.is_deleted == False,
                )
            )
        )
        return result.scalar_one()
