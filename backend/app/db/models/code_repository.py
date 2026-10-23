"""代码源（远程 Git 仓库）配置

覆盖率任务通过 repo_id 关联代码源，前端据此下拉选择分支与服务。
"""
from sqlalchemy import BigInteger, Column, ForeignKey, String

from app.db.base import Base
from app.db.base_model import BaseModel, SoftDeleteMixin, UserTrackingMixin


class CodeRepository(Base, BaseModel, UserTrackingMixin, SoftDeleteMixin):
    """项目级代码源"""

    __tablename__ = "code_repositories"
    __table_args__ = {"comment": "代码源（远程 Git 仓库）配置表"}

    project_id = Column(
        BigInteger,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    name = Column(String(100), nullable=False, comment="代码源名称")
    repo_url = Column(String(500), nullable=False, comment="Git 仓库 URL（HTTPS/SSH）")
    default_branch = Column(String(100), nullable=True, comment="默认分支")
    description = Column(String(500), nullable=True, comment="说明")

    def __repr__(self):
        return f"<CodeRepository(id={self.id}, name={self.name})>"
