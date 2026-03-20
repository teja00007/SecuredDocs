"""Tests for src/services/ldap_auth_service.py — LDAP authentication (mocked)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.exceptions import AuthenticationError
from src.services.ldap_auth_service import LDAPAuthService, get_ldap_auth_service


class TestLDAPAuthServiceFactory:
    def test_returns_none_when_disabled(self):
        with patch("src.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(LDAP_ENABLED=False)
            svc = get_ldap_auth_service()
        assert svc is None

    def test_returns_service_when_enabled(self):
        with patch("src.config.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                LDAP_ENABLED=True,
                LDAP_SERVER="ldap://localhost:389",
                LDAP_BIND_DN="cn=svc,dc=example,dc=com",
                LDAP_BIND_PASSWORD="secret",
                LDAP_BASE_DN="dc=example,dc=com",
                LDAP_USER_FILTER="(sAMAccountName={username})",
                LDAP_GROUP_BASE_DN="",
                LDAP_GROUP_FILTER="(member={user_dn})",
                LDAP_GROUP_ROLE_MAP="{}",
                LDAP_TLS=False,
            )
            svc = get_ldap_auth_service()
        assert isinstance(svc, LDAPAuthService)


class TestLDAPAuthServiceAuthenticate:
    def _make_service(self):
        return LDAPAuthService(
            server_url="ldap://localhost:389",
            bind_dn="cn=svc,dc=example,dc=com",
            bind_password="secret",
            base_dn="dc=example,dc=com",
            group_role_map={"Domain Admins": "admin", "Nexus Users": "editor"},
        )

    @pytest.mark.asyncio
    async def test_raises_when_ldap3_missing(self):
        svc = self._make_service()
        user_repo = AsyncMock()
        with patch.dict("sys.modules", {"ldap3": None}):
            with pytest.raises(RuntimeError, match="ldap3 not installed"):
                await svc.authenticate("alice", "pass", user_repo)

    @pytest.mark.asyncio
    async def test_raises_when_no_user_found(self):
        """When LDAP search returns empty entries, raise AuthenticationError."""
        svc = self._make_service()
        user_repo = AsyncMock()

        mock_ldap3 = MagicMock()
        # Connection auto-bind succeeds
        mock_conn_instance = MagicMock()
        mock_conn_instance.entries = []  # no user found in LDAP
        mock_ldap3.Connection.return_value = mock_conn_instance
        mock_ldap3.SIMPLE = "SIMPLE"
        mock_ldap3.SUBTREE = "SUBTREE"
        mock_ldap3.ALL = "ALL"
        mock_ldap3.Server.return_value = MagicMock()
        mock_ldap3.core = MagicMock()
        mock_ldap3.core.exceptions = MagicMock()
        mock_ldap3.core.exceptions.LDAPException = Exception
        mock_ldap3.core.exceptions.LDAPBindError = Exception

        with patch.dict("sys.modules", {
            "ldap3": mock_ldap3,
            "ldap3.core": mock_ldap3.core,
            "ldap3.core.exceptions": mock_ldap3.core.exceptions,
        }):
            with pytest.raises(AuthenticationError):
                await svc.authenticate("unknown_user", "pass", user_repo)

    def test_group_role_map_applied(self):
        svc = self._make_service()
        assert svc._group_role_map == {"Domain Admins": "admin", "Nexus Users": "editor"}

    def test_fetch_groups_returns_empty_without_map(self):
        svc = LDAPAuthService()  # no group_role_map
        mock_conn = MagicMock()
        result = svc._fetch_groups(mock_conn, "cn=alice,dc=example,dc=com")
        assert result == []
        mock_conn.search.assert_not_called()
