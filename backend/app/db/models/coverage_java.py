"""JaCoCo 覆盖率采集数据模型

三张表：
- CoverageTask        任务（一等实体，持久化配置）
- JavaCoverageRun     运行实例（一次触发 = 一个 run，含多个服务的采集）
- JavaCoverageReport  单服务报告（一个 run 的某个服务，存行级覆盖与产物路径）
"""
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.db.base_model import BaseModel, SoftDeleteMixin, UserTrackingMixin


class CoverageTask(Base, BaseModel, UserTrackingMixin, SoftDeleteMixin):
    """覆盖率采集任务（一等实体）"""

    __tablename__ = "coverage_tasks"
    __table_args__ = {"comment": "JaCoCo 覆盖率采集任务表"}

    project_id = Column(
        BigInteger,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    name = Column(String(200), nullable=False, comment="任务名称")
    repo_id = Column(BigInteger, nullable=True, index=True, comment="关联代码源 code_repositories.id")
    repo_url = Column(String(500), nullable=False, comment="Git 仓库 URL（HTTPS/SSH），clone 用")
    services = Column(JSON, nullable=False, comment='服务列表 [{"name","module","path"}]，monorepo 多服务')
    branch = Column(String(100), nullable=False, default="main", comment="目标采集分支")
    diff_base_branch = Column(String(100), nullable=True, comment="增量 diff 基准分支，空则用 project.default_main_branch")
    requirement_ref = Column(String(200), nullable=True, comment="关联需求（预留字段，二期接第三方平台）")
    cron_expr = Column(String(100), nullable=True, comment="定时采集 cron 表达式（MVP 仅存储）")
    threshold_line_rate = Column(Float, nullable=True, comment="行覆盖率告警阈值（MVP 仅存储）")
    threshold_branch_rate = Column(Float, nullable=True, comment="分支覆盖率告警阈值（MVP 仅存储）")
    collection_mode = Column(
        String(20),
        nullable=False,
        default="unittest",
        comment="采集模式：unittest（单元测试，默认）| runtime（运行时 tcpserver dump）",
    )
    runtime_config = Column(JSON, nullable=True, comment='运行时模式配置 {"host":"10.0.1.100","port":6300}')

    owner_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="负责人ID",
    )
    status = Column(
        String(20),
        nullable=False,
        default="draft",
        index=True,
        comment="draft/queued/running/completed/failed/cancelled",
    )
    # 不设 FK：CoverageTask.current_run_id → JavaCoverageRun.id 是反向引用，避免循环依赖
    current_run_id = Column(BigInteger, nullable=True, comment="当前进行中的 run_id")
    last_completed_at = Column(DateTime, nullable=True, comment="最近一次成功完成时间")
    last_failed_at = Column(DateTime, nullable=True, comment="最近一次失败时间")

    project = relationship("Project")
    owner = relationship("User", foreign_keys=[owner_id])

    def __repr__(self):
        return f"<CoverageTask(id={self.id}, name={self.name}, status={self.status})>"


class JavaCoverageRun(Base, BaseModel):
    """覆盖率采集运行实例（一次触发 = 一个 run，包含 N 个服务的采集）"""

    __tablename__ = "java_coverage_runs"
    __table_args__ = {"comment": "JaCoCo 覆盖率采集运行实例表"}

    task_id = Column(
        BigInteger,
        ForeignKey("coverage_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属任务ID",
    )
    trigger_type = Column(
        String(20),
        nullable=False,
        default="manual",
        comment="触发方式 manual/cron/retry",
    )
    overall_status = Column(
        String(20),
        nullable=False,
        default="queued",
        index=True,
        comment="queued/running/completed/failed/cancelled/partial",
    )
    commit_sha = Column(String(64), nullable=True, comment="触发时确定的 commit（下拉选择或分支 HEAD）")
    source = Column(String(20), nullable=True, comment="采集来源 unittest/runtime")
    services_total = Column(Integer, nullable=False, default=0, comment="服务总数")
    services_completed = Column(Integer, nullable=False, default=0, comment="成功数")
    services_failed = Column(Integer, nullable=False, default=0, comment="失败数")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")

    task = relationship("CoverageTask")

    def __repr__(self):
        return f"<JavaCoverageRun(id={self.id}, task_id={self.task_id}, status={self.overall_status})>"


class JavaCoverageReport(Base, BaseModel):
    """单服务覆盖率报告（一个 run 下的某个服务）"""

    __tablename__ = "java_coverage_reports"
    __table_args__ = {"comment": "JaCoCo 单服务覆盖率报告表"}

    run_id = Column(
        BigInteger,
        ForeignKey("java_coverage_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属 run_id",
    )
    task_id = Column(
        BigInteger,
        ForeignKey("coverage_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属任务ID（冗余，便于按任务过滤）",
    )
    service_name = Column(String(100), nullable=False, index=True, comment="服务名称")
    commit_sha = Column(String(64), nullable=True, comment="采集时的 commit SHA")
    source = Column(String(20), nullable=True, comment="采集来源 unittest/runtime")
    warnings = Column(JSON, nullable=True, comment='告警 {"mismatch_classes": [...]}，如部署包与平台编译 class 不一致')
    status = Column(
        String(20),
        nullable=False,
        default="queued",
        index=True,
        comment="queued/running/completed/failed/skipped/cancelled",
    )
    progress = Column(Integer, nullable=False, default=0, comment="进度 0-100")
    stage = Column(
        String(20),
        nullable=False,
        default="pending",
        comment="当前阶段 pending/clone/build/test/report/done",
    )
    stage_detail = Column(String(500), nullable=True, comment="当前阶段描述（如 '执行 mvn clean test (3/10)'）")

    line_rate = Column(Float, nullable=True, comment="行覆盖率 0-100")
    branch_rate = Column(Float, nullable=True, comment="分支覆盖率 0-100")
    lines_covered = Column(Integer, nullable=True)
    lines_total = Column(Integer, nullable=True)
    branches_covered = Column(Integer, nullable=True)
    branches_total = Column(Integer, nullable=True)

    line_coverage_json = Column(
        JSON,
        nullable=True,
        comment="按文件的行级覆盖 {file_path: {line_no: {ci,mi,cb,mb,status}}}",
    )

    xml_report_path = Column(String(500), nullable=True, comment="MinIO 中的 XML 报告路径")
    html_report_path = Column(String(500), nullable=True, comment="MinIO 中的 HTML 报告路径")
    exec_file_path = Column(String(500), nullable=True, comment="MinIO 中的 .exec 文件路径")
    build_log_path = Column(String(500), nullable=True, comment="MinIO 中的构建日志路径")
    source_snapshot_path = Column(String(500), nullable=True, comment="MinIO 中的源码快照 zip 路径")
    method_index_path = Column(String(500), nullable=True, comment="MinIO 中本 commit 的方法索引 JSON")
    error_message = Column(Text, nullable=True)

    run = relationship("JavaCoverageRun")
    task = relationship("CoverageTask")

    def __repr__(self):
        return (
            f"<JavaCoverageReport(id={self.id}, run_id={self.run_id}, "
            f"service={self.service_name}, status={self.status})>"
        )


class CoverageLedger(Base, BaseModel):
    """覆盖率累积账本头：一个 task+service 在一轮内的累积状态，始终对齐到 head_commit"""

    __tablename__ = "coverage_ledgers"
    __table_args__ = (
        UniqueConstraint("task_id", "service_name", "round_no", name="uq_ledger_task_service_round"),
        {"comment": "覆盖率累积账本表"},
    )

    task_id = Column(
        BigInteger,
        ForeignKey("coverage_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属任务ID",
    )
    service_name = Column(String(100), nullable=False, comment="服务名称")
    branch = Column(String(100), nullable=False, comment="本轮绑定的分支，切换分支自动开新一轮")
    round_no = Column(Integer, nullable=False, default=1, comment="轮次，从 1 开始")
    is_active = Column(Boolean, nullable=False, default=True, comment="当前轮次，同一 task+service 仅一个 active")
    head_commit = Column(String(64), nullable=True, comment="账本当前对齐的 commit")

    line_rate = Column(Float, nullable=True, comment="累积行覆盖率 0-100")
    branch_rate = Column(Float, nullable=True, comment="累积分支覆盖率 0-100")
    lines_covered = Column(Integer, nullable=True)
    lines_total = Column(Integer, nullable=True)
    branches_covered = Column(Integer, nullable=True)
    branches_total = Column(Integer, nullable=True)
    source_stats = Column(JSON, nullable=True, comment='按来源统计 {"unittest_lines","runtime_lines","inherited_lines"}')

    merged_exec_path = Column(String(500), nullable=True, comment="MinIO：本轮累积的 jacococli merge 结果")
    method_index_path = Column(String(500), nullable=True, comment="MinIO：head_commit 的方法索引 JSON")
    classfiles_path = Column(String(500), nullable=True, comment="MinIO：head_commit 编译出的 class 压缩包")
    source_snapshot_path = Column(String(500), nullable=True, comment="MinIO：head_commit 的源码快照 zip")

    task = relationship("CoverageTask")

    def __repr__(self):
        return (
            f"<CoverageLedger(id={self.id}, task_id={self.task_id}, service={self.service_name}, "
            f"round={self.round_no}, head={self.head_commit})>"
        )


class CoverageLedgerFile(Base, BaseModel):
    """账本行级数据（按文件存）"""

    __tablename__ = "coverage_ledger_files"
    __table_args__ = {"comment": "覆盖率账本文件级行覆盖表"}

    ledger_id = Column(
        BigInteger,
        ForeignKey("coverage_ledgers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属账本ID",
    )
    file_path = Column(String(500), nullable=False, comment="JaCoCo key，如 com/example/Foo.java")
    lines_json = Column(JSON, nullable=False, comment="{line_no: {ci,mi,cb,mb,status,sources}}")
    lines_covered = Column(Integer, nullable=False, default=0)
    lines_total = Column(Integer, nullable=False, default=0)


class CoverageLedgerEvent(Base, BaseModel):
    """账本合并记录"""

    __tablename__ = "coverage_ledger_events"
    __table_args__ = {"comment": "覆盖率账本合并事件表"}

    ledger_id = Column(
        BigInteger,
        ForeignKey("coverage_ledgers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属账本ID",
    )
    report_id = Column(BigInteger, nullable=True, comment="合并进来的采集结果")
    source = Column(String(20), nullable=True, comment="unittest/runtime")
    from_commit = Column(String(64), nullable=True, comment="迁移前 commit")
    to_commit = Column(String(64), nullable=True, comment="迁移后 commit")
    direction = Column(String(20), nullable=False, comment="init/same/forward/backward/diverged/new_round")
    reason = Column(String(20), nullable=True, comment="new_round 时：branch_switch/manual")
    mismatch_classes_json = Column(JSON, nullable=True, comment="本次 class 不一致的类")
    methods_kept = Column(Integer, nullable=False, default=0)
    methods_reset = Column(Integer, nullable=False, default=0)
    methods_removed = Column(Integer, nullable=False, default=0)
    methods_added = Column(Integer, nullable=False, default=0)
    reset_methods_json = Column(JSON, nullable=True, comment="被清零方法 key 列表（需回归方法）")
    line_rate_before = Column(Float, nullable=True)
    line_rate_after = Column(Float, nullable=True)
