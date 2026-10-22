"""Import database models so Alembic can discover their metadata."""
from app.db.base import Base
from app.db.models.user import User
from app.db.models.api_token import ApiToken
from app.db.models.project import Project
from app.db.models.permission import Permission, ProjectDataPolicy, Role, RoleDirectPermission, RolePermission
from app.db.models.project_member import ProjectMember
from app.db.models.audit_log import AuditLog
from app.db.models.environment import Environment, Variable
from app.db.models.notification import NotificationChannel, NotificationDelivery
from app.db.models.test_plan import TestPlan, PlanItem, Schedule, PlanRun, PlanRunItem
from app.db.models.report import NotificationLog, NotificationRule, ReportFile
from app.db.models.system_config import SystemConfig
from app.db.models.code_case import CodeCaseModule, CodeTestCase, CodeCaseExecution
from app.db.models.coverage_java import CoverageTask, JavaCoverageReport, JavaCoverageRun
from app.db.models.code_repository import CodeRepository

__all__ = [
    "Base",
    "User",
    "ApiToken",
    "Project",
    "ProjectMember",
    "Role",
    "Permission",
    "RolePermission",
    "RoleDirectPermission",
    "ProjectDataPolicy",
    "AuditLog",
    "Environment",
    "Variable",
    "NotificationChannel",
    "NotificationDelivery",
    "NotificationRule",
    "NotificationLog",
    "ReportFile",
    "TestPlan",
    "PlanItem",
    "Schedule",
    "PlanRun",
    "PlanRunItem",
    "SystemConfig",
    "CodeCaseModule",
    "CodeTestCase",
    "CodeCaseExecution",
    "CoverageTask",
    "JavaCoverageRun",
    "JavaCoverageReport",
    "CodeRepository",
]
