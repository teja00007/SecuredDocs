"""RBAC enforcement: permissions, visibility filters, document access checks.

Uses a pluggable VisibilityRule registry so adding a new visibility level
(e.g., "internal") requires only a new class + one registry entry.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Role → Permission mapping
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "super_admin": {
        "collection:read", "collection:write", "collection:delete",
        "document:read", "document:write", "document:delete",
        "query:execute",
        "user:manage",
        "dl:manage",
        "compliance:manage",
        "admin:read", "admin:write",
        "company:read", "company:write", "company:delete",
    },
    "admin": {
        "collection:read", "collection:write", "collection:delete",
        "document:read", "document:write", "document:delete",
        "query:execute",
        "user:manage",
        "dl:manage",
        "compliance:manage",
        "admin:read", "admin:write",
    },
    "analyst": {
        "collection:read", "collection:write",
        "document:read", "document:write",
        "query:execute",
        "dl:manage",
    },
    "viewer": {
        "collection:read",
        "document:read",
        "query:execute",
    },
}


def has_permission(roles: list[str], permission: str) -> bool:
    """Check if any of the user's roles grant the given permission."""
    for role in roles:
        if permission in ROLE_PERMISSIONS.get(role, set()):
            return True
    return False


# ---------------------------------------------------------------------------
# User context dataclass (token-decoded info)
# ---------------------------------------------------------------------------

@dataclass
class UserContext:
    """Lightweight user info extracted from JWT for access checks."""
    user_id: str
    roles: list[str]
    team_ids: list[str]
    username: str = ""
    company_id: str | None = None
    is_super_admin: bool = False


# ---------------------------------------------------------------------------
# Visibility Rule registry (pluggable)
# ---------------------------------------------------------------------------

class VisibilityRule(ABC):
    """Abstract base for visibility rules."""

    @abstractmethod
    def can_access(self, user: UserContext, doc_metadata: dict) -> bool:
        """Check if user can access a document with given metadata."""
        ...

    @abstractmethod
    def build_filter_clause(self, user: UserContext) -> dict:
        """Return a filter clause for this visibility level."""
        ...


class PublicVisibilityRule(VisibilityRule):
    def can_access(self, user: UserContext, doc_metadata: dict) -> bool:
        return True

    def build_filter_clause(self, user: UserContext) -> dict:
        return {"visibility": "public"}


class TeamVisibilityRule(VisibilityRule):
    def can_access(self, user: UserContext, doc_metadata: dict) -> bool:
        allowed_teams = doc_metadata.get("allowed_teams", [])
        return bool(set(user.team_ids) & set(allowed_teams))

    def build_filter_clause(self, user: UserContext) -> dict:
        return {"visibility": "team", "allowed_teams": user.team_ids}


class ConfidentialVisibilityRule(VisibilityRule):
    def can_access(self, user: UserContext, doc_metadata: dict) -> bool:
        allowed_users = doc_metadata.get("allowed_users", [])
        return user.user_id in allowed_users

    def build_filter_clause(self, user: UserContext) -> dict:
        return {"visibility": "confidential", "allowed_users": [user.user_id]}


class ChannelVisibilityRule(VisibilityRule):
    """Channel-shared docs: accessible to all members of the channel at upload time.

    Channel member user IDs are resolved at upload and stored in allowed_users,
    so the access check is identical to confidential (user_id in allowed_users).
    """
    def can_access(self, user: UserContext, doc_metadata: dict) -> bool:
        allowed_users = doc_metadata.get("allowed_users", [])
        return user.user_id in allowed_users

    def build_filter_clause(self, user: UserContext) -> dict:
        return {"visibility": "channel", "allowed_users": [user.user_id]}


class InternalVisibilityRule(VisibilityRule):
    """Internal docs: visible to all authenticated users in the same company.

    Sits between public (everyone) and team (specific teams). Use for
    company-wide policies, HR documents, engineering standards, etc.
    """
    def can_access(self, user: UserContext, doc_metadata: dict) -> bool:
        if not user.company_id:
            return False
        return user.company_id == doc_metadata.get("company_id")

    def build_filter_clause(self, user: UserContext) -> dict:
        # When user has no company, use a sentinel that matches nothing.
        return {"visibility": "internal", "company_id": user.company_id or "_no_match_"}


# Registry — add new visibility levels here
VISIBILITY_RULES: dict[str, VisibilityRule] = {
    "public": PublicVisibilityRule(),
    "internal": InternalVisibilityRule(),
    "team": TeamVisibilityRule(),
    "channel": ChannelVisibilityRule(),
    "confidential": ConfidentialVisibilityRule(),
}


def register_visibility_rule(name: str, rule: VisibilityRule) -> None:
    """Register a new visibility rule at runtime."""
    VISIBILITY_RULES[name] = rule


def build_scoped_visibility_filter(user: UserContext, scope: str = "all") -> dict:
    """Build a narrowed visibility filter based on a user-chosen scope.

    scope values:
      "all"           → full RBAC filter (default, same as build_visibility_filter)
      "personal"      → only documents owned by this user
      "team:<team_id>"→ public docs + docs shared with that specific team + own docs
    """
    if scope == "personal":
        return {"owner_id": user.user_id}

    if scope.startswith("team:"):
        team_id = scope[5:]
        # Validate the user actually belongs to this team (or is admin)
        if team_id not in user.team_ids and "admin" not in user.roles:
            return build_visibility_filter(user)  # fall back to full access
        return {"$or": [
            {"owner_id": user.user_id},
            {"visibility": "public"},
            {"visibility": "team", "allowed_teams": [team_id]},
        ]}

    # "all" or unrecognised → full filter
    return build_visibility_filter(user)


# ---------------------------------------------------------------------------
# Visibility filter builder (for vector DB queries)
# ---------------------------------------------------------------------------

def build_visibility_filter(user: UserContext) -> dict:
    """Build a metadata filter for vector DB queries enforcing RBAC.

    Returns a provider-agnostic filter dict with an "$or" structure:
    - Always include owner's own documents
    - Include documents matching each registered visibility rule
    """
    # Super admin or company admin sees everything (within their company scope, enforced at query layer)
    if user.is_super_admin or "admin" in user.roles:
        return {}

    clauses = []

    # Owner always sees their own docs
    clauses.append({"owner_id": user.user_id})

    # Each visibility rule contributes a clause
    for rule in VISIBILITY_RULES.values():
        clauses.append(rule.build_filter_clause(user))

    return {"$or": clauses}


# ---------------------------------------------------------------------------
# Document access checker (for non-query operations)
# ---------------------------------------------------------------------------

def check_document_access(user: UserContext | None, doc_metadata: dict) -> bool:
    """Check if a user can access a specific document.

    Args:
        user: UserContext or None (unauthenticated)
        doc_metadata: dict with keys: visibility, owner_id, allowed_teams, allowed_users
    """
    if user is None:
        return False

    # Admin bypass
    if user.is_super_admin or "admin" in user.roles:
        return True

    # Owner always has access
    if doc_metadata.get("owner_id") == user.user_id:
        return True

    # Delegate to the visibility rule
    visibility = doc_metadata.get("visibility", "")
    rule = VISIBILITY_RULES.get(visibility)
    if rule is None:
        raise ValueError(f"Unknown visibility level: {visibility!r}")

    return rule.can_access(user, doc_metadata)


# ---------------------------------------------------------------------------
# Team/DL permission checks
# ---------------------------------------------------------------------------

def can_manage_team(user: UserContext, team_created_by: str) -> bool:
    """Check if user can edit/delete a team (admin or team creator)."""
    if "admin" in user.roles:
        return True
    return user.user_id == team_created_by


def can_create_team(roles: list[str]) -> bool:
    """Check if user can create new teams (requires dl:manage permission)."""
    return has_permission(roles, "dl:manage")
