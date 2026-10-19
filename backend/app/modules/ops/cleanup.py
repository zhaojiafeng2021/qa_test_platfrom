"""数据保留/清理服务。

定期清理超期的报告文件，避免磁盘与数据表无限膨胀。

双保险安全设计（防止误删验收数据）：
1. 保留窗（retention window）：仅清理 created_at 早于 now - retention_days 的记录。
2. 保护白名单（protected run ids）：命中白名单的 Run 及其关联数据一律跳过，即便已超期。

所有函数返回统一统计结构 {"scanned": n, "deleted": m, "errors": k}。
dry_run=True 时只统计不实删（scanned 正常计数，deleted 恒为 0）。
清理为 best-effort：单条删除失败计入 errors，不阻断其余清理。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.report import ReportFile

logger = get_logger(__name__)


async def cleanup_reports(
    db: AsyncSession,
    *,
    retention_days: int,
    protected_run_ids: list[int] | None = None,
    batch_size: int = 500,
    dry_run: bool = False,
) -> dict:
    """清理超期报告文件（DB 记录 + MinIO/本地物理文件）。

    命中白名单 plan_run_id 的报告一律保留（execution 类报告 plan_run_id 为空，
    不受 run 白名单影响，但仍受保留窗约束）。
    """
    protected = set(protected_run_ids or [])
    cutoff = datetime.utcnow() - timedelta(days=retention_days)

    stmt = (
        select(ReportFile)
        .where(ReportFile.created_at < cutoff)
        .order_by(ReportFile.id)
        .limit(batch_size)
    )

    scanned = 0
    deleted = 0
    errors = 0

    # 延迟导入 ReportService 复用其删除范式（MinIO -> 本地 -> DB row）。
    from app.modules.report.service import ReportService

    service = ReportService(db)

    while True:
        rows = (await db.execute(stmt)).scalars().all()
        if not rows:
            break

        progressed = False
        for report in rows:
            # 白名单保护：关联受保护 Run 的报告跳过。
            if report.plan_run_id is not None and report.plan_run_id in protected:
                continue
            scanned += 1
            progressed = True
            if dry_run:
                continue
            try:
                await service.delete_report(report.project_id, report.id)
                deleted += 1
            except Exception:
                errors += 1
                logger.exception("cleanup_reports failed report_id=%s", report.id)

        # dry_run 或整批都被白名单跳过时，避免死循环：只扫一批即退出。
        if dry_run or not progressed:
            break
        # 实删模式下 delete_report 已提交，下一轮 limit 查询自然取到新的超期记录。

    result = {"scanned": scanned, "deleted": deleted, "errors": errors}
    logger.info("cleanup_reports done dry_run=%s result=%s", dry_run, result)
    return result
