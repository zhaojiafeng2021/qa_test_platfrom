"""
Datetime utilities for timezone conversion and serialization.
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# 北京时区
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def to_beijing_time(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert UTC naive datetime to Beijing timezone-aware datetime.

    Args:
        dt: UTC naive datetime (as stored in database)

    Returns:
        Beijing timezone-aware datetime, or None if input is None
    """
    if dt is None:
        return None
    # Database stores naive UTC, interpret as UTC and convert to Beijing
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ)


def batch_convert_to_beijing(items, *fields: str) -> None:
    """Batch convert datetime fields on Pydantic model instances to Beijing time.

    Mutates items in place, converting specified datetime fields from UTC to Beijing.

    Args:
        items: Sequence of Pydantic model instances
        fields: Field names to convert (e.g., 'created_at', 'updated_at')
    """
    for item in items:
        for field in fields:
            value = getattr(item, field, None)
            if value is not None and isinstance(value, datetime):
                setattr(item, field, to_beijing_time(value))
