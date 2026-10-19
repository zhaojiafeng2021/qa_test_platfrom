"""
代码用例模型（自动化代码用例机制）

与手工用例(manual_cases)、自动化用例(automation_cases)完全隔离：
独立两张新表，不改动原有任何表结构。

- CodeCaseModule: 用例模块层级树，由扫描时的 @case(module="A-B-C") 自动建立
- CodeTestCase:   代码用例信息表，一条记录对应一个被 @case 装饰的函数
"""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text

from app.db.base import Base
from app.db.base_model import BaseModel, UserTrackingMixin


class CodeCaseModule(Base, BaseModel, UserTrackingMixin):
    """代码用例模块表（支持多级层级，可按项目隔离；project_id 为空表示全局共享）"""
    __tablename__ = "code_case_modules"
    __table_args__ = {"comment": "代码用例模块表"}

    project_id = Column(BigInteger, nullable=True, index=True, comment="所属项目ID，NULL=全局共享")
    parent_id = Column(BigInteger, nullable=True, index=True, comment="父模块ID，根级为空")
    name = Column(String(100), nullable=False, index=True, comment="模块名称")
    level = Column(Integer, default=1, nullable=False, comment="层级深度（根=1）")
    full_path = Column(String(500), nullable=False, index=True,
                       comment='完整层级路径，如 "支付中心-支付渠道-支付宝"')
    sort_order = Column(Integer, default=0, nullable=False, comment="排序权重")
    is_used = Column(Boolean, default=True, nullable=False, index=True,
                     comment="是否有效使用（扫描后若模块下无用例则置 False）")

    def __repr__(self):
        return f"<CodeCaseModule(id={self.id}, full_path={self.full_path})>"


class CodeTestCase(Base, BaseModel, UserTrackingMixin):
    """代码用例表（扫描 code_testcases 目录得到）"""
    __tablename__ = "code_testcases"
    __table_args__ = {"comment": "代码用例表"}

    project_id = Column(BigInteger, nullable=True, index=True, comment="所属项目ID，NULL=全局共享（旧数据兼容）")
    module_id = Column(BigInteger, nullable=True, index=True, comment="所属模块ID（最小层级）")
    module = Column(String(500), nullable=False, index=True,
                    comment='模块层级原始字符串，如 "支付中心-支付渠道-支付宝"')
    name = Column(String(200), nullable=False, comment="用例名称")
    level = Column(String(10), default="P1", nullable=False, index=True,
                   comment="用例等级: P0/P1/P2/P3")
    description = Column(Text, nullable=True, comment="用例描述")

    file_path = Column(String(500), nullable=False, index=True,
                       comment="相对 code_testcases 的文件路径")
    function_name = Column(String(200), nullable=False, comment="函数名，执行器据此定位")
    code_snippet = Column(Text, nullable=True, comment="代码片段")
    line_number = Column(Integer, nullable=True, comment="函数所在行号")

    status = Column(String(20), default="idle", nullable=False, index=True,
                    comment="执行状态: idle/running/passed/failed")
    last_run_at = Column(DateTime, nullable=True, comment="上次执行时间")

    # 软删除：文件从磁盘消失时置 True，重新出现时自动恢复
    is_deleted = Column(Boolean, default=False, nullable=False, index=True,
                        comment="源文件是否已删除")
    deleted_at = Column(DateTime, nullable=True, comment="标记删除时间")

    def __repr__(self):
        return f"<CodeTestCase(id={self.id}, name={self.name}, module={self.module})>"


class CodeCaseExecution(Base, BaseModel):
    """
    代码用例执行记录

    一条记录 = 一个用例的一次执行；同一批次共享 batch_id。
    用例元信息在此做快照，避免用例改名/失效后历史结果读不出来。
    """
    __tablename__ = "code_case_executions"
    __table_args__ = {"comment": "代码用例执行记录表"}

    batch_id = Column(String(40), nullable=False, index=True, comment="批次ID，同批次共享")
    case_id = Column(BigInteger, nullable=False, index=True, comment="用例ID")

    # 执行时的用例快照
    case_name = Column(String(200), nullable=False, comment="用例名称（快照）")
    module = Column(String(500), nullable=True, comment="模块层级（快照）")
    level = Column(String(10), nullable=True, comment="用例等级（快照）")
    file_path = Column(String(500), nullable=True, comment="文件路径（快照）")
    function_name = Column(String(200), nullable=True, comment="函数名（快照）")

    status = Column(String(20), default="pending", nullable=False, index=True,
                    comment="pending/running/passed/failed/error/timeout")
    message = Column(String(1000), nullable=True, comment="结果摘要/错误信息")
    logs = Column(Text, nullable=True, comment="捕获的 stdout/stderr")
    traceback = Column(Text, nullable=True, comment="异常堆栈")
    duration_ms = Column(Integer, nullable=True, comment="耗时（毫秒）")

    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    trigger_by = Column(BigInteger, nullable=True, comment="触发人用户ID")

    def __repr__(self):
        return f"<CodeCaseExecution(id={self.id}, case_id={self.case_id}, status={self.status})>"
