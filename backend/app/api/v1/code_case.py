"""
代码用例管理 API 路由

独立于手工用例/自动化用例，不影响原有路由。
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.errors import success_response
from app.db.base import get_db
from app.modules.auth.schemas import CurrentUser
from app.modules.code_case.service import (
    CodeCaseExecutionService, CodeCaseModuleService, CodeCaseScanService,
    CodeCaseService,
)
from app.schemas.code_case import (
    CodeModuleCreate, CodeModuleUpdate, ExecuteRequest,
)

router = APIRouter(prefix="/code-cases", tags=["代码用例"])


# ──────────────────────────────────────────────
# 扫描
# ──────────────────────────────────────────────

@router.post("/scan")
async def scan_code_cases(
    project_id: Optional[int] = Query(None, description="只同步该项目的用例；不传则全量扫描"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """扫描代码：先同步 Git 仓库，再解析 code_testcases 目录下的 @case 用例并入库。"""
    from app.modules.code_case.sync_repo import ensure_latest
    sync_result = ensure_latest()

    svc = CodeCaseScanService(db)
    result = await svc.scan(current_user.id, project_id=project_id)
    return success_response(
        data={**result.model_dump(mode='json'), "sync": sync_result},
        message="同步+扫描完成"
    )


# ──────────────────────────────────────────────
# 用例统计 / 列表 / 详情
# ──────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    project_id: Optional[int] = Query(None, description="按项目过滤；不传返回全部（含旧数据）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """用例数据统计（总数、按等级、按状态、涉及模块数）"""
    svc = CodeCaseService(db)
    return success_response(data=(await svc.stats(project_id=project_id)).model_dump(mode='json'))


@router.get("")
async def list_code_cases(
    module_id: Optional[int] = Query(None, description="按模块过滤"),
    include_children: bool = Query(True, description="是否含子模块用例"),
    level: Optional[str] = Query(None, description="用例等级 P0/P1/P2/P3"),
    keyword: Optional[str] = Query(None, description="按用例名/模块/函数名搜索"),
    project_id: Optional[int] = Query(None, description="按项目过滤；不传返回全部（含旧数据）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """用例列表（附带用例归属模块层级字段 module / module_path）"""
    svc = CodeCaseService(db)
    page_data = await svc.paginate(
        module_id=module_id, include_children=include_children,
        level=level, keyword=keyword, project_id=project_id,
        page=page, page_size=page_size,
    )
    return success_response(data=page_data.model_dump(mode='json'))


# ──────────────────────────────────────────────
# 执行 / 结果预览
# 注意：这些静态路径必须声明在 GET /{case_id} 之前，
# 否则 /executions 会被单段通配 /{case_id} 先匹配到并报 422。
# ──────────────────────────────────────────────

@router.post("/execute")
async def execute_cases(
    data: ExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    执行用例（异步）

    三种方式取其一：case_ids 指定用例 / module_id 按模块（含子模块）/ all_cases 全部。
    立即返回 batch_id 与 pending 明细，用 GET /batches/{batch_id} 轮询结果。
    """
    svc = CodeCaseExecutionService(db)
    result = await svc.start(data, current_user.id)
    return success_response(data=result.model_dump(mode='json'), message="执行已提交")


@router.get("/batches/{batch_id}")
async def get_batch_result(
    batch_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """执行结果预览：批次汇总（通过率/各状态计数）+ 用例明细"""
    svc = CodeCaseExecutionService(db)
    return success_response(data=(await svc.get_batch(batch_id)).model_dump(mode='json'))


@router.get("/executions")
async def list_executions(
    case_id: Optional[int] = Query(None, description="按用例过滤"),
    batch_id: Optional[str] = Query(None, description="按批次过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """执行历史列表"""
    svc = CodeCaseExecutionService(db)
    page_data = await svc.list_executions(
        case_id=case_id, batch_id=batch_id, status=status,
        page=page, page_size=page_size,
    )
    return success_response(data=page_data.model_dump(mode='json'))


@router.get("/executions/{exec_id}")
async def get_execution(
    exec_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """单条执行详情（含完整日志与堆栈）"""
    svc = CodeCaseExecutionService(db)
    return success_response(data=(await svc.get_execution(exec_id)).model_dump(mode='json'))


@router.get("/{case_id}")
async def get_code_case(
    case_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """用例详情（含代码片段）"""
    svc = CodeCaseService(db)
    return success_response(data=(await svc.get_detail(case_id)).model_dump(mode='json'))


# ──────────────────────────────────────────────
# 用例模块层级
# ──────────────────────────────────────────────

@router.get("/modules/tree")
async def get_module_tree(
    project_id: Optional[int] = Query(None, description="按项目过滤模块树；不传返回全部"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """用例模块层级树（含用例数量）"""
    svc = CodeCaseModuleService(db)
    tree = await svc.get_tree(project_id=project_id)
    return success_response(data=[n.model_dump(mode='json') for n in tree])


@router.post("/modules")
async def create_module(
    data: CodeModuleCreate,
    project_id: Optional[int] = Query(None, description="绑定到指定项目；不传则创建全局共享模块"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """新增用例模块"""
    svc = CodeCaseModuleService(db)
    result = await svc.create(data, current_user.id, project_id=project_id)
    return success_response(data=result.model_dump(mode='json'), message="模块已创建")


@router.patch("/modules/{module_id}")
async def update_module(
    module_id: int,
    data: CodeModuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """编辑用例模块名称/排序（改名会级联更新子孙层级路径）"""
    svc = CodeCaseModuleService(db)
    result = await svc.update(module_id, data, current_user.id)
    return success_response(data=result.model_dump(mode='json'), message="模块已更新")


@router.delete("/modules/{module_id}")
async def delete_module(
    module_id: int,
    cascade: bool = Query(False, description="是否连带删除子模块（默认拒绝非空模块）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    """删除用例模块层级"""
    svc = CodeCaseModuleService(db)
    await svc.delete(module_id, cascade=cascade)
    return success_response(message="模块已删除")
