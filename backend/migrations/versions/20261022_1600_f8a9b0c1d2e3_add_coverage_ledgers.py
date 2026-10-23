"""add coverage ledgers / ledger_files / ledger_events, report.method_index_path

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-10-22 16:00:00.000000+00:00

覆盖率累积账本（P3）。
"""
from alembic import op
import sqlalchemy as sa


revision = 'f8a9b0c1d2e3'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def _ts():
    return [
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
    ]


def upgrade() -> None:
    op.add_column('java_coverage_reports', sa.Column('method_index_path', sa.String(length=500), nullable=True, comment='MinIO 中本 commit 的方法索引 JSON'))

    op.create_table(
        'coverage_ledgers',
        sa.Column('id', sa.BigInteger(), primary_key=True, comment='主键ID'),
        sa.Column('task_id', sa.BigInteger(), sa.ForeignKey('coverage_tasks.id', ondelete='CASCADE'), nullable=False, comment='所属任务ID'),
        sa.Column('service_name', sa.String(length=100), nullable=False, comment='服务名称'),
        sa.Column('branch', sa.String(length=100), nullable=False, comment='本轮绑定的分支，切换分支自动开新一轮'),
        sa.Column('round_no', sa.Integer(), nullable=False, comment='轮次，从 1 开始'),
        sa.Column('is_active', sa.Boolean(), nullable=False, comment='当前轮次，同一 task+service 仅一个 active'),
        sa.Column('head_commit', sa.String(length=64), nullable=True, comment='账本当前对齐的 commit'),
        sa.Column('line_rate', sa.Float(), nullable=True, comment='累积行覆盖率 0-100'),
        sa.Column('branch_rate', sa.Float(), nullable=True, comment='累积分支覆盖率 0-100'),
        sa.Column('lines_covered', sa.Integer(), nullable=True),
        sa.Column('lines_total', sa.Integer(), nullable=True),
        sa.Column('branches_covered', sa.Integer(), nullable=True),
        sa.Column('branches_total', sa.Integer(), nullable=True),
        sa.Column('source_stats', sa.JSON(), nullable=True, comment='按来源统计'),
        sa.Column('merged_exec_path', sa.String(length=500), nullable=True, comment='MinIO：本轮累积的 jacococli merge 结果'),
        sa.Column('method_index_path', sa.String(length=500), nullable=True, comment='MinIO：head_commit 的方法索引 JSON'),
        sa.Column('classfiles_path', sa.String(length=500), nullable=True, comment='MinIO：head_commit 编译出的 class 压缩包'),
        sa.Column('source_snapshot_path', sa.String(length=500), nullable=True, comment='MinIO：head_commit 的源码快照 zip'),
        *_ts(),
        sa.UniqueConstraint('task_id', 'service_name', 'round_no', name='uq_ledger_task_service_round'),
        comment='覆盖率累积账本表',
    )
    op.create_index('ix_coverage_ledgers_id', 'coverage_ledgers', ['id'])
    op.create_index('ix_coverage_ledgers_task_id', 'coverage_ledgers', ['task_id'])

    op.create_table(
        'coverage_ledger_files',
        sa.Column('id', sa.BigInteger(), primary_key=True, comment='主键ID'),
        sa.Column('ledger_id', sa.BigInteger(), sa.ForeignKey('coverage_ledgers.id', ondelete='CASCADE'), nullable=False, comment='所属账本ID'),
        sa.Column('file_path', sa.String(length=500), nullable=False, comment='JaCoCo key，如 com/example/Foo.java'),
        sa.Column('lines_json', sa.JSON(), nullable=False, comment='{line_no: {ci,mi,cb,mb,status,sources}}'),
        sa.Column('lines_covered', sa.Integer(), nullable=False),
        sa.Column('lines_total', sa.Integer(), nullable=False),
        *_ts(),
        comment='覆盖率账本文件级行覆盖表',
    )
    op.create_index('ix_coverage_ledger_files_id', 'coverage_ledger_files', ['id'])
    op.create_index('ix_coverage_ledger_files_ledger_id', 'coverage_ledger_files', ['ledger_id'])

    op.create_table(
        'coverage_ledger_events',
        sa.Column('id', sa.BigInteger(), primary_key=True, comment='主键ID'),
        sa.Column('ledger_id', sa.BigInteger(), sa.ForeignKey('coverage_ledgers.id', ondelete='CASCADE'), nullable=False, comment='所属账本ID'),
        sa.Column('report_id', sa.BigInteger(), nullable=True, comment='合并进来的采集结果'),
        sa.Column('source', sa.String(length=20), nullable=True, comment='unittest/runtime'),
        sa.Column('from_commit', sa.String(length=64), nullable=True, comment='迁移前 commit'),
        sa.Column('to_commit', sa.String(length=64), nullable=True, comment='迁移后 commit'),
        sa.Column('direction', sa.String(length=20), nullable=False, comment='init/same/forward/backward/diverged/new_round'),
        sa.Column('reason', sa.String(length=20), nullable=True, comment='new_round 时：branch_switch/manual'),
        sa.Column('mismatch_classes_json', sa.JSON(), nullable=True, comment='本次 class 不一致的类'),
        sa.Column('methods_kept', sa.Integer(), nullable=False),
        sa.Column('methods_reset', sa.Integer(), nullable=False),
        sa.Column('methods_removed', sa.Integer(), nullable=False),
        sa.Column('methods_added', sa.Integer(), nullable=False),
        sa.Column('reset_methods_json', sa.JSON(), nullable=True, comment='被清零方法 key 列表（需回归方法）'),
        sa.Column('line_rate_before', sa.Float(), nullable=True),
        sa.Column('line_rate_after', sa.Float(), nullable=True),
        *_ts(),
        comment='覆盖率账本合并事件表',
    )
    op.create_index('ix_coverage_ledger_events_id', 'coverage_ledger_events', ['id'])
    op.create_index('ix_coverage_ledger_events_ledger_id', 'coverage_ledger_events', ['ledger_id'])


def downgrade() -> None:
    op.drop_table('coverage_ledger_events')
    op.drop_table('coverage_ledger_files')
    op.drop_table('coverage_ledgers')
    op.drop_column('java_coverage_reports', 'method_index_path')
