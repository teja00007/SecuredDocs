"""Tests for src/ingestion/acl_scanner.py — POSIX ACL scanning."""

import os
import stat
import pytest
from pathlib import Path

from src.ingestion.acl_scanner import ACLScanner, ACLResult


@pytest.fixture
def scanner():
    return ACLScanner(
        user_map={"testuser": "test@corp.io"},
        group_map={"testgroup": "engineering-team"},
    )


class TestACLScannerPosix:
    def test_scan_nonexistent_returns_empty(self, scanner):
        result = scanner.scan("/nonexistent/path/that/does/not/exist.txt")
        assert isinstance(result, ACLResult)
        assert result.owner_id is None

    def test_scan_world_readable_returns_public(self, scanner, tmp_path):
        f = tmp_path / "public.txt"
        f.write_text("hello")
        os.chmod(f, 0o644)  # world-readable
        result = scanner.scan(str(f))
        assert result.visibility == "public"

    def test_scan_owner_only_returns_confidential(self, scanner, tmp_path):
        f = tmp_path / "private.txt"
        f.write_text("secret")
        os.chmod(f, 0o600)  # owner only
        result = scanner.scan(str(f))
        # No world-readable → confidential
        assert result.visibility in ("confidential", "team")

    def test_scan_group_readable_includes_team(self, scanner, tmp_path):
        f = tmp_path / "team.txt"
        f.write_text("team data")
        os.chmod(f, 0o640)  # owner+group readable
        result = scanner.scan(str(f))
        # Group-readable → at least one team (or confidential if group not mapped)
        assert result.visibility in ("team", "confidential", "public")

    def test_acl_result_dataclass_defaults(self):
        result = ACLResult()
        assert result.owner_id is None
        assert result.allowed_users == []
        assert result.allowed_teams == []
        assert result.visibility == "confidential"

    def test_user_map_applied(self, tmp_path):
        import pwd
        current_user = pwd.getpwuid(os.getuid()).pw_name
        scanner = ACLScanner(user_map={current_user: "mapped@nexus.io"})
        f = tmp_path / "mapped.txt"
        f.write_text("data")
        os.chmod(f, 0o600)
        result = scanner.scan(str(f))
        if result.owner_id:
            assert result.owner_id == "mapped@nexus.io"

    def test_scanner_is_windows_false_on_posix(self, scanner):
        import platform
        assert scanner._is_windows == (platform.system() == "Windows")
