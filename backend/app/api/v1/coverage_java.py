"""JaCoCo 覆盖率采集 API（真实实现）

REST 路由：
- POST   /projects/{pid}/coverage-tasks                 创建任务
- GET    /projects/{pid}/coverage-tasks                 分页列出
- GET    /projects/{pid}/coverage-tasks/{tid}           详情
- PATCH  /projects/{pid}/coverage-tasks/{tid}           更新
- DELETE /projects/{pid}/coverage-tasks/{tid}           删除
- POST   /projects/{pid}/coverage-tasks/{tid}/trigger   触发采集（投递 arq）
- POST   /projects/{pid}/coverage-tasks/{tid}/cancel    取消进行中采集
- GET    /projects/{pid}/coverage-tasks/{tid}/runs      历史 run 列表
- GET    /coverage/runs/{run_id}/reports                单 run 下所有服务报告
- GET    /coverage/reports/{report_id}                  单服务报告详情
- GET    /coverage/reports/{report_id}/files            报告文件列表 + 覆盖汇总
- GET    /coverage/reports/{report_id}/file-content     单文件源码 + 行级覆盖
- GET    /coverage/reports/{report_id}/build-log        构建日志

累积账本：
- GET    /projects/{pid}/coverage-tasks/{tid}/ledger            各服务当前账本 + 历史轮次
- POST   /projects/{pid}/coverage-tasks/{tid}/ledger/new-round  开始新一轮
- GET    /projects/{pid}/coverage-ledgers/{lid}/files           账本文件列表
- GET    /projects/{pid}/coverage-ledgers/{lid}/file?path=      单文件源码 + 行覆盖（含 sources）
- GET    /projects/{pid}/coverage-ledgers/{lid}/diff-coverage   基于账本的增量覆盖率
- GET    /projects/{pid}/coverage-ledgers/{lid}/events          合并历史 + 需回归方法
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_project_permission
from app.core.errors import success_response
from app.modules.auth.schemas import CurrentUser
from app.modules.coverage_java.service import CoverageJavaService
from app.schemas.coverage_java import (
    CoverageTaskCreate,
    CoverageTaskUpdate,
    DiffCoverageResponse,
    LedgerDiffCoverageResponse,
    LedgerEventsResponse,
    LedgerFileContent,
    NewRoundRequest,
    ServiceLedgers,
    TriggerRequest,
)
from app.workers.coverage_java_tasks import (
    abort_coverage_collection,
    enqueue_coverage_collection,
)

router = APIRouter()


# ──────────────────────────────────────────────
# Task CRUD
# ──────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/coverage-tasks",
    status_code=201,
    dependencies=[Depends(require_project_permission("coverage:create"))],
)
async def create_coverage_task(
    project_id: int,
    data: CoverageTaskCreate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建覆盖率任务"""
    service = CoverageJavaService(db)
    task = await service.create_task(
        project_id=project_id,
        data=data.model_dump(),
        owner_id=current_user.id,
    )
    return success_response(data=task, message="创建成功")


@router.get("/projects/{project_id}/coverage-tasks")
async def list_coverage_tasks(
    project_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    branch: Optional[str] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """分页列出覆盖率任务"""
    service = CoverageJavaService(db)
    result = await service.list_tasks(
        project_id=project_id,
        page=page, page_size=page_size,
        keyword=keyword, status=status, branch=branch,
    )
    return success_response(data=result)


@router.get("/projects/{project_id}/coverage-tasks/{task_id}")
async def get_coverage_task(
    project_id: int,
    task_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """任务详情"""
    service = CoverageJavaService(db)
    task = await service.get_task(project_id, task_id)
    return success_response(data=task)


@router.patch(
    "/projects/{project_id}/coverage-tasks/{task_id}",
    dependencies=[Depends(require_project_permission("coverage:update"))],
)
async def update_coverage_task(
    project_id: int,
    task_id: int,
    data: CoverageTaskUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新任务"""
    service = CoverageJavaService(db)
    patch = {k: v for k, v in data.model_dump().items() if v is not None}
    task = await service.update_task(
        project_id=project_id, task_id=task_id,
        data=patch, user_id=current_user.id,
    )
    return success_response(data=task, message="更新成功")


@router.delete(
    "/projects/{project_id}/coverage-tasks/{task_id}",
    dependencies=[Depends(require_project_permission("coverage:delete"))],
)
async def delete_coverage_task(
    project_id: int,
    task_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除任务（软删除）"""
    service = CoverageJavaService(db)
    await service.delete_task(project_id, task_id, current_user.id)
    return success_response(message="覆盖率任务已删除")


# ──────────────────────────────────────────────
# 触发 / 取消
# ──────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/coverage-tasks/{task_id}/trigger",
    status_code=202,
    dependencies=[Depends(require_project_permission("coverage:trigger"))],
)
async def trigger_coverage_task(
    project_id: int,
    task_id: int,
    body: Optional[TriggerRequest] = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """触发覆盖率采集：创建 run + 占位 reports → 投递 arq → 返回 run_id

    body 可省略：commit_sha 不传取分支 HEAD，source 不传用任务的 collection_mode。
    """
    body = body or TriggerRequest()
    service = CoverageJavaService(db)
    run, reports = await service.trigger(
        project_id=project_id, task_id=task_id,
        user_id=current_user.id, trigger_type="manual",
        commit_sha=body.commit_sha, source=body.source,
    )

    # 投递 arq（repo_url 从 task 读出）
    task = await service.get_task(project_id, task_id)
    job_id = await enqueue_coverage_collection(
        task_id=task_id, run_id=run.id, repo_url=task.repo_url,
    )
    if job_id is None:
        # arq 去重（job_id 已存在，说明重复触发）
        from app.core.errors import AppException, ErrorCode
        raise AppException(
            message="相同 run 的采集任务已在队列中，请勿重复触发",
            code=ErrorCode.REVISION_CONFLICT,
            http_status=409,
        )

    return success_response(data={
        "run_id": run.id,
        "job_id": job_id,
        "reports": reports,
    })


@router.post(
    "/projects/{project_id}/coverage-tasks/{task_id}/cancel",
    dependencies=[Depends(require_project_permission("coverage:trigger"))],
)
async def cancel_coverage_task(
    project_id: int,
    task_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """取消进行中的采集：标记 DB cancelled + 尽力 abort arq job"""
    service = CoverageJavaService(db)
    run = await service.cancel(project_id, task_id, current_user.id)
    # 尽力 abort arq job（DB 状态已是 cancelled，worker 循环时也会自检）
    await abort_coverage_collection(run.id)
    return success_response(message="已发送取消信号")


# ──────────────────────────────────────────────
# Run / Report 查询
# ──────────────────────────────────────────────

@router.get("/projects/{project_id}/coverage-tasks/{task_id}/runs")
async def list_task_runs(
    project_id: int,
    task_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出任务的历史 run"""
    service = CoverageJavaService(db)
    result = await service.list_runs(project_id, task_id, page, page_size)
    return success_response(data=result)


@router.get("/coverage/runs/{run_id}/reports")
async def list_run_reports(
    run_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """列出某次 run 下所有服务的 report"""
    service = CoverageJavaService(db)
    reports = await service.list_run_reports(run_id)
    return success_response(data=reports)


@router.get("/coverage/reports/{report_id}")
async def get_coverage_report(
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """单服务报告详情"""
    service = CoverageJavaService(db)
    report = await service.get_report(report_id)
    return success_response(data=report)


@router.get("/coverage/reports/{report_id}/files")
async def list_report_files(
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """报告涉及的文件列表 + 行级覆盖汇总"""
    service = CoverageJavaService(db)
    files = await service.list_report_files(report_id)
    return success_response(data=files)


@router.get("/coverage/reports/{report_id}/file-content")
async def get_report_file_content(
    report_id: int,
    path: str = Query(..., description="文件相对路径"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """单文件源码 + 行级覆盖标记"""
    service = CoverageJavaService(db)
    result = await service.get_file_content(report_id, path)
    return success_response(data=result)


@router.get("/coverage/reports/{report_id}/build-log")
async def get_report_build_log(
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查看构建日志"""
    service = CoverageJavaService(db)
    log = await service.get_build_log(report_id)
    return success_response(data={"report_id": report_id, "log": log})


@router.get("/coverage/reports/{report_id}/diff-coverage")
async def get_report_diff_coverage(
    report_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """计算增量覆盖率（基于 git diff merge-base）

    前置条件：
    - 任务配置了 diff_base_branch
    - workspace 中还保留着该 run 的 clone

    返回：
    - 增量行覆盖率(只统计变更行)
    - 按文件的变更行覆盖明细
    """
    service = CoverageJavaService(db)
    result = await service.get_diff_coverage(report_id)
    return success_response(data=DiffCoverageResponse.model_validate(result).model_dump())


# ──────────────────────────────────────────────
# 累积账本
# ──────────────────────────────────────────────

@router.get("/projects/{project_id}/coverage-tasks/{task_id}/ledger")
async def get_task_ledgers(
    project_id: int,
    task_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """各服务当前账本汇总（轮次、head_commit、来源占比）+ 历史轮次"""
    items = await CoverageJavaService(db).get_task_ledgers(project_id, task_id)
    return success_response(data=[
        ServiceLedgers.model_validate(i, from_attributes=True).model_dump(mode="json") for i in items
    ])


@router.post(
    "/projects/{project_id}/coverage-tasks/{task_id}/ledger/new-round",
    dependencies=[Depends(require_project_permission("coverage:trigger"))],
)
async def start_ledger_new_round(
    project_id: int,
    task_id: int,
    body: Optional[NewRoundRequest] = None,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """开始新一轮：当前账本 is_active=false 只读保留，下一次采集开第 N+1 轮"""
    body = body or NewRoundRequest()
    closed = await CoverageJavaService(db).start_new_round(project_id, task_id, body.service_name)
    return success_response(data={"closed_services": closed}, message="已开始新一轮，下次采集生效")


@router.get("/projects/{project_id}/coverage-ledgers/{ledger_id}/files")
async def list_ledger_files(
    project_id: int,
    ledger_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """账本文件列表 + 行覆盖汇总"""
    files = await CoverageJavaService(db).list_ledger_files(project_id, ledger_id)
    return success_response(data=files)


@router.get("/projects/{project_id}/coverage-ledgers/{ledger_id}/file")
async def get_ledger_file(
    project_id: int,
    ledger_id: int,
    path: str = Query(..., min_length=1, max_length=500, description="JaCoCo 文件 key，如 com/example/Foo.java"),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """单文件源码（head_commit 快照）+ 行覆盖（含 sources）"""
    result = await CoverageJavaService(db).get_ledger_file(project_id, ledger_id, path)
    return success_response(data=LedgerFileContent.model_validate(result).model_dump())


@router.get("/projects/{project_id}/coverage-ledgers/{ledger_id}/diff-coverage")
async def get_ledger_diff_coverage(
    project_id: int,
    ledger_id: int,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """基于账本的增量覆盖率：merge-base(base, head)..head 的变更行 × 账本累积覆盖"""
    result = await CoverageJavaService(db).get_ledger_diff_coverage(project_id, ledger_id)
    return success_response(data=LedgerDiffCoverageResponse.model_validate(result).model_dump())


@router.get("/projects/{project_id}/coverage-ledgers/{ledger_id}/events")
async def get_ledger_events(
    project_id: int,
    ledger_id: int,
    limit: int = Query(100, ge=1, le=500),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """合并历史（新的在前）+ 需回归方法"""
    result = await CoverageJavaService(db).get_ledger_events(project_id, ledger_id, limit)
    return success_response(data=LedgerEventsResponse.model_validate(result, from_attributes=True).model_dump(mode="json"))
