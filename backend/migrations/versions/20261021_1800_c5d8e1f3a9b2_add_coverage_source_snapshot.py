"""add java_coverage_reports.source_snapshot_path

Revision ID: c5d8e1f3a9b2
Revises: a3f7c9e2b8d4
Create Date: 2026-10-21 18:00:00.000000+00:00

采集完成时把报告涉及的源码打包为 sources.zip 上传 MinIO，
代码浏览页从快照读取源码（与采集时 commit 一致）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5d8e1f3a9b2'
down_revision = 'a3f7c9e2b8d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'java_coverage_reports',
        sa.Column(
            'source_snapshot_path', sa.String(length=500), nullable=True,
            comment='MinIO 中的源码快照 zip 路径',
        ),
    )


def downgrade() -> None:
    op.drop_column('java_coverage_reports', 'source_snapshot_path')
