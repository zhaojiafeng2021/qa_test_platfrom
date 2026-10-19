"""WP-08 报告与通知的API接口。"""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_project_permission
from app.core.errors import success_response
from app.modules.auth.schemas import CurrentUser
from app.modules.report.service import NotificationService, ReportService
from app.schemas.report import (
    NotificationRuleCreate,
    NotificationRuleUpdate,
)

router = APIRouter()


# ============ ReportFile APIs ============


@router.post("/projects/{project_id}/reports", status_code=201, dependencies=[Depends(require_project_permission("asset:create"))])
async def create_report(
    project_id: int,
    report_type: str = Query("html", description="html or pdf"),
    plan_run_id: int = Query(..., description="计划运行ID"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建报告文件（同步生成后返回）。"""
    service = ReportService(db)
    result = await service.create_report(
        project_id=project_id,
        report_type=report_type,
        user_id=current_user.id,
        plan_run_id=plan_run_id,
    )
    return success_response(data=result.model_dump(mode="json"))


@router.get("/projects/{project_id}/reports/{report_id}")
async def get_report(
    project_id: int,
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取报告文件信息（含下载URL）。"""
    service = ReportService(db)
    result = await service.get_report(project_id, report_id)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/projects/{project_id}/reports")
async def list_reports(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    report_type: str | None = Query(None, description="html or pdf"),
    started_from: str | None = Query(None, description="ISO格式起始时间"),
    started_to: str | None = Query(None, description="ISO格式结束时间"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """分页列出项目的报告文件（支持类型和日期范围筛选）。"""
    service = ReportService(db)
    result = await service.list_reports(
        project_id, page, page_size, report_type, started_from, started_to
    )
    return success_response(data={
        "total": result["total"],
        "items": [item.model_dump(mode="json") for item in result["items"]],
    })


@router.get("/projects/{project_id}/plan-runs/{plan_run_id}/reports")
async def list_plan_run_reports(
    project_id: int,
    plan_run_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出某个计划运行的所有报告。"""
    service = ReportService(db)
    result = await service.list_reports_by_plan_run(project_id, plan_run_id)
    return success_response(data=[item.model_dump(mode="json") for item in result])


@router.get("/projects/{project_id}/reports/{report_id}/download")
async def download_report(
    project_id: int,
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """下载报告文件内容（MinIO 优先，本地 fallback）。二进制响应，不走统一包装。"""
    service = ReportService(db)
    content, content_type, filename = await service.get_report_content(project_id, report_id)
    # inline 让 HTML 直接在浏览器打开；文件名用 RFC5987 编码兼容中文
    disposition = f"inline; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": disposition},
    )


@router.delete("/projects/{project_id}/reports/{report_id}", dependencies=[Depends(require_project_permission("asset:delete"))])
async def delete_report(
    project_id: int,
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除报告记录及存储文件。"""
    service = ReportService(db)
    await service.delete_report(project_id, report_id)
    return success_response(message="报告已删除")


# ============ NotificationRule APIs ============


@router.post("/projects/{project_id}/notification-rules", status_code=201, dependencies=[Depends(require_project_permission("asset:create"))])
async def create_notification_rule(
    project_id: int,
    data: NotificationRuleCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建通知规则。"""
    service = NotificationService(db)
    result = await service.create_rule(project_id, data, current_user.id)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/projects/{project_id}/notification-rules/{rule_id}")
async def get_notification_rule(
    project_id: int,
    rule_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取通知规则。"""
    service = NotificationService(db)
    result = await service.get_rule(project_id, rule_id)
    return success_response(data=result.model_dump(mode="json"))


@router.get("/projects/{project_id}/notification-rules")
async def list_notification_rules(
    project_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出项目的所有通知规则。"""
    service = NotificationService(db)
    result = await service.list_rules(project_id)
    return success_response(data=[item.model_dump(mode="json") for item in result])


@router.put("/projects/{project_id}/notification-rules/{rule_id}", dependencies=[Depends(require_project_permission("asset:update"))])
async def update_notification_rule(
    project_id: int,
    rule_id: int,
    data: NotificationRuleUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新通知规则。"""
    service = NotificationService(db)
    result = await service.update_rule(project_id, rule_id, data, current_user.id)
    return success_response(data=result.model_dump(mode="json"))


@router.delete("/projects/{project_id}/notification-rules/{rule_id}", dependencies=[Depends(require_project_permission("asset:delete"))])
async def delete_notification_rule(
    project_id: int,
    rule_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除通知规则。"""
    service = NotificationService(db)
    await service.delete_rule(project_id, rule_id)
    return success_response(message="通知规则已删除")


@router.get("/projects/{project_id}/notification-rules/{rule_id}/logs")
async def list_notification_logs(
    project_id: int,
    rule_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """分页列出通知日志。"""
    service = NotificationService(db)
    result = await service.list_logs(project_id, rule_id, page, page_size)
    return success_response(data={
        "total": result["total"],
        "items": [item.model_dump(mode="json") for item in result["items"]],
    })
