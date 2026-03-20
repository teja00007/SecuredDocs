"""File system ACL scanner — maps Windows SIDs / POSIX groups to Nexus permissions.

Scans the file system ACL of a document and returns Nexus-compatible
allowed_teams and allowed_users lists derived from the OS-level permissions.

Supported platforms
-------------------
- **macOS / Linux (POSIX)**: reads POSIX owner UID, GID, and mode bits.
  Maps group names to Nexus team names and owner to a Nexus user.
- **Windows**: reads DACL entries via `pywin32` and maps SIDs to Nexus
  user/team identifiers stored in the `ServiceAccount` or `User` tables.

Install (Windows only): pip install pywin32

Usage
-----
    from src.ingestion.acl_scanner import ACLScanner

    scanner = ACLScanner(user_map={"DOMAIN\\alice": "alice@corp.io"}, group_map={"Domain Users": "engineering"})
    result = scanner.scan("/path/to/file.pdf")
    print(result.allowed_users)  # ["alice@corp.io"]
    print(result.allowed_teams)  # ["engineering"]
"""

from __future__ import annotations

import logging
import os
import platform
import stat
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ACLResult:
    """RBAC-compatible permission result derived from file system ACLs."""
    owner_id: str | None = None
    allowed_users: list[str] = field(default_factory=list)
    allowed_teams: list[str] = field(default_factory=list)
    visibility: str = "confidential"   # conservative default


class ACLScanner:
    """Scan a file path and derive Nexus RBAC permissions from OS-level ACLs.

    Parameters
    ----------
    user_map:
        Mapping from OS username / Windows SAM account name to Nexus user ID
        or email. E.g. ``{"alice": "alice@corp.io"}``.
    group_map:
        Mapping from OS group name / Windows group CN to Nexus team name.
        E.g. ``{"engineering": "engineering-team"}``.
    """

    def __init__(
        self,
        user_map: dict[str, str] | None = None,
        group_map: dict[str, str] | None = None,
    ) -> None:
        self._user_map = user_map or {}
        self._group_map = group_map or {}
        self._is_windows = platform.system() == "Windows"

    def scan(self, file_path: str) -> ACLResult:
        """Scan the file at *file_path* and return an ACLResult."""
        path = Path(file_path)
        if not path.exists():
            logger.warning("ACLScanner: file not found: %s", file_path)
            return ACLResult()

        if self._is_windows:
            return self._scan_windows(str(path))
        return self._scan_posix(str(path))

    # ── POSIX ─────────────────────────────────────────────────────────────────

    def _scan_posix(self, file_path: str) -> ACLResult:
        result = ACLResult()
        try:
            st = os.stat(file_path)
            mode = st.st_mode

            # Owner
            import pwd, grp
            try:
                owner_name = pwd.getpwuid(st.st_uid).pw_name
                result.owner_id = self._user_map.get(owner_name, owner_name)
                result.allowed_users.append(result.owner_id)
            except KeyError:
                pass

            # Group — map to Nexus team if world-readable or group-readable
            if mode & stat.S_IRGRP:
                try:
                    group_name = grp.getgrgid(st.st_gid).gr_name
                    nexus_team = self._group_map.get(group_name, group_name)
                    result.allowed_teams.append(nexus_team)
                except KeyError:
                    pass

            # World-readable → public
            if mode & stat.S_IROTH:
                result.visibility = "public"
            elif result.allowed_teams:
                result.visibility = "team"
            elif result.allowed_users:
                result.visibility = "confidential"

        except Exception as e:
            logger.warning("POSIX ACL scan failed for %s: %s", file_path, e)

        return result

    # ── Windows ───────────────────────────────────────────────────────────────

    def _scan_windows(self, file_path: str) -> ACLResult:
        result = ACLResult()
        try:
            import win32security
            import win32con
        except ImportError:
            logger.warning(
                "pywin32 not installed — Windows ACL scanning disabled. "
                "Run: pip install pywin32"
            )
            return result

        try:
            sd = win32security.GetFileSecurity(
                file_path,
                win32security.DACL_SECURITY_INFORMATION | win32security.OWNER_SECURITY_INFORMATION,
            )
        except Exception as e:
            logger.warning("Windows ACL read failed for %s: %s", file_path, e)
            return result

        # Owner
        owner_sid = sd.GetSecurityDescriptorOwner()
        owner_name = self._resolve_sid(owner_sid)
        if owner_name:
            nexus_user = self._user_map.get(owner_name, owner_name)
            result.owner_id = nexus_user
            result.allowed_users.append(nexus_user)

        # DACL entries
        dacl = sd.GetSecurityDescriptorDacl()
        if dacl is None:
            result.visibility = "public"
            return result

        everyone_sid = win32security.CreateWellKnownSid(win32security.WinWorldSid, None)

        for i in range(dacl.GetAceCount()):
            ace = dacl.GetAce(i)
            ace_type, ace_flags = ace[0]
            ace_sid = ace[2]

            # Allow ACE only
            if ace_type != win32con.ACCESS_ALLOWED_ACE_TYPE:
                continue

            if ace_sid == everyone_sid:
                result.visibility = "public"
                continue

            account_name = self._resolve_sid(ace_sid)
            if not account_name:
                continue

            # Determine if it's a group or user
            try:
                _, _, sid_type = win32security.LookupAccountSid(None, ace_sid)
                # SidTypeGroup=2, SidTypeAlias=4, SidTypeWellKnownGroup=5
                if sid_type in (2, 4, 5):
                    nexus_team = self._group_map.get(account_name, account_name)
                    if nexus_team not in result.allowed_teams:
                        result.allowed_teams.append(nexus_team)
                else:
                    nexus_user = self._user_map.get(account_name, account_name)
                    if nexus_user not in result.allowed_users:
                        result.allowed_users.append(nexus_user)
            except Exception:
                pass

        if result.visibility != "public":
            result.visibility = "team" if result.allowed_teams else "confidential"

        return result

    @staticmethod
    def _resolve_sid(sid) -> str | None:
        """Convert a Windows SID to a SAM account name (DOMAIN\\user)."""
        try:
            import win32security
            name, domain, _ = win32security.LookupAccountSid(None, sid)
            return f"{domain}\\{name}" if domain else name
        except Exception:
            return None
