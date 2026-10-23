"""add coverage_java tables

Revision ID: a3f7c9e2b8d4
Revises: 2b9f94c1d0a7
Create Date: 2026-10-21 15:30:00.000000+00:00

新增 JaCoCo 覆盖率采集三张表：
- coverage_tasks          任务配置
- java_coverage_runs      运行实例（一次触发）
- java_coverage_reports   单服务报告（含行级覆盖 JSON 和 MinIO 产物路径）
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3f7c9e2b8d4'
down_revision = '2b9f94c1d0a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─── coverage_tasks ───
    op.create_table(
        'coverage_tasks',
        sa.Column('project_id', sa.BigInteger(), nullable=False, comment='所属项目ID'),
        sa.Column('name', sa.String(length=200), nullable=False, comment='任务名称'),
        sa.Column('repo_url', sa.String(length=500), nullable=False, comment='Git 仓库 URL（HTTPS/SSH），clone 用'),
        sa.Column('services', sa.JSON(), nullable=False, comment='服务列表 [{"name","module","path"}]，monorepo 多服务'),
        sa.Column('branch', sa.String(length=100), nullable=False, comment='目标采集分支'),
        sa.Column('diff_base_branch', sa.String(length=100), nullable=True, comment='增量 diff 基准分支，空则用 project.default_main_branch'),
        sa.Column('requirement_ref', sa.String(length=200), nullable=True, comment='关联需求（预留字段，二期接第三方平台）'),
        sa.Column('cron_expr', sa.String(length=100), nullable=True, comment='定时采集 cron 表达式（MVP 仅存储）'),
        sa.Column('threshold_line_rate', sa.Float(), nullable=True, comment='行覆盖率告警阈值（MVP 仅存储）'),
        sa.Column('threshold_branch_rate', sa.Float(), nullable=True, comment='分支覆盖率告警阈值（MVP 仅存储）'),
        sa.Column('owner_id', sa.BigInteger(), nullable=False, comment='负责人ID'),
        sa.Column('status', sa.String(length=20), nullable=False, comment='draft/queued/running/completed/failed/cancelled'),
        sa.Column('current_run_id', sa.BigInteger(), nullable=True, comment='当前进行中的 run_id'),
        sa.Column('last_completed_at', sa.DateTime(), nullable=True, comment='最近一次成功完成时间'),
        sa.Column('last_failed_at', sa.DateTime(), nullable=True, comment='最近一次失败时间'),
        sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('created_by', sa.BigInteger(), nullable=True, comment='创建者ID'),
        sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='更新者ID'),
        sa.Column('is_deleted', sa.Boolean(), server_default='0', nullable=False, comment='是否已删除'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True, comment='删除时间'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='JaCoCo 覆盖率采集任务表',
    )
    op.create_index(op.f('ix_coverage_tasks_id'), 'coverage_tasks', ['id'], unique=False)
    op.create_index(op.f('ix_coverage_tasks_project_id'), 'coverage_tasks', ['project_id'], unique=False)
    op.create_index(op.f('ix_coverage_tasks_status'), 'coverage_tasks', ['status'], unique=False)

    # ─── java_coverage_runs ───
    op.create_table(
        'java_coverage_runs',
        sa.Column('task_id', sa.BigInteger(), nullable=False, comment='所属任务ID'),
        sa.Column('trigger_type', sa.String(length=20), nullable=False, comment='触发方式 manual/cron/retry'),
        sa.Column('overall_status', sa.String(length=20), nullable=False, comment='queued/running/completed/failed/cancelled/partial'),
        sa.Column('services_total', sa.Integer(), nullable=False, comment='服务总数'),
        sa.Column('services_completed', sa.Integer(), nullable=False, comment='成功数'),
        sa.Column('services_failed', sa.Integer(), nullable=False, comment='失败数'),
        sa.Column('started_at', sa.DateTime(), nullable=True, comment='开始时间'),
        sa.Column('finished_at', sa.DateTime(), nullable=True, comment='结束时间'),
        sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.ForeignKeyConstraint(['task_id'], ['coverage_tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='JaCoCo 覆盖率采集运行实例表',
    )
    op.create_index(op.f('ix_java_coverage_runs_id'), 'java_coverage_runs', ['id'], unique=False)
    op.create_index(op.f('ix_java_coverage_runs_overall_status'), 'java_coverage_runs', ['overall_status'], unique=False)
    op.create_index(op.f('ix_java_coverage_runs_task_id'), 'java_coverage_runs', ['task_id'], unique=False)

    # ─── java_coverage_reports ───
    op.create_table(
        'java_coverage_reports',
        sa.Column('run_id', sa.BigInteger(), nullable=False, comment='所属 run_id'),
        sa.Column('task_id', sa.BigInteger(), nullable=False, comment='所属任务ID（冗余，便于按任务过滤）'),
        sa.Column('service_name', sa.String(length=100), nullable=False, comment='服务名称'),
        sa.Column('commit_sha', sa.String(length=64), nullable=True, comment='采集时的 commit SHA'),
        sa.Column('status', sa.String(length=20), nullable=False, comment='queued/running/completed/failed/skipped/cancelled'),
        sa.Column('progress', sa.Integer(), nullable=False, comment='进度 0-100'),
        sa.Column('stage', sa.String(length=20), nullable=False, comment='当前阶段 pending/clone/build/test/report/done'),
        sa.Column('stage_detail', sa.String(length=500), nullable=True, comment="当前阶段描述（如 '执行 mvn clean test (3/10)'）"),
        sa.Column('line_rate', sa.Float(), nullable=True, comment='行覆盖率 0-100'),
        sa.Column('branch_rate', sa.Float(), nullable=True, comment='分支覆盖率 0-100'),
        sa.Column('lines_covered', sa.Integer(), nullable=True),
        sa.Column('lines_total', sa.Integer(), nullable=True),
        sa.Column('branches_covered', sa.Integer(), nullable=True),
        sa.Column('branches_total', sa.Integer(), nullable=True),
        sa.Column('line_coverage_json', sa.JSON(), nullable=True, comment='按文件的行级覆盖 {file_path: {line_no: {ci,mi,cb,mb,status}}}'),
        sa.Column('xml_report_path', sa.String(length=500), nullable=True, comment='MinIO 中的 XML 报告路径'),
        sa.Column('html_report_path', sa.String(length=500), nullable=True, comment='MinIO 中的 HTML 报告路径'),
        sa.Column('exec_file_path', sa.String(length=500), nullable=True, comment='MinIO 中的 .exec 文件路径'),
        sa.Column('build_log_path', sa.String(length=500), nullable=True, comment='MinIO 中的构建日志路径'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.ForeignKeyConstraint(['run_id'], ['java_coverage_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['coverage_tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='JaCoCo 单服务覆盖率报告表',
    )
    op.create_index(op.f('ix_java_coverage_reports_id'), 'java_coverage_reports', ['id'], unique=False)
    op.create_index(op.f('ix_java_coverage_reports_run_id'), 'java_coverage_reports', ['run_id'], unique=False)
    op.create_index(op.f('ix_java_coverage_reports_service_name'), 'java_coverage_reports', ['service_name'], unique=False)
    op.create_index(op.f('ix_java_coverage_reports_status'), 'java_coverage_reports', ['status'], unique=False)
    op.create_index(op.f('ix_java_coverage_reports_task_id'), 'java_coverage_reports', ['task_id'], unique=False)


def downgrade() -> None:
    # FK-safe 顺序：先删依赖方（reports → runs → tasks）
    op.drop_index(op.f('ix_java_coverage_reports_task_id'), table_name='java_coverage_reports')
    op.drop_index(op.f('ix_java_coverage_reports_status'), table_name='java_coverage_reports')
    op.drop_index(op.f('ix_java_coverage_reports_service_name'), table_name='java_coverage_reports')
    op.drop_index(op.f('ix_java_coverage_reports_run_id'), table_name='java_coverage_reports')
    op.drop_index(op.f('ix_java_coverage_reports_id'), table_name='java_coverage_reports')
    op.drop_table('java_coverage_reports')

    op.drop_index(op.f('ix_java_coverage_runs_task_id'), table_name='java_coverage_runs')
    op.drop_index(op.f('ix_java_coverage_runs_overall_status'), table_name='java_coverage_runs')
    op.drop_index(op.f('ix_java_coverage_runs_id'), table_name='java_coverage_runs')
    op.drop_table('java_coverage_runs')

    op.drop_index(op.f('ix_coverage_tasks_status'), table_name='coverage_tasks')
    op.drop_index(op.f('ix_coverage_tasks_project_id'), table_name='coverage_tasks')
    op.drop_index(op.f('ix_coverage_tasks_id'), table_name='coverage_tasks')
    op.drop_table('coverage_tasks')
