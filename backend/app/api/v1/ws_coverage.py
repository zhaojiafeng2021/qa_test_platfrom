"""WebSocket：覆盖率任务进度推送

真实实现：
- accept 后立即从 DB 读当前 run + reports 推 snapshot
- 注册到 ConnectionManager（频道 coverage:task:{task_id}），被动接收 Redis 广播
- 客户端可发 {"type":"ping"} → 回 pong；其他上行消息忽略
- 断开时自动取消注册（最后一个连接会关闭 Redis subscriber 协程）

TODO(prod): WS 鉴权。当前内网开发阶段放开，生产必须在 query/header 校验 token 并校验 project 权限。
"""
import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.ws_manager import ws_manager
from app.db.base import AsyncSessionLocal
from app.modules.coverage_java.repository import (
    CoverageTaskRepository,
    JavaCoverageReportRepository,
)
from app.workers.coverage_java_tasks import coverage_progress_channel

logger = logging.getLogger(__name__)

router = APIRouter()


async def _build_snapshot(task_id: int) -> dict:
    """从 DB 构造 snapshot 消息"""
    async with AsyncSessionLocal() as db:
        task_repo = CoverageTaskRepository(db)
        report_repo = JavaCoverageReportRepository(db)

        task = await task_repo.get(task_id)
        if not task:
            return {
                "type": "snapshot",
                "task_id": task_id,
                "run_id": None,
                "reports": [],
                "error": "task_not_found",
            }

        run_id = task.current_run_id
        reports = []
        if run_id:
            rs = await report_repo.list_by_run(run_id)
            reports = [
                {
                    "id": r.id,
                    "run_id": r.run_id,
                    "task_id": r.task_id,
                    "service_name": r.service_name,
                    "commit_sha": r.commit_sha,
                    "status": r.status,
                    "progress": r.progress,
                    "stage": r.stage,
                    "stage_detail": r.stage_detail,
                    "line_rate": r.line_rate,
                    "branch_rate": r.branch_rate,
                    "lines_covered": r.lines_covered,
                    "lines_total": r.lines_total,
                    "branches_covered": r.branches_covered,
                    "branches_total": r.branches_total,
                    "xml_report_path": r.xml_report_path,
                    "html_report_path": r.html_report_path,
                    "exec_file_path": r.exec_file_path,
                    "build_log_path": r.build_log_path,
                    "error_message": r.error_message,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                }
                for r in rs
            ]

        return {
            "type": "snapshot",
            "task_id": task_id,
            "run_id": run_id,
            "reports": reports,
        }


@router.websocket("/ws/coverage/tasks/{task_id}/progress")
async def coverage_task_progress_ws(websocket: WebSocket, task_id: int):
    """覆盖率任务进度推送

    协议见 backend/app/schemas/coverage_java.py 中的 Ws*Message 系列：
    - snapshot       连接建立后立即推（服务端主动）
    - progress       阶段进度（Redis 广播）
    - service_done   单服务完成
    - service_error  单服务失败
    - task_done      整个 run 完成
    """
    await websocket.accept()
    channel = coverage_progress_channel(task_id)
    logger.info(f"Coverage WS connected: task_id={task_id}")

    # 1. 先推 snapshot（当前 run 状态）
    try:
        snapshot = await _build_snapshot(task_id)
        await websocket.send_json(snapshot)
    except Exception:
        logger.exception(f"Failed to build snapshot for task {task_id}")
        try:
            await websocket.send_json({
                "type": "snapshot",
                "task_id": task_id,
                "run_id": None,
                "reports": [],
                "error": "snapshot_failed",
            })
        except Exception:
            pass

    # 2. 注册到 manager，后续消息由 Redis subscriber 推送
    await ws_manager.connect(channel, websocket)

    try:
        # 3. 接收客户端消息（心跳 / 未来扩展指令）
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    pass
            except asyncio.TimeoutError:
                # 30s 无客户端消息 → 主动 ping 保活
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        logger.info(f"Coverage WS disconnected: task_id={task_id}")
    except Exception:
        logger.exception(f"Coverage WS error: task_id={task_id}")
    finally:
        await ws_manager.disconnect(channel, websocket)
