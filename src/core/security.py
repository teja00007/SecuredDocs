"""JWT token management and password hashing."""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from src.core.exceptions import AuthenticationError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Defaults — overridden by Settings in production
_DEFAULT_SECRET_KEY = "dev-secret-key-change-me"
_DEFAULT_ALGORITHM = "HS256"
_DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES = 30
_DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS = 7


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with bcrypt. Raises ValueError if password is empty."""
    if not password:
        raise ValueError("Password cannot be empty")
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its bcrypt hash."""
    if not plain_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT Access Token
# ---------------------------------------------------------------------------

def create_access_token(
    data: dict,
    secret_key: str = _DEFAULT_SECRET_KEY,
    algorithm: str = _DEFAULT_ALGORITHM,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token with user_id, roles, and team_ids."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=_DEFAULT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def decode_access_token(
    token: str,
    secret_key: str = _DEFAULT_SECRET_KEY,
    algorithm: str = _DEFAULT_ALGORITHM,
) -> dict:
    """Decode and validate a JWT access token. Returns payload dict.

    Raises AuthenticationError on expired, invalid, or malformed tokens.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError as e:
        raise AuthenticationError(f"Invalid access token: {e}")

    if "sub" not in payload:
        raise AuthenticationError("Token missing 'sub' claim")

    if payload.get("type") != "access":
        raise AuthenticationError("Token is not an access token")

    # Default missing optional claims
    payload.setdefault("roles", [])
    payload.setdefault("team_ids", [])
    return payload


# ---------------------------------------------------------------------------
# JWT Refresh Token
# ---------------------------------------------------------------------------

def create_refresh_token(
    user_id: str,
    secret_key: str = _DEFAULT_SECRET_KEY,
    algorithm: str = _DEFAULT_ALGORITHM,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT refresh token (longer-lived, contains only user_id)."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=_DEFAULT_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode = {"sub": user_id, "exp": expire, "type": "refresh"}
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def decode_refresh_token(
    token: str,
    secret_key: str = _DEFAULT_SECRET_KEY,
    algorithm: str = _DEFAULT_ALGORITHM,
) -> dict:
    """Decode and validate a JWT refresh token. Returns payload dict.

    Raises AuthenticationError if the token is an access token,
    expired, or invalid.
    """
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError as e:
        raise AuthenticationError(f"Invalid refresh token: {e}")

    if "sub" not in payload:
        raise AuthenticationError("Token missing 'sub' claim")

    if payload.get("type") != "refresh":
        raise AuthenticationError("Token is not a refresh token")

    return payload


# ---------------------------------------------------------------------------
# 2FA pending token (short-lived, used only for /auth/2fa/complete)
# ---------------------------------------------------------------------------

_DEFAULT_2FA_PENDING_EXPIRE_MINUTES = 5


def create_2fa_pending_token(
    user_id: str,
    secret_key: str = _DEFAULT_SECRET_KEY,
    algorithm: str = _DEFAULT_ALGORITHM,
) -> str:
    """Create a short-lived JWT that signals 2FA is required."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=_DEFAULT_2FA_PENDING_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire, "type": "2fa_pending"}
    return jwt.encode(payload, secret_key, algorithm=algorithm)


def decode_2fa_pending_token(
    token: str,
    secret_key: str = _DEFAULT_SECRET_KEY,
    algorithm: str = _DEFAULT_ALGORITHM,
) -> dict:
    """Decode and validate a 2FA-pending token."""
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    except JWTError as e:
        raise AuthenticationError(f"Invalid 2FA token: {e}")

    if "sub" not in payload:
        raise AuthenticationError("Token missing 'sub' claim")

    if payload.get("type") != "2fa_pending":
        raise AuthenticationError("Token is not a 2FA pending token")

    return payload
