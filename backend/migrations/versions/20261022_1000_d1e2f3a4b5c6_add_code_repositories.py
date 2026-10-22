"""add code_repositories and coverage_tasks.repo_id

Revision ID: d1e2f3a4b5c6
Revises: 7cc077e9daa1
Create Date: 2026-10-22 10:00:00.000000+00:00
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5c6'
down_revision = '7cc077e9daa1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'code_repositories',
        sa.Column('id', sa.BigInteger(), primary_key=True, comment='主键ID'),
        sa.Column('project_id', sa.BigInteger(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False, comment='所属项目ID'),
        sa.Column('name', sa.String(length=100), nullable=False, comment='代码源名称'),
        sa.Column('repo_url', sa.String(length=500), nullable=False, comment='Git 仓库 URL（HTTPS/SSH）'),
        sa.Column('default_branch', sa.String(length=100), nullable=True, comment='默认分支'),
        sa.Column('description', sa.String(length=500), nullable=True, comment='说明'),
        sa.Column('created_by', sa.BigInteger(), nullable=True, comment='创建者ID'),
        sa.Column('updated_by', sa.BigInteger(), nullable=True, comment='更新者ID'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0', comment='是否已删除'),
        sa.Column('deleted_at', sa.DateTime(), nullable=True, comment='删除时间'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        comment='代码源（远程 Git 仓库）配置表',
    )
    op.create_index('ix_code_repositories_id', 'code_repositories', ['id'])
    op.create_index('ix_code_repositories_project_id', 'code_repositories', ['project_id'])
    op.add_column('coverage_tasks', sa.Column('repo_id', sa.BigInteger(), nullable=True, comment='关联代码源 code_repositories.id'))
    op.create_index('ix_coverage_tasks_repo_id', 'coverage_tasks', ['repo_id'])


def downgrade() -> None:
    op.drop_index('ix_coverage_tasks_repo_id', table_name='coverage_tasks')
    op.drop_column('coverage_tasks', 'repo_id')
    op.drop_index('ix_code_repositories_project_id', table_name='code_repositories')
    op.drop_index('ix_code_repositories_id', table_name='code_repositories')
    op.drop_table('code_repositories')
