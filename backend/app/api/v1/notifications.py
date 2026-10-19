"""Notification center API."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_project_permission
from app.core.errors import success_response
from app.db.base import get_db
from app.modules.auth.schemas import CurrentUser
from app.modules.notification.schemas import (
    ChannelCreate,
    ChannelTestRequest,
    ChannelUpdate,
    EventEmitRequest,
    RuleCreate,
    RuleUpdate,
)
from app.modules.notification.service import NotificationService


router = APIRouter(prefix="/projects/{project_id}/notifications", tags=["飞书通知中心"])


@router.get("/catalog", dependencies=[Depends(require_project_permission("notification:read"))])
async def get_catalog(project_id: int):
    return success_response(data=NotificationService.catalog())


@router.get("/channels", dependencies=[Depends(require_project_permission("notification:read"))])
async def list_channels(project_id: int, db: AsyncSession = Depends(get_db)):
    items = await NotificationService(db).list_channels(project_id)
    return success_response(data=[item.model_dump(mode="json") for item in items])


@router.post("/channels", status_code=201, dependencies=[Depends(require_project_permission("notification:manage"))])
async def create_channel(
    project_id: int,
    data: ChannelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    item = await NotificationService(db).create_channel(project_id, data, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="Webhook 已添加")


@router.put("/channels/{channel_id}", dependencies=[Depends(require_project_permission("notification:manage"))])
async def update_channel(
    project_id: int,
    channel_id: int,
    data: ChannelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    item = await NotificationService(db).update_channel(project_id, channel_id, data, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="Webhook 已更新")


@router.delete("/channels/{channel_id}", dependencies=[Depends(require_project_permission("notification:manage"))])
async def delete_channel(
    project_id: int,
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    await NotificationService(db).delete_channel(project_id, channel_id, current_user.id)
    return success_response(message="Webhook 已删除")


@router.post("/channels/{channel_id}/test", dependencies=[Depends(require_project_permission("notification:manage"))])
async def test_channel(
    project_id: int,
    channel_id: int,
    data: ChannelTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    result = await NotificationService(db).test_channel(
        project_id, channel_id, data.message, current_user.id
    )
    return success_response(data=result, message="测试发送完成")


@router.get("/rules", dependencies=[Depends(require_project_permission("notification:read"))])
async def list_rules(project_id: int, db: AsyncSession = Depends(get_db)):
    items = await NotificationService(db).list_rules(project_id)
    return success_response(data=[item.model_dump(mode="json") for item in items])


@router.post("/rules", status_code=201, dependencies=[Depends(require_project_permission("notification:manage"))])
async def create_rule(
    project_id: int,
    data: RuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    item = await NotificationService(db).create_rule(project_id, data, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="通知规则已创建")


@router.put("/rules/{rule_id}", dependencies=[Depends(require_project_permission("notification:manage"))])
async def update_rule(
    project_id: int,
    rule_id: int,
    data: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    item = await NotificationService(db).update_rule(project_id, rule_id, data, current_user.id)
    return success_response(data=item.model_dump(mode="json"), message="通知规则已更新")


@router.delete("/rules/{rule_id}", dependencies=[Depends(require_project_permission("notification:manage"))])
async def delete_rule(
    project_id: int,
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    await NotificationService(db).delete_rule(project_id, rule_id, current_user.id)
    return success_response(message="通知规则已删除")


@router.get("/deliveries", dependencies=[Depends(require_project_permission("notification:read"))])
async def list_deliveries(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    event_type: str | None = None,
    status: str | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    db: AsyncSession = Depends(get_db),
):
    result = await NotificationService(db).list_deliveries(
        project_id, page, page_size, event_type, status, started_from, started_to
    )
    return success_response(data={
        "total": result["total"],
        "items": [item.model_dump(mode="json") for item in result["items"]],
        "page": page,
        "page_size": page_size,
    })


@router.post("/events", dependencies=[Depends(require_project_permission("notification:manage"))])
async def emit_event(
    project_id: int,
    data: EventEmitRequest,
    db: AsyncSession = Depends(get_db),
):
    service = NotificationService(db)
    delivery_ids = await service.emit_event(
        project_id, data.event_id, data.event_type, data.context, data.summary
    )
    await db.commit()
    await service.wake_deliveries(delivery_ids)
    return success_response(data={"delivery_ids": delivery_ids}, message="通知事件已受理")
