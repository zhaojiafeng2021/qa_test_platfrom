"""Database access for notification rules, channels, and durable deliveries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.notification import NotificationChannel, NotificationDelivery
from app.db.models.permission import Role
from app.db.models.project_member import ProjectMember, ProjectRole
from app.db.models.report import NotificationRule
from app.db.models.user import User, UserStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_channel(self, channel_id: int) -> NotificationChannel | None:
        return (await self.db.execute(
            select(NotificationChannel).where(NotificationChannel.id == channel_id)
        )).scalar_one_or_none()

    async def list_channels(self, project_id: int) -> list[NotificationChannel]:
        rows = await self.db.execute(
            select(NotificationChannel)
            .where(NotificationChannel.project_id == project_id)
            .order_by(NotificationChannel.enabled.desc(), NotificationChannel.id)
        )
        return list(rows.scalars().all())

    async def channel_name_exists(self, project_id: int, name: str, exclude_id: int | None = None) -> bool:
        stmt = select(NotificationChannel.id).where(
            NotificationChannel.project_id == project_id,
            func.lower(NotificationChannel.name) == name.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(NotificationChannel.id != exclude_id)
        return (await self.db.execute(stmt)).scalar_one_or_none() is not None

    async def create_channel(self, **values) -> NotificationChannel:
        channel = NotificationChannel(**values)
        self.db.add(channel)
        await self.db.flush()
        return channel

    async def channel_rule_count(self, channel_id: int) -> int:
        return int((await self.db.execute(
            select(func.count(NotificationRule.id)).where(NotificationRule.channel_id == channel_id)
        )).scalar_one())

    async def get_rule(self, rule_id: int) -> NotificationRule | None:
        return (await self.db.execute(
            select(NotificationRule).options(selectinload(NotificationRule.channel)).where(NotificationRule.id == rule_id)
        )).scalar_one_or_none()

    async def list_rules(self, project_id: int) -> list[NotificationRule]:
        rows = await self.db.execute(
            select(NotificationRule)
            .options(selectinload(NotificationRule.channel))
            .where(NotificationRule.project_id == project_id)
            .order_by(NotificationRule.enabled.desc(), NotificationRule.id.desc())
        )
        return list(rows.scalars().all())

    async def enabled_rules_for_event(self, project_id: int, event_type: str) -> list[NotificationRule]:
        rows = await self.db.execute(
            select(NotificationRule)
            .options(selectinload(NotificationRule.channel))
            .where(
                NotificationRule.project_id == project_id,
                NotificationRule.event_type == event_type,
                NotificationRule.enabled.is_(True),
            )
            .order_by(NotificationRule.id)
        )
        return list(rows.scalars().all())

    async def get_rules_by_ids(
        self, rule_ids: list[int], project_id: int, event_type: str
    ) -> list[NotificationRule]:
        """Get specific rules by IDs (only enabled, matching project and event type)."""
        rows = await self.db.execute(
            select(NotificationRule)
            .options(selectinload(NotificationRule.channel))
            .where(
                NotificationRule.id.in_(rule_ids),
                NotificationRule.project_id == project_id,
                NotificationRule.event_type == event_type,
                NotificationRule.enabled.is_(True),
            )
            .order_by(NotificationRule.id)
        )
        return list(rows.scalars().all())

    async def create_rule(self, **values) -> NotificationRule:
        rule = NotificationRule(**values)
        self.db.add(rule)
        await self.db.flush()
        return rule

    async def project_member_user_ids(self, project_id: int) -> set[int]:
        rows = await self.db.execute(
            select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
        )
        return set(rows.scalars().all())

    async def project_admin_user_ids(self, project_id: int) -> set[int]:
        rows = await self.db.execute(
            select(ProjectMember.user_id)
            .outerjoin(Role, Role.id == ProjectMember.role_id)
            .where(
                ProjectMember.project_id == project_id,
                or_(
                    Role.code == "project_admin",
                    ProjectMember.role.in_([ProjectRole.OWNER, ProjectRole.ADMIN]),
                ),
            )
        )
        return set(rows.scalars().all())

    async def users_with_feishu_identity(self, user_ids: set[int]) -> list[User]:
        if not user_ids:
            return []
        rows = await self.db.execute(
            select(User).where(
                User.id.in_(sorted(user_ids)),
                User.status == UserStatus.ACTIVE,
            )
        )
        return list(rows.scalars().all())

    async def get_delivery(self, delivery_id: int, lock: bool = False) -> NotificationDelivery | None:
        stmt = select(NotificationDelivery).where(NotificationDelivery.id == delivery_id)
        if lock:
            stmt = stmt.with_for_update(skip_locked=True)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create_delivery(self, **values) -> NotificationDelivery:
        delivery = NotificationDelivery(**values)
        self.db.add(delivery)
        await self.db.flush()
        return delivery

    async def create_delivery_idempotent(self, **values) -> NotificationDelivery | None:
        statement = (
            insert(NotificationDelivery)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_notification_delivery_event")
            .returning(NotificationDelivery.id)
        )
        delivery_id = (await self.db.execute(statement)).scalar_one_or_none()
        if delivery_id is None:
            return None
        return await self.get_delivery(delivery_id)

    async def list_deliveries(
        self,
        project_id: int,
        page: int,
        page_size: int,
        event_type: str | None = None,
        status: str | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
    ) -> tuple[int, list[tuple[NotificationDelivery, str | None, str | None]]]:
        conditions = [NotificationDelivery.project_id == project_id]
        if event_type:
            conditions.append(NotificationDelivery.event_type == event_type)
        if status:
            conditions.append(NotificationDelivery.status == status)
        if started_from:
            conditions.append(NotificationDelivery.created_at >= started_from)
        if started_to:
            conditions.append(NotificationDelivery.created_at <= started_to)
        total = int((await self.db.execute(
            select(func.count(NotificationDelivery.id)).where(*conditions)
        )).scalar_one())
        rows = await self.db.execute(
            select(NotificationDelivery, NotificationRule.name, NotificationChannel.name)
            .outerjoin(NotificationRule, NotificationRule.id == NotificationDelivery.rule_id)
            .outerjoin(NotificationChannel, NotificationChannel.id == NotificationDelivery.channel_id)
            .where(*conditions)
            .order_by(NotificationDelivery.created_at.desc(), NotificationDelivery.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return total, list(rows.all())

    async def due_delivery_ids(self, limit: int = 100) -> list[int]:
        now = utcnow()
        stale = now - timedelta(minutes=5)
        rows = await self.db.execute(
            select(NotificationDelivery.id)
            .where(
                or_(
                    NotificationDelivery.status == "pending",
                    (NotificationDelivery.status == "retrying") & (NotificationDelivery.next_attempt_at <= now),
                    (NotificationDelivery.status == "sending") & (NotificationDelivery.updated_at <= stale),
                )
            )
            .order_by(NotificationDelivery.next_attempt_at.asc().nullsfirst(), NotificationDelivery.id)
            .limit(limit)
        )
        return list(rows.scalars().all())
