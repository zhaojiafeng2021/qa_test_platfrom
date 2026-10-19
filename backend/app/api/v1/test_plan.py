"""WP-07 test plan, schedule, and execution queue APIs."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_client_ip, require_project_permission
from app.core.errors import success_response
from app.db.base import get_db
from app.modules.audit.service import AuditService
from app.modules.auth.schemas import CurrentUser
from app.modules.test_plan.service import ScheduleService, TestPlanService
from app.schemas.test_plan import (
    PlanRunCreate,
    ScheduleCreate,
    ScheduleUpdate,
    TestPlanCreate,
    TestPlanUpdate,
)


router = APIRouter(prefix="/projects/{project_id}", tags=["测试计划与调度"])


def _parse_iso_naive(value: Optional[str]) -> Optional[datetime]:
    """解析 ISO 时间字符串为 naive UTC datetime（created_at 存的是 naive UTC）。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@router.post("/test-plans", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_project_permission("asset:create"))])
async def create_plan(project_id: int, data: TestPlanCreate, request: Request,
                      db: AsyncSession = Depends(get_db),
                      current_user: CurrentUser = Depends(get_current_user)):
    result = await TestPlanService(db).create(project_id, data, current_user.id)
    await AuditService(db).record(
        action="create", resource_type="test_plan",
        user_id=current_user.id, project_id=project_id, resource_id=result.id,
        detail_json={"name": getattr(result, "name", None)},
        ip_address=get_client_ip(request),
    )
    return success_response(data=result.model_dump())


@router.get("/test-plans")
async def list_plans(project_id: int,
                     plan_status: Optional[str] = Query(None, alias="status"),
                     page: int = Query(1, ge=1),
                     page_size: int = Query(20, ge=1, le=100),
                     db: AsyncSession = Depends(get_db),
                     current_user: CurrentUser = Depends(get_current_user)):
    result = await TestPlanService(db).list(project_id, plan_status, page, page_size)
    return success_response(data={
        "total": result["total"],
        "items": [item.model_dump() for item in result["items"]],
    })


@router.get("/test-plans/{plan_id}")
async def get_plan(project_id: int, plan_id: int,
                   db: AsyncSession = Depends(get_db),
                   current_user: CurrentUser = Depends(get_current_user)):
    result = await TestPlanService(db).get(project_id, plan_id)
    dumped = result.model_dump()
    # Debug
    print(f"[DEBUG] notification_rule_ids in result object: {result.notification_rule_ids}")
    print(f"[DEBUG] notification_rule_ids in dumped: {dumped.get('notification_rule_ids')}")
    print(f"[DEBUG] 'notification_rule_ids' in dumped keys: {'notification_rule_ids' in dumped}")
    return success_response(data=dumped)


@router.put("/test-plans/{plan_id}", dependencies=[Depends(require_project_permission("asset:update"))])
async def update_plan(project_id: int, plan_id: int, data: TestPlanUpdate,
                      db: AsyncSession = Depends(get_db),
                      current_user: CurrentUser = Depends(get_current_user)):
    result = await TestPlanService(db).update(project_id, plan_id, data, current_user.id)
    return success_response(data=result.model_dump())


@router.delete("/test-plans/{plan_id}", dependencies=[Depends(require_project_permission("asset:delete"))])
async def delete_plan(project_id: int, plan_id: int, request: Request,
                      db: AsyncSession = Depends(get_db),
                      current_user: CurrentUser = Depends(get_current_user)):
    await TestPlanService(db).delete(project_id, plan_id, current_user.id)
    await AuditService(db).record(
        action="delete", resource_type="test_plan",
        user_id=current_user.id, project_id=project_id, resource_id=plan_id,
        ip_address=get_client_ip(request),
    )
    return success_response(message="测试计划已删除")


@router.post("/test-plans/{plan_id}/runs", dependencies=[Depends(require_project_permission("execution:run"))])
async def run_plan(project_id: int, plan_id: int, data: PlanRunCreate, response: Response,
                   request: Request,
                   idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                   db: AsyncSession = Depends(get_db),
                   current_user: CurrentUser = Depends(get_current_user)):
    result, created = await TestPlanService(db).run(
        project_id, plan_id, data, current_user.id, idempotency_key
    )
    if created:
        await AuditService(db).record(
            action="run", resource_type="test_plan",
            user_id=current_user.id, project_id=project_id, resource_id=plan_id,
            detail_json={"plan_run_id": result.id},
            ip_address=get_client_ip(request),
        )
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    return success_response(data=result.model_dump())


@router.get("/plan-runs")
async def list_plan_runs(project_id: int,
                         plan_id: Optional[int] = Query(None, gt=0),
                         run_status: Optional[str] = Query(None, alias="status"),
                         trigger_type: Optional[str] = Query(None),
                         started_from: Optional[str] = Query(None, description="ISO datetime lower bound (created_at>=)"),
                         started_to: Optional[str] = Query(None, description="ISO datetime upper bound (created_at<=)"),
                         page: int = Query(1, ge=1),
                         page_size: int = Query(20, ge=1, le=100),
                         db: AsyncSession = Depends(get_db),
                         current_user: CurrentUser = Depends(get_current_user)):
    dt_from = _parse_iso_naive(started_from)
    dt_to = _parse_iso_naive(started_to)
    result = await TestPlanService(db).list_runs(
        project_id, plan_id, run_status, page, page_size,
        trigger_type=trigger_type, started_from=dt_from, started_to=dt_to,
    )
    return success_response(data={
        "total": result["total"],
        "items": [item.model_dump() for item in result["items"]],
    })


@router.get("/plan-runs/{run_id}")
async def get_plan_run(project_id: int, run_id: int,
                       db: AsyncSession = Depends(get_db),
                       current_user: CurrentUser = Depends(get_current_user)):
    result = await TestPlanService(db).get_run(project_id, run_id)
    return success_response(data=result.model_dump())


@router.post("/plan-runs/{run_id}/cancel", dependencies=[Depends(require_project_permission("execution:run"))])
async def cancel_plan_run(project_id: int, run_id: int,
                          db: AsyncSession = Depends(get_db),
                          current_user: CurrentUser = Depends(get_current_user)):
    result = await TestPlanService(db).cancel_run(project_id, run_id)
    return success_response(data=result.model_dump())


@router.post("/test-plans/{plan_id}/schedules", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_project_permission("asset:create"))])
async def create_schedule(project_id: int, plan_id: int, data: ScheduleCreate,
                          db: AsyncSession = Depends(get_db),
                          current_user: CurrentUser = Depends(get_current_user)):
    result = await ScheduleService(db).create(project_id, plan_id, data, current_user.id)
    return success_response(data=result.model_dump())


@router.get("/schedules")
async def list_schedules(project_id: int,
                         db: AsyncSession = Depends(get_db),
                         current_user: CurrentUser = Depends(get_current_user)):
    result = await ScheduleService(db).list(project_id)
    return success_response(data=[item.model_dump() for item in result])


@router.put("/schedules/{schedule_id}", dependencies=[Depends(require_project_permission("asset:update"))])
async def update_schedule(project_id: int, schedule_id: int, data: ScheduleUpdate,
                          db: AsyncSession = Depends(get_db),
                          current_user: CurrentUser = Depends(get_current_user)):
    result = await ScheduleService(db).update(project_id, schedule_id, data, current_user.id)
    return success_response(data=result.model_dump())


@router.delete("/schedules/{schedule_id}", dependencies=[Depends(require_project_permission("asset:delete"))])
async def delete_schedule(project_id: int, schedule_id: int, request: Request,
                          db: AsyncSession = Depends(get_db),
                          current_user: CurrentUser = Depends(get_current_user)):
    await ScheduleService(db).delete(project_id, schedule_id, current_user.id)
    await AuditService(db).record(
        action="delete", resource_type="schedule",
        user_id=current_user.id, project_id=project_id, resource_id=schedule_id,
        ip_address=get_client_ip(request),
    )
    return success_response(message="定时任务已删除")


@router.post("/test-plans/{plan_id}/sync-versions", dependencies=[Depends(require_project_permission("asset:update"))])
async def sync_case_versions(project_id: int, plan_id: int,
                              case_ids: Optional[list[int]] = None,
                              db: AsyncSession = Depends(get_db),
                              current_user: CurrentUser = Depends(get_current_user)):
    """同步用例到最新版本（支持批量或全部）"""
    result = await TestPlanService(db).sync_case_versions(project_id, plan_id, case_ids)
    return success_response(data=result.model_dump(), message="用例版本已同步")
