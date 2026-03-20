"""
TDD Test Cases — Security Module (src/core/security.py)

Tests for JWT token management and password hashing.
"""
import pytest
from datetime import timedelta, datetime, timezone

from jose import jwt

from src.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    decode_access_token,
    create_refresh_token,
    decode_refresh_token,
    _DEFAULT_SECRET_KEY,
    _DEFAULT_ALGORITHM,
)
from src.core.exceptions import AuthenticationError


# ============================================================================
# PASSWORD HASHING
# ============================================================================

class TestPasswordHashing:
    """Verify bcrypt password hash and verify cycle."""

    def test_hash_password_returns_bcrypt_string(self):
        """hash_password('secret') should return a bcrypt hash starting with $2b$."""
        hashed = hash_password("secret")
        assert hashed.startswith("$2b$")

    def test_hash_password_different_each_time(self):
        """Two calls with same password should produce different hashes (salt)."""
        h1 = hash_password("secret")
        h2 = hash_password("secret")
        assert h1 != h2

    def test_verify_password_correct(self):
        """verify_password('secret', hashed) should return True for matching password."""
        hashed = hash_password("secret")
        assert verify_password("secret", hashed) is True

    def test_verify_password_wrong(self):
        """verify_password('wrong', hashed) should return False."""
        hashed = hash_password("secret")
        assert verify_password("wrong", hashed) is False

    def test_verify_password_empty_string(self):
        """verify_password('', hashed) should return False."""
        hashed = hash_password("secret")
        assert verify_password("", hashed) is False

    def test_hash_password_empty_string_raises(self):
        """hash_password('') should raise ValueError — don't allow empty passwords."""
        with pytest.raises(ValueError, match="empty"):
            hash_password("")

    def test_hash_password_unicode(self):
        """hash_password with unicode characters should work correctly."""
        hashed = hash_password("пароль🔑")
        assert verify_password("пароль🔑", hashed) is True
        assert verify_password("wrong", hashed) is False


# ============================================================================
# JWT ACCESS TOKEN
# ============================================================================

class TestAccessToken:
    """Verify JWT access token creation and validation."""

    def test_create_access_token_returns_string(self):
        """create_access_token(data) should return a JWT string."""
        token = create_access_token({"sub": "user-1"})
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_access_token_contains_user_id(self):
        """Decoded token payload should contain 'sub' with user_id."""
        token = create_access_token({"sub": "user-123"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user-123"

    def test_create_access_token_contains_roles(self):
        """Decoded token should contain 'roles' list."""
        token = create_access_token({"sub": "user-1", "roles": ["admin", "analyst"]})
        payload = decode_access_token(token)
        assert payload["roles"] == ["admin", "analyst"]

    def test_create_access_token_contains_team_ids(self):
        """Decoded token should contain 'team_ids' list."""
        token = create_access_token({"sub": "user-1", "team_ids": ["t1", "t2"]})
        payload = decode_access_token(token)
        assert payload["team_ids"] == ["t1", "t2"]

    def test_create_access_token_has_expiry(self):
        """Token should have 'exp' claim set to now + configured duration."""
        token = create_access_token({"sub": "user-1"})
        payload = decode_access_token(token)
        assert "exp" in payload

    def test_create_access_token_custom_expiry(self):
        """create_access_token(data, expires_delta=timedelta(hours=1)) should respect custom expiry."""
        before = datetime.now(timezone.utc)
        token = create_access_token({"sub": "user-1"}, expires_delta=timedelta(hours=1))
        payload = decode_access_token(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        # Should expire ~1 hour from now
        assert (exp - before).total_seconds() > 3500
        assert (exp - before).total_seconds() < 3700

    def test_decode_access_token_valid(self):
        """decode_access_token(valid_token) should return the payload dict."""
        token = create_access_token({"sub": "user-1", "roles": ["viewer"]})
        payload = decode_access_token(token)
        assert payload["sub"] == "user-1"
        assert payload["roles"] == ["viewer"]

    def test_decode_access_token_expired_raises(self):
        """decode_access_token(expired_token) should raise AuthenticationError."""
        token = create_access_token(
            {"sub": "user-1"}, expires_delta=timedelta(seconds=-1)
        )
        with pytest.raises(AuthenticationError):
            decode_access_token(token)

    def test_decode_access_token_invalid_signature_raises(self):
        """Token signed with wrong secret should raise AuthenticationError."""
        token = create_access_token({"sub": "user-1"}, secret_key="correct-secret")
        with pytest.raises(AuthenticationError):
            decode_access_token(token, secret_key="wrong-secret")

    def test_decode_access_token_malformed_raises(self):
        """decode_access_token('not.a.jwt') should raise AuthenticationError."""
        with pytest.raises(AuthenticationError):
            decode_access_token("not.a.jwt")

    def test_decode_access_token_missing_sub_raises(self):
        """Token without 'sub' claim should raise AuthenticationError."""
        token = jwt.encode(
            {"roles": ["admin"], "type": "access", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            _DEFAULT_SECRET_KEY,
            algorithm=_DEFAULT_ALGORITHM,
        )
        with pytest.raises(AuthenticationError, match="sub"):
            decode_access_token(token)


# ============================================================================
# JWT REFRESH TOKEN
# ============================================================================

class TestRefreshToken:
    """Verify JWT refresh token creation and validation."""

    def test_create_refresh_token_returns_string(self):
        """create_refresh_token(user_id) should return a JWT string."""
        token = create_refresh_token("user-1")
        assert isinstance(token, str)

    def test_refresh_token_longer_expiry_than_access(self):
        """Refresh token expiry should be longer than access token expiry."""
        access = create_access_token({"sub": "user-1"})
        refresh = create_refresh_token("user-1")
        a_payload = jwt.decode(access, _DEFAULT_SECRET_KEY, algorithms=[_DEFAULT_ALGORITHM])
        r_payload = jwt.decode(refresh, _DEFAULT_SECRET_KEY, algorithms=[_DEFAULT_ALGORITHM])
        assert r_payload["exp"] > a_payload["exp"]

    def test_refresh_token_contains_user_id(self):
        """Decoded refresh token should contain 'sub' with user_id."""
        token = create_refresh_token("user-42")
        payload = decode_refresh_token(token)
        assert payload["sub"] == "user-42"

    def test_refresh_token_contains_type_claim(self):
        """Refresh token should have 'type': 'refresh' to distinguish from access tokens."""
        token = create_refresh_token("user-1")
        payload = decode_refresh_token(token)
        assert payload["type"] == "refresh"

    def test_decode_refresh_token_valid(self):
        """decode_refresh_token(valid_token) should return payload."""
        token = create_refresh_token("user-1")
        payload = decode_refresh_token(token)
        assert payload["sub"] == "user-1"
        assert payload["type"] == "refresh"

    def test_decode_refresh_token_rejects_access_token(self):
        """Passing an access token to decode_refresh_token should raise AuthenticationError."""
        access_token = create_access_token({"sub": "user-1"})
        with pytest.raises(AuthenticationError):
            decode_refresh_token(access_token)

    def test_decode_access_token_rejects_refresh_token(self):
        """Passing a refresh token to decode_access_token should raise AuthenticationError."""
        refresh_token = create_refresh_token("user-1")
        with pytest.raises(AuthenticationError):
            decode_access_token(refresh_token)


# ============================================================================
# TOKEN EDGE CASES (Fix #15)
# ============================================================================

class TestTokenEdgeCases:
    """Additional token security edge cases."""

    def test_tampered_payload_raises(self):
        """Token with modified payload but original signature should raise AuthenticationError."""
        token = create_access_token({"sub": "user-1"})
        # Tamper by modifying the payload part (base64)
        parts = token.split(".")
        parts[1] = parts[1] + "tampered"
        tampered = ".".join(parts)
        with pytest.raises(AuthenticationError):
            decode_access_token(tampered)

    def test_token_signed_with_wrong_secret_raises(self):
        """Token signed with a different secret key should raise AuthenticationError."""
        token = create_access_token({"sub": "user-1"}, secret_key="secret-A")
        with pytest.raises(AuthenticationError):
            decode_access_token(token, secret_key="secret-B")

    def test_token_missing_roles_claim_handled(self):
        """Token without 'roles' claim should default to empty roles list (not crash)."""
        token = create_access_token({"sub": "user-1"})  # no roles in data
        payload = decode_access_token(token)
        assert payload["roles"] == []

    def test_token_missing_team_ids_claim_handled(self):
        """Token without 'team_ids' claim should default to empty list."""
        token = create_access_token({"sub": "user-1"})  # no team_ids in data
        payload = decode_access_token(token)
        assert payload["team_ids"] == []

    def test_token_with_unicode_user_id(self):
        """Token with unicode characters in sub claim should work correctly."""
        token = create_access_token({"sub": "пользователь-1"})
        payload = decode_access_token(token)
        assert payload["sub"] == "пользователь-1"

    def test_token_with_extra_claims_ignored(self):
        """Extra unknown claims in token should be silently ignored."""
        token = create_access_token({"sub": "user-1", "custom_field": "hello"})
        payload = decode_access_token(token)
        assert payload["sub"] == "user-1"
        assert payload.get("custom_field") == "hello"
