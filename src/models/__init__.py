"""ORM models — import all models here so SQLAlchemy registers them."""

from src.models.company import Company
from src.models.user import User, Role, Permission, user_roles, role_permissions
from src.models.team import Team, TeamMembership
from src.models.document import (
    Collection,
    Document,
    DocumentTeamAccess,
    DocumentUserAccess,
    VisibilityEnum,
    DocumentStatusEnum,
)
from src.models.audit import (
    QueryLog,
    IngestionLog,
    DocumentAuditLog,
    TeamAuditLog,
    DocumentAction,
    TeamAction,
)
from src.models.api_key import APIKey
from src.models.webhook import Webhook  # Feature 4: Outbound webhooks
from src.models.compliance import (
    ComplianceConfig,
    ComplianceCollectionOverride,
    CustomComplianceRuleModel,
    ComplianceScanResult,
)
from src.models.session import UserSession

__all__ = [
    "User", "Role", "Permission", "user_roles", "role_permissions",
    "Team", "TeamMembership",
    "Collection", "Document", "DocumentTeamAccess", "DocumentUserAccess",
    "VisibilityEnum", "DocumentStatusEnum",
    "QueryLog", "IngestionLog", "DocumentAuditLog", "TeamAuditLog",
    "DocumentAction", "TeamAction",
    "APIKey",
    "Webhook",
    "Company",
]
