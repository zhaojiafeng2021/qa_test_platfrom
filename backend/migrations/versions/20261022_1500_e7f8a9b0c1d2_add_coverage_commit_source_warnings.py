"""add run.commit_sha/source, report.source/warnings

Revision ID: e7f8a9b0c1d2
Revises: d1e2f3a4b5c6
Create Date: 2026-10-22 15:00:00.000000+00:00

触发采集时确定 commit 与来源；报告记录 class 不一致等告警（覆盖率累积账本前置）。
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7f8a9b0c1d2'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('java_coverage_runs', sa.Column('commit_sha', sa.String(length=64), nullable=True, comment='触发时确定的 commit（下拉选择或分支 HEAD）'))
    op.add_column('java_coverage_runs', sa.Column('source', sa.String(length=20), nullable=True, comment='采集来源 unittest/runtime'))
    op.add_column('java_coverage_reports', sa.Column('source', sa.String(length=20), nullable=True, comment='采集来源 unittest/runtime'))
    op.add_column('java_coverage_reports', sa.Column('warnings', sa.JSON(), nullable=True, comment='告警，如部署包与平台编译 class 不一致'))


def downgrade() -> None:
    op.drop_column('java_coverage_reports', 'warnings')
    op.drop_column('java_coverage_reports', 'source')
    op.drop_column('java_coverage_runs', 'source')
    op.drop_column('java_coverage_runs', 'commit_sha')
