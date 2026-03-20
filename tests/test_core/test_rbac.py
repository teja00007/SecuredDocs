"""
TDD Test Cases — RBAC Module (src/core/rbac.py)

Tests for permission checking, visibility filter construction,
and document access control logic.
"""
import pytest

from src.core.rbac import (
    has_permission,
    build_visibility_filter,
    check_document_access,
    can_manage_team,
    can_create_team,
    UserContext,
    VISIBILITY_RULES,
    VisibilityRule,
    register_visibility_rule,
)


# ============================================================================
# PERMISSION CHECKING
# ============================================================================

class TestPermissionChecker:
    """Verify role-based permission checks."""

    def test_admin_has_all_permissions(self):
        """Admin role should pass any permission check."""
        assert has_permission(["admin"], "collection:read") is True
        assert has_permission(["admin"], "user:manage") is True
        assert has_permission(["admin"], "dl:manage") is True
        assert has_permission(["admin"], "compliance:manage") is True

    def test_analyst_has_read_permission(self):
        """Analyst role should have collection:read, document:read."""
        assert has_permission(["analyst"], "collection:read") is True
        assert has_permission(["analyst"], "document:read") is True
        assert has_permission(["analyst"], "query:execute") is True

    def test_analyst_lacks_admin_permission(self):
        """Analyst should NOT have user:manage."""
        assert has_permission(["analyst"], "user:manage") is False
        assert has_permission(["analyst"], "compliance:manage") is False

    def test_viewer_has_only_read(self):
        """Viewer should only have collection:read and query:execute."""
        assert has_permission(["viewer"], "collection:read") is True
        assert has_permission(["viewer"], "query:execute") is True
        assert has_permission(["viewer"], "document:write") is False
        assert has_permission(["viewer"], "dl:manage") is False

    def test_user_with_multiple_roles(self):
        """Permissions should be union of all assigned roles."""
        # viewer has query:execute, analyst has document:write
        assert has_permission(["viewer", "analyst"], "document:write") is True
        assert has_permission(["viewer", "analyst"], "query:execute") is True

    def test_unknown_role_has_no_permissions(self):
        """An unrecognized role name should grant no permissions."""
        assert has_permission(["superuser"], "collection:read") is False

    def test_empty_roles_list(self):
        """User with no roles should have no permissions."""
        assert has_permission([], "collection:read") is False


# ============================================================================
# VISIBILITY FILTER BUILDER
# ============================================================================

class TestVisibilityFilterBuilder:
    """Verify the metadata filter constructed for vector DB queries."""

    def _user(self, user_id="u1", roles=None, team_ids=None):
        return UserContext(
            user_id=user_id,
            roles=roles or ["viewer"],
            team_ids=team_ids or [],
        )

    def test_filter_includes_public_documents(self):
        """Filter should always match visibility='public'."""
        f = build_visibility_filter(self._user())
        clauses = f["$or"]
        assert any(c.get("visibility") == "public" for c in clauses)

    def test_filter_includes_owned_documents(self):
        """Filter should match owner_id=current_user.id regardless of visibility."""
        f = build_visibility_filter(self._user(user_id="u42"))
        clauses = f["$or"]
        assert any(c.get("owner_id") == "u42" for c in clauses)

    def test_filter_includes_team_documents_for_member(self):
        """User in 'backend-team' should see docs with allowed_teams containing 'backend-team'."""
        f = build_visibility_filter(self._user(team_ids=["backend-team"]))
        clauses = f["$or"]
        team_clause = next(c for c in clauses if c.get("visibility") == "team")
        assert "backend-team" in team_clause["allowed_teams"]

    def test_filter_excludes_team_documents_for_non_member(self):
        """User NOT in 'backend-team' should NOT see team-restricted docs for that DL."""
        f = build_visibility_filter(self._user(team_ids=[]))
        clauses = f["$or"]
        team_clause = next(c for c in clauses if c.get("visibility") == "team")
        assert team_clause["allowed_teams"] == []

    def test_filter_includes_confidential_for_allowed_user(self):
        """User in allowed_users list should see confidential docs."""
        f = build_visibility_filter(self._user(user_id="u5"))
        clauses = f["$or"]
        conf_clause = next(c for c in clauses if c.get("visibility") == "confidential")
        assert "u5" in conf_clause["allowed_users"]

    def test_filter_excludes_confidential_for_non_allowed_user(self):
        """User NOT in allowed_users should NOT see confidential docs (enforced at query time)."""
        f = build_visibility_filter(self._user(user_id="u5"))
        clauses = f["$or"]
        conf_clause = next(c for c in clauses if c.get("visibility") == "confidential")
        assert "u999" not in conf_clause["allowed_users"]

    def test_filter_user_with_no_teams(self):
        """User with empty team_ids should only see public + owned + explicitly allowed."""
        f = build_visibility_filter(self._user(team_ids=[]))
        clauses = f["$or"]
        team_clause = next(c for c in clauses if c.get("visibility") == "team")
        assert team_clause["allowed_teams"] == []

    def test_filter_user_with_multiple_teams(self):
        """User in multiple DLs should see team docs from ALL their DLs."""
        f = build_visibility_filter(self._user(team_ids=["t1", "t2", "t3"]))
        clauses = f["$or"]
        team_clause = next(c for c in clauses if c.get("visibility") == "team")
        assert set(team_clause["allowed_teams"]) == {"t1", "t2", "t3"}

    def test_filter_structure_is_valid_for_chroma(self):
        """Returned filter dict should have $or key with list of clauses."""
        f = build_visibility_filter(self._user())
        assert "$or" in f
        assert isinstance(f["$or"], list)
        assert len(f["$or"]) > 0

    def test_filter_structure_is_valid_for_qdrant(self):
        """Returned filter should be convertible to valid Qdrant filter payload."""
        f = build_visibility_filter(self._user(team_ids=["t1"]))
        assert "$or" in f
        # Each clause should be a dict
        for clause in f["$or"]:
            assert isinstance(clause, dict)


# ============================================================================
# DOCUMENT ACCESS CHECKER
# ============================================================================

class TestDocumentAccessChecker:
    """Verify per-document access decisions."""

    def _user(self, user_id="u1", roles=None, team_ids=None):
        return UserContext(
            user_id=user_id,
            roles=roles or ["viewer"],
            team_ids=team_ids or [],
        )

    def test_owner_can_access_own_public_doc(self):
        """Document owner always has access."""
        doc = {"visibility": "public", "owner_id": "u1", "allowed_teams": [], "allowed_users": []}
        assert check_document_access(self._user(user_id="u1"), doc) is True

    def test_owner_can_access_own_confidential_doc(self):
        """Document owner always has access even if confidential."""
        doc = {"visibility": "confidential", "owner_id": "u1", "allowed_teams": [], "allowed_users": []}
        assert check_document_access(self._user(user_id="u1"), doc) is True

    def test_any_user_can_access_public_doc(self):
        """Any authenticated user can access a public document."""
        doc = {"visibility": "public", "owner_id": "u-other", "allowed_teams": [], "allowed_users": []}
        assert check_document_access(self._user(user_id="u99"), doc) is True

    def test_team_member_can_access_team_doc(self):
        """User in an assigned DL can access a team-visibility document."""
        doc = {"visibility": "team", "owner_id": "u-other", "allowed_teams": ["t1"], "allowed_users": []}
        assert check_document_access(self._user(team_ids=["t1"]), doc) is True

    def test_non_team_member_cannot_access_team_doc(self):
        """User NOT in any assigned DL cannot access a team-visibility document."""
        doc = {"visibility": "team", "owner_id": "u-other", "allowed_teams": ["t1"], "allowed_users": []}
        assert check_document_access(self._user(team_ids=["t2"]), doc) is False

    def test_allowed_user_can_access_confidential_doc(self):
        """User explicitly in allowed_users can access confidential document."""
        doc = {"visibility": "confidential", "owner_id": "u-other", "allowed_teams": [], "allowed_users": ["u1"]}
        assert check_document_access(self._user(user_id="u1"), doc) is True

    def test_non_allowed_user_cannot_access_confidential_doc(self):
        """User not in allowed_users and not owner cannot access confidential document."""
        doc = {"visibility": "confidential", "owner_id": "u-other", "allowed_teams": [], "allowed_users": ["u5"]}
        assert check_document_access(self._user(user_id="u1"), doc) is False

    def test_admin_can_access_any_document(self):
        """Admin role should bypass all access checks."""
        doc = {"visibility": "confidential", "owner_id": "u-other", "allowed_teams": [], "allowed_users": []}
        assert check_document_access(self._user(roles=["admin"]), doc) is True

    def test_access_check_with_multiple_teams_on_doc(self):
        """Doc assigned to [team-a, team-b] — user in team-b should have access."""
        doc = {"visibility": "team", "owner_id": "u-other", "allowed_teams": ["team-a", "team-b"], "allowed_users": []}
        assert check_document_access(self._user(team_ids=["team-b"]), doc) is True

    def test_access_check_returns_false_for_anonymous(self):
        """None/unauthenticated user should be denied access."""
        doc = {"visibility": "public", "owner_id": "u1", "allowed_teams": [], "allowed_users": []}
        assert check_document_access(None, doc) is False


# ============================================================================
# TEAM/DL PERMISSION
# ============================================================================

class TestTeamPermission:
    """Verify who can manage (create/edit/delete) Distribution Lists."""

    def _user(self, user_id="u1", roles=None, team_ids=None):
        return UserContext(
            user_id=user_id,
            roles=roles or ["viewer"],
            team_ids=team_ids or [],
        )

    def test_admin_can_manage_any_team(self):
        """Admin role can edit/delete any DL."""
        assert can_manage_team(self._user(roles=["admin"]), "u-other") is True

    def test_creator_can_manage_own_team(self):
        """The user who created the DL can edit/delete it."""
        assert can_manage_team(self._user(user_id="u1"), "u1") is True

    def test_non_creator_non_admin_cannot_manage_team(self):
        """Regular user who didn't create the DL cannot edit/delete it."""
        assert can_manage_team(self._user(user_id="u1"), "u-other") is False

    def test_any_user_with_dl_manage_permission_can_create(self):
        """User with dl:manage permission can create new DLs."""
        assert can_create_team(["analyst"]) is True
        assert can_create_team(["admin"]) is True

    def test_viewer_cannot_create_team(self):
        """Viewer role should not be able to create DLs."""
        assert can_create_team(["viewer"]) is False


# ============================================================================
# VISIBILITY RULE REGISTRY (Fix #11)
# ============================================================================

class TestVisibilityRuleRegistry:
    """Verify pluggable visibility rules via registry pattern."""

    def test_registry_contains_public_rule(self):
        """VISIBILITY_RULES should contain 'public' key."""
        assert "public" in VISIBILITY_RULES

    def test_registry_contains_team_rule(self):
        """VISIBILITY_RULES should contain 'team' key."""
        assert "team" in VISIBILITY_RULES

    def test_registry_contains_confidential_rule(self):
        """VISIBILITY_RULES should contain 'confidential' key."""
        assert "confidential" in VISIBILITY_RULES

    def test_adding_custom_visibility_rule(self):
        """Registering a new VisibilityRule('internal') should work."""

        class InternalRule(VisibilityRule):
            def can_access(self, user, doc_metadata):
                return True  # all internal users

            def build_filter_clause(self, user):
                return {"visibility": "internal"}

        register_visibility_rule("internal", InternalRule())
        assert "internal" in VISIBILITY_RULES
        # Cleanup
        del VISIBILITY_RULES["internal"]

    def test_filter_builder_uses_registry(self):
        """build_visibility_filter should iterate VISIBILITY_RULES, not hardcode levels."""
        user = UserContext(user_id="u1", roles=["viewer"], team_ids=[])
        f = build_visibility_filter(user)
        # Should have clauses for each registered visibility + owner clause
        assert len(f["$or"]) == len(VISIBILITY_RULES) + 1  # +1 for owner clause

    def test_access_checker_uses_registry(self):
        """check_document_access should delegate to the rule for the doc's visibility."""
        user = UserContext(user_id="u1", roles=["viewer"], team_ids=[])
        doc = {"visibility": "public", "owner_id": "u-other", "allowed_teams": [], "allowed_users": []}
        # Public rule always returns True
        assert check_document_access(user, doc) is True

    def test_unknown_visibility_raises(self):
        """Document with unregistered visibility value should raise ValueError."""
        user = UserContext(user_id="u1", roles=["viewer"], team_ids=[])
        doc = {"visibility": "top_secret", "owner_id": "u-other", "allowed_teams": [], "allowed_users": []}
        with pytest.raises(ValueError, match="top_secret"):
            check_document_access(user, doc)
