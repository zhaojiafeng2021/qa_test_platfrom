"""
认证相关的数据库操作
"""
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User, UserStatus
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember, ProjectRole
from app.core.security import hash_password


class UserRepository:
    """用户数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """根据ID获取用户"""
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        """根据邮箱获取用户"""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_feishu_open_id(self, feishu_open_id: str) -> Optional[User]:
        """根据飞书OpenID获取用户"""
        result = await self.db.execute(
            select(User).where(User.feishu_open_id == feishu_open_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        username: str,
        email: str,
        password: Optional[str] = None,
        full_name: Optional[str] = None,
        feishu_open_id: Optional[str] = None,
        feishu_union_id: Optional[str] = None,
        avatar_url: Optional[str] = None
    ) -> User:
        """创建用户"""
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password) if password else None,
            full_name=full_name,
            feishu_open_id=feishu_open_id,
            feishu_union_id=feishu_union_id,
            avatar_url=avatar_url,
            status=UserStatus.ACTIVE
        )

        self.db.add(user)
        await self.db.flush()
        await self.db.refresh(user)

        return user

    async def update_feishu_info(
        self,
        user: User,
        feishu_open_id: str,
        feishu_union_id: Optional[str] = None,
        avatar_url: Optional[str] = None,
        full_name: Optional[str] = None,
    ) -> None:
        """绑定/更新飞书信息到已有用户"""
        user.feishu_open_id = feishu_open_id
        if feishu_union_id:
            user.feishu_union_id = feishu_union_id
        if avatar_url:
            user.avatar_url = avatar_url
        if full_name and not user.full_name:
            user.full_name = full_name
        await self.db.flush()

    async def update_last_login(self, user_id: int, ip_address: str) -> None:
        """更新最后登录时间和IP"""
        from datetime import datetime

        user = await self.get_by_id(user_id)
        if user:
            user.last_login_at = datetime.utcnow().isoformat()
            user.last_login_ip = ip_address
            await self.db.flush()

    async def username_exists(self, username: str) -> bool:
        """检查用户名是否存在"""
        result = await self.db.execute(
            select(User.id).where(User.username == username)
        )
        return result.scalar_one_or_none() is not None

    async def email_exists(self, email: str) -> bool:
        """检查邮箱是否存在"""
        result = await self.db.execute(
            select(User.id).where(User.email == email)
        )
        return result.scalar_one_or_none() is not None

    async def get_all_project_ids(self) -> List[int]:
        """获取所有活跃项目的ID列表"""
        from app.db.models.project import ProjectStatus
        result = await self.db.execute(
            select(Project.id).where(Project.status == ProjectStatus.ACTIVE)
        )
        return list(result.scalars().all())

    async def get_user_project_ids(self, user_id: int) -> List[int]:
        """获取用户已加入的项目ID列表"""
        result = await self.db.execute(
            select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
        )
        return list(result.scalars().all())

    async def add_user_to_projects_as_viewer(self, user_id: int, project_ids: List[int]) -> None:
        """将用户以 viewer 角色加入指定项目"""
        for pid in project_ids:
            member = ProjectMember(
                project_id=pid,
                user_id=user_id,
                role=ProjectRole.VIEWER,
            )
            self.db.add(member)
        await self.db.flush()

    async def get_names_by_ids(self, user_ids: List[int]) -> dict[int, str]:
        """批量获取用户显示名称（full_name 优先，否则 username），返回 {user_id: display_name}"""
        if not user_ids:
            return {}
        unique_ids = list(set(uid for uid in user_ids if uid is not None))
        if not unique_ids:
            return {}
        result = await self.db.execute(
            select(User.id, User.full_name, User.username).where(User.id.in_(unique_ids))
        )
        return {
            row.id: row.full_name or row.username
            for row in result.all()
        }
