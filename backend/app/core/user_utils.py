"""
Shared utility for populating user display names on response schemas.
"""
from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repository import UserRepository


async def get_user_name(db: AsyncSession, user_id: int) -> str:
    """Get display name for a single user ID.

    Returns the user's display name or "未知用户" if not found.
    """
    if user_id is None:
        return "未知用户"

    user_repo = UserRepository(db)
    name_map = await user_repo.get_names_by_ids([user_id])
    return name_map.get(user_id, "未知用户")


async def batch_get_user_names(db: AsyncSession, user_ids: list[int]) -> dict[int, str]:
    """Batch-resolve user IDs to display names.

    Returns a dict mapping user_id -> display_name.
    """
    if not user_ids:
        return {}

    user_repo = UserRepository(db)
    return await user_repo.get_names_by_ids(user_ids)


async def populate_user_names(
    db: AsyncSession,
    items: Sequence,
    created_by_field: str = "created_by",
    updated_by_field: str = "updated_by",
) -> None:
    """Batch-resolve user IDs to display names on a list of Pydantic model instances.

    Mutates items in place, setting `created_by_name` and `updated_by_name` fields.
    Items must already have those Optional[str] fields defined.
    """
    user_ids: set[int] = set()
    for item in items:
        cid = getattr(item, created_by_field, None)
        uid = getattr(item, updated_by_field, None)
        if cid is not None:
            user_ids.add(cid)
        if uid is not None:
            user_ids.add(uid)

    if not user_ids:
        return

    user_repo = UserRepository(db)
    name_map = await user_repo.get_names_by_ids(list(user_ids))

    for item in items:
        cid = getattr(item, created_by_field, None)
        uid = getattr(item, updated_by_field, None)
        if cid is not None and cid in name_map:
            item.created_by_name = name_map[cid]
        if uid is not None and uid in name_map:
            item.updated_by_name = name_map[uid]
