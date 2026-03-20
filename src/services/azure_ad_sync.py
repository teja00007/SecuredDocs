"""Azure AD group sync via Microsoft Graph API.

On every Microsoft OAuth login, fetches the user's transitive group
memberships from the Graph API and maps them to Nexus roles.

This augments the existing Microsoft OAuth flow in `src/api/v1/oauth.py`.
Call `sync_azure_ad_groups()` after a successful token exchange.

Install: httpx (already a dependency)

Config (.env)
-------------
    AZURE_AD_SYNC_ENABLED=true
    MICROSOFT_TENANT_ID=<your-tenant-id>
    # MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET already exist
    AZURE_AD_GROUP_ROLE_MAP={"<group-object-id>": "admin", "<group-id>": "editor"}

Notes
-----
- The Graph API requires the `GroupMember.Read.All` (application) or
  `User.Read` + `Group.Read.All` (delegated) permission.
- With delegated tokens (what OAuth gives us) we use the /me/memberOf
  endpoint which works with `User.Read` scope.
- For app-level sync (service account), use a client-credentials token.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from src.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

_GRAPH_ME_GROUPS = "https://graph.microsoft.com/v1.0/me/memberOf"
_GRAPH_TRANSITIVE = "https://graph.microsoft.com/v1.0/me/transitiveMemberOf/microsoft.graph.group"


async def sync_azure_ad_groups(
    access_token: str,
    user,
    user_repo: "UserRepository",
    group_role_map: dict[str, str],
) -> list[str]:
    """Fetch the user's Azure AD group memberships and assign Nexus roles.

    Parameters
    ----------
    access_token:
        The Microsoft OAuth access token obtained during login.
    user:
        The Nexus User ORM object (already created/updated by the OAuth flow).
    user_repo:
        User repository for role assignment.
    group_role_map:
        Mapping of Azure AD group object IDs (or display names) to Nexus role
        names.  Example: ``{"a1b2c3...": "admin", "d4e5f6...": "editor"}``.

    Returns
    -------
    list[str]
        The Nexus role names that were assigned.
    """
    if not group_role_map:
        return []

    groups = await _fetch_groups(access_token)
    assigned: list[str] = []

    for group in groups:
        group_id = group.get("id", "")
        group_name = group.get("displayName", "")

        # Match on object ID first, then display name
        role_name = group_role_map.get(group_id) or group_role_map.get(group_name)
        if not role_name:
            continue

        role = await user_repo.get_role_by_name(role_name)
        if role:
            try:
                await user_repo.assign_role(user.id, role.id)
                assigned.append(role_name)
                logger.debug(
                    "Azure AD sync: assigned role %r to %s (group %r)",
                    role_name, user.username, group_name or group_id,
                )
            except Exception:
                pass  # already assigned

    return assigned


async def _fetch_groups(access_token: str) -> list[dict]:
    """Call Microsoft Graph /me/memberOf and return group list."""
    headers = {"Authorization": f"Bearer {access_token}"}
    groups: list[dict] = []

    url: str | None = _GRAPH_ME_GROUPS
    async with httpx.AsyncClient(timeout=10.0) as client:
        while url:
            try:
                r = await client.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
            except Exception as exc:
                logger.warning("Azure AD group fetch failed: %s", exc)
                break

            for item in data.get("value", []):
                # Filter to only Group objects (memberOf can include other types)
                if item.get("@odata.type") == "#microsoft.graph.group":
                    groups.append(item)

            url = data.get("@odata.nextLink")  # pagination

    return groups


# ── Helper for the OAuth callback ─────────────────────────────────────────────

def get_group_role_map() -> dict[str, str]:
    """Parse AZURE_AD_GROUP_ROLE_MAP from settings."""
    from src.config import get_settings
    s = get_settings()
    raw = getattr(s, "AZURE_AD_GROUP_ROLE_MAP", "{}")
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("AZURE_AD_GROUP_ROLE_MAP is not valid JSON.")
        return {}


def is_azure_ad_sync_enabled() -> bool:
    from src.config import get_settings
    return getattr(get_settings(), "AZURE_AD_SYNC_ENABLED", False)
