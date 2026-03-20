"""LDAP / Active Directory authentication service.

Authenticates users against an LDAP/AD server and optionally maps LDAP
groups to Nexus roles on every login.

Install: pip install ldap3

Config (.env)
-------------
    LDAP_ENABLED=true
    LDAP_SERVER=ldap://dc.example.com:389   # or ldaps://... for TLS
    LDAP_BIND_DN=CN=svc_nexus,OU=ServiceAccounts,DC=example,DC=com
    LDAP_BIND_PASSWORD=s3cr3t
    LDAP_BASE_DN=DC=example,DC=com
    LDAP_USER_FILTER=(sAMAccountName={username})   # AD style
    LDAP_GROUP_BASE_DN=OU=Groups,DC=example,DC=com
    LDAP_GROUP_FILTER=(member={user_dn})
    LDAP_GROUP_ROLE_MAP={"Domain Admins": "admin", "Nexus Users": "editor"}
    LDAP_TLS=false                          # set true for ldaps://

Group → Role mapping
--------------------
The LDAP_GROUP_ROLE_MAP JSON maps LDAP group CNs (common names) to Nexus
role names.  On login the service fetches the user's group memberships and
assigns the highest-priority Nexus role.  Existing roles are preserved if
the user already has a role not found in the map.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from src.core.exceptions import AuthenticationError

if TYPE_CHECKING:
    from src.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


class LDAPAuthService:
    """Authenticates users via LDAP and syncs group → role mappings."""

    def __init__(
        self,
        server_url: str = "ldap://localhost:389",
        bind_dn: str = "",
        bind_password: str = "",
        base_dn: str = "DC=example,DC=com",
        user_filter: str = "(sAMAccountName={username})",
        group_base_dn: str = "",
        group_filter: str = "(member={user_dn})",
        group_role_map: dict[str, str] | None = None,
        use_tls: bool = False,
    ) -> None:
        self._server_url = server_url
        self._bind_dn = bind_dn
        self._bind_password = bind_password
        self._base_dn = base_dn
        self._user_filter = user_filter
        self._group_base_dn = group_base_dn or base_dn
        self._group_filter = group_filter
        self._group_role_map: dict[str, str] = group_role_map or {}
        self._use_tls = use_tls

    # ── Public API ────────────────────────────────────────────────────────────

    async def authenticate(
        self,
        username: str,
        password: str,
        user_repo: "UserRepository",
        company_id: str | None = None,
    ):
        """Authenticate username/password against LDAP.

        1. Binds with service account to find the user DN.
        2. Re-binds with the user DN + supplied password.
        3. Creates or updates the local Nexus user.
        4. Syncs group memberships → roles.

        Returns the Nexus User ORM object.
        Raises AuthenticationError on failure.
        """
        try:
            from ldap3 import Server, Connection, SIMPLE, SUBTREE, ALL
            from ldap3.core.exceptions import LDAPBindError, LDAPException
        except ImportError:
            raise RuntimeError(
                "ldap3 not installed. Run: pip install ldap3"
            )

        # Step 1 — service-account bind to find the user DN
        server = Server(self._server_url, get_info=ALL, use_ssl=self._use_tls)
        try:
            svc_conn = Connection(
                server,
                user=self._bind_dn,
                password=self._bind_password,
                authentication=SIMPLE,
                auto_bind=True,
            )
        except LDAPException as e:
            logger.error("LDAP service bind failed: %s", e)
            raise AuthenticationError("LDAP service unavailable")

        search_filter = self._user_filter.format(username=username)
        svc_conn.search(
            self._base_dn,
            search_filter,
            search_scope=SUBTREE,
            attributes=["cn", "mail", "displayName", "sAMAccountName"],
        )

        if not svc_conn.entries:
            svc_conn.unbind()
            raise AuthenticationError("Invalid credentials")

        entry = svc_conn.entries[0]
        user_dn = entry.entry_dn
        email = str(entry["mail"].value) if "mail" in entry else f"{username}@ldap.local"
        display_name = str(entry["displayName"].value) if "displayName" in entry else username

        # Fetch group memberships while we have the service connection
        groups = self._fetch_groups(svc_conn, user_dn)
        svc_conn.unbind()

        # Step 2 — bind with the real user to verify the password
        try:
            user_conn = Connection(
                server,
                user=user_dn,
                password=password,
                authentication=SIMPLE,
                auto_bind=True,
            )
            user_conn.unbind()
        except LDAPBindError:
            raise AuthenticationError("Invalid credentials")
        except LDAPException as e:
            logger.error("LDAP user bind error: %s", e)
            raise AuthenticationError("LDAP authentication error")

        # Step 3 — upsert local Nexus user
        user = await user_repo.get_by_username(username)
        if user is None:
            user = await user_repo.get_by_email(email)

        if user is None:
            from src.models.user import User
            from src.core.security import hash_password
            user = User(
                id=str(uuid.uuid4()),
                username=username,
                email=email,
                hashed_password=hash_password(uuid.uuid4().hex),  # unusable password
                display_name=display_name,
                is_active=True,
                company_id=company_id,
            )
            user = await user_repo.create(user)
            logger.info("LDAP: created new Nexus user %s", username)
        else:
            logger.debug("LDAP: found existing Nexus user %s", username)

        # Step 4 — sync roles from group membership
        await self._sync_roles(user, groups, user_repo)

        return user

    # ── Internal ─────────────────────────────────────────────────────────────

    def _fetch_groups(self, conn, user_dn: str) -> list[str]:
        """Return list of LDAP group CNs the user belongs to."""
        if not self._group_role_map:
            return []
        search_filter = self._group_filter.format(user_dn=user_dn)
        conn.search(
            self._group_base_dn,
            search_filter,
            attributes=["cn"],
        )
        return [str(e["cn"].value) for e in conn.entries if "cn" in e]

    async def _sync_roles(self, user, groups: list[str], user_repo: "UserRepository") -> None:
        """Map LDAP groups → Nexus roles and assign them."""
        if not self._group_role_map or not groups:
            return

        target_roles: set[str] = set()
        for group_cn in groups:
            role_name = self._group_role_map.get(group_cn)
            if role_name:
                target_roles.add(role_name)

        for role_name in target_roles:
            role = await user_repo.get_role_by_name(role_name)
            if role:
                try:
                    await user_repo.assign_role(user.id, role.id)
                    logger.debug("LDAP: assigned role %r to %s", role_name, user.username)
                except Exception:
                    pass  # role already assigned


# ── Factory ───────────────────────────────────────────────────────────────────

def get_ldap_auth_service() -> LDAPAuthService | None:
    """Return a configured LDAPAuthService or None if LDAP is disabled."""
    from src.config import get_settings
    s = get_settings()

    if not getattr(s, "LDAP_ENABLED", False):
        return None

    group_role_map: dict[str, str] = {}
    raw_map = getattr(s, "LDAP_GROUP_ROLE_MAP", "{}")
    try:
        group_role_map = json.loads(raw_map)
    except (json.JSONDecodeError, TypeError):
        logger.warning("LDAP_GROUP_ROLE_MAP is not valid JSON — group sync disabled.")

    return LDAPAuthService(
        server_url=getattr(s, "LDAP_SERVER", "ldap://localhost:389"),
        bind_dn=getattr(s, "LDAP_BIND_DN", ""),
        bind_password=getattr(s, "LDAP_BIND_PASSWORD", ""),
        base_dn=getattr(s, "LDAP_BASE_DN", "DC=example,DC=com"),
        user_filter=getattr(s, "LDAP_USER_FILTER", "(sAMAccountName={username})"),
        group_base_dn=getattr(s, "LDAP_GROUP_BASE_DN", ""),
        group_filter=getattr(s, "LDAP_GROUP_FILTER", "(member={user_dn})"),
        group_role_map=group_role_map,
        use_tls=getattr(s, "LDAP_TLS", False),
    )
