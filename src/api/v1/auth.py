"""Authentication endpoints."""

import hashlib
import json
import secrets
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from threading import Lock

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_auth_service, get_current_user, get_db, get_settings
from src.config import Settings
from src.core.exceptions import AuthenticationError
from src.core.rbac import UserContext
from src.core.security import (
    create_2fa_pending_token,
    decode_2fa_pending_token,
    decode_refresh_token,
    hash_password,
)
from src.models.session import UserSession
from src.models.user import User
from src.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    ProfileUpdateRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    TOTPDisableRequest,
    TOTPSetupResponse,
    TOTPVerifySetupRequest,
    TOTPVerifySetupResponse,
    TokenResponse,
    TwoFACompleteRequest,
    UserResponse,
)
from src.services.auth_service import AuthService
from src.services.email_service import EmailService

router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Simple in-memory brute-force protection for /login
# ---------------------------------------------------------------------------
_MAX_FAILURES = 5
_WINDOW_SECS = 900  # 15 minutes lockout window
_login_failures: dict[str, list[float]] = defaultdict(list)
_failures_lock = Lock()


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    with _failures_lock:
        _login_failures[ip] = [t for t in _login_failures[ip] if now - t < _WINDOW_SECS]
        if len(_login_failures[ip]) >= _MAX_FAILURES:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed login attempts. Try again in 15 minutes.",
            )


def _record_failure(ip: str) -> None:
    with _failures_lock:
        _login_failures[ip].append(time.time())


def _clear_failures(ip: str) -> None:
    with _failures_lock:
        _login_failures.pop(ip, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _current_session_id(request: Request) -> str | None:
    """Extract the session ID stored in request state (set during refresh flow)."""
    return getattr(request.state, "session_id", None)


async def _create_session(
    db: AsyncSession,
    user_id: str,
    refresh_token: str,
    request: Request,
    settings: Settings,
) -> UserSession:
    """Persist a new UserSession for the given refresh token."""
    session = UserSession(
        user_id=user_id,
        refresh_token_hash=_token_hash(refresh_token),
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


def _build_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        is_active=user.is_active,
        roles=[r.name for r in user.roles],
        teams=[m.team_id for m in user.team_memberships],
        created_at=user.created_at,
        display_name=getattr(user, "display_name", None),
        bio=getattr(user, "bio", None),
        company_id=getattr(user, "company_id", None),
        is_super_admin=getattr(user, "is_super_admin", False),
    )


# ---------------------------------------------------------------------------
# FEATURE 4 helper — validate & consume an invite token
# ---------------------------------------------------------------------------

async def _resolve_invite(token: str, email: str, db: AsyncSession):
    """Return the Invite if valid; raise HTTPException otherwise."""
    from src.models.invite import Invite

    result = await db.execute(select(Invite).where(Invite.token == token))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invite token")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invite already used")
    if invite.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite token has expired")
    if invite.email.lower() != email.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite token does not match the provided email address",
        )
    return invite


# ===========================================================================
# Registration
# ===========================================================================

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    auth_svc: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    invite_only: bool = getattr(settings, "INVITE_ONLY", False)

    invite = None
    if invite_only:
        if not body.invite_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is invite-only. An invite token is required.",
            )
        invite = await _resolve_invite(body.invite_token, body.email, db)

    try:
        user = await auth_svc.register_user(body.username, body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Apply invite — assign roles and teams
    if invite:
        invite_roles = json.loads(invite.roles)
        invite_team_ids = json.loads(invite.team_ids)

        for role_name in invite_roles:
            role = await auth_svc._user_repo.get_role_by_name(role_name)
            if role and role not in user.roles:
                await auth_svc._user_repo.assign_role(user.id, role.id)

        if invite_team_ids:
            from src.models.team import TeamMembership
            for team_id in invite_team_ids:
                tm = TeamMembership(user_id=user.id, team_id=team_id)
                db.add(tm)

        invite.accepted_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(user)

    # Send welcome email (fire and forget)
    if invite:
        email_svc = EmailService()
        try:
            await email_svc.send_welcome(user.email, user.username)
        except Exception:
            pass

    return _build_user_response(user)


# ===========================================================================
# LDAP login
# ===========================================================================

class LDAPLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/ldap/login", summary="Authenticate via LDAP / Active Directory")
async def ldap_login(
    request: Request,
    body: LDAPLoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Authenticate with an LDAP/AD server.  Requires LDAP_ENABLED=true."""
    from src.services.ldap_auth_service import get_ldap_auth_service
    from src.repositories.user_repository import UserRepository
    from src.services.auth_service import AuthService

    ldap_svc = get_ldap_auth_service()
    if ldap_svc is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="LDAP authentication is not enabled on this server.",
        )

    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    user_repo = UserRepository(db)
    try:
        user = await ldap_svc.authenticate(
            username=body.username,
            password=body.password,
            user_repo=user_repo,
            company_id=None,
        )
    except AuthenticationError as e:
        _record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    _clear_failures(client_ip)

    auth_svc = AuthService(user_repo, settings)
    tokens = auth_svc.create_tokens(user)
    await _create_session(db, user.id, tokens["refresh_token"], request, settings)
    await db.commit()
    return TokenResponse(**tokens)


# ===========================================================================
# Login
# ===========================================================================

@router.post("/login")
async def login(
    request: Request,
    body: LoginRequest,
    auth_svc: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    try:
        user = await auth_svc.authenticate_user(body.username_or_email, body.password)
    except AuthenticationError as e:
        _record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    _clear_failures(client_ip)

    # If 2FA is enabled, return a short-lived temp token instead of real tokens
    if getattr(user, "totp_enabled", False):
        temp_token = create_2fa_pending_token(
            user_id=user.id,
            secret_key=settings.APP_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        return LoginResponse(requires_2fa=True, temp_token=temp_token)

    tokens = auth_svc.create_tokens(user)
    # Create session
    session = await _create_session(db, user.id, tokens["refresh_token"], request, settings)
    await db.commit()

    return TokenResponse(**tokens)


# ===========================================================================
# Refresh
# ===========================================================================

@router.post("/refresh", response_model=dict)
async def refresh_token(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    auth_svc: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
):
    # Validate the refresh token
    try:
        payload = decode_refresh_token(
            body.refresh_token,
            secret_key=settings.APP_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user_id = payload["sub"]

    # Look up and validate the session
    token_hash = _token_hash(body.refresh_token)
    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user_id,
            UserSession.refresh_token_hash == token_hash,
            UserSession.is_revoked == False,  # noqa: E712
        )
    )
    db_session = result.scalar_one_or_none()
    if not db_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session not found or has been revoked",
        )
    if db_session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    user = await auth_svc.get_user_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or deactivated"
        )

    # Issue new access token only
    new_tokens = auth_svc.create_tokens(user)
    db_session.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return {"access_token": new_tokens["access_token"]}


# ===========================================================================
# Me / Profile
# ===========================================================================

@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: UserContext = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service),
):
    user = await auth_svc.get_user_by_id(current_user.user_id)
    return _build_user_response(user)


@router.patch("/profile", response_model=UserResponse)
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: UserContext = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
):
    user = await auth_svc.get_user_by_id(current_user.user_id)
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or None
    if body.bio is not None:
        user.bio = body.bio.strip() or None
    await db.commit()
    await db.refresh(user)
    return _build_user_response(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: UserContext = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
):
    try:
        await auth_svc.change_password(current_user.user_id, body.current_password, body.new_password)
        await db.commit()
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ===========================================================================
# FEATURE 2: Password Reset
# ===========================================================================

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(
    body: ForgotPasswordRequest,
    auth_svc: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
):
    """Always returns 200 — does not reveal whether the email exists."""
    generic_response = {"message": "If that email exists, a reset link has been sent"}

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        return generic_response

    reset_token = secrets.token_hex(32)
    user.password_reset_token = reset_token
    user.password_reset_expires = datetime.now(timezone.utc) + timedelta(hours=1)
    await db.commit()

    email_svc = EmailService()
    try:
        await email_svc.send_password_reset(user.email, reset_token, user.username)
    except Exception:
        pass  # Don't expose SMTP errors to the caller

    return generic_response


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )

    result = await db.execute(
        select(User).where(User.password_reset_token == body.token)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired reset token"
        )
    if user.password_reset_expires is None or user.password_reset_expires < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Reset token has expired"
        )

    user.hashed_password = hash_password(body.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    await db.commit()

    return {"message": "Password reset successful"}


# ===========================================================================
# Email Verification
# ===========================================================================

class VerifyEmailRequest(BaseModel):
    token: str

class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(
    body: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify email with token sent on registration."""
    result = await db.execute(
        select(User).where(User.email_verification_token == body.token)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired verification token",
        )
    user.email_verified = True
    user.email_verification_token = None
    await db.commit()
    return {"message": "Email verified successfully"}


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
async def resend_verification(
    body: ResendVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resend email verification link. Always returns 200."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user and not getattr(user, "email_verified", True) and user.is_active:
        verify_token = secrets.token_hex(32)
        user.email_verification_token = verify_token
        await db.commit()
        email_svc = EmailService()
        try:
            await email_svc.send_verification_email(user.email, user.username, verify_token)
        except Exception:
            pass
    return {"message": "If that email exists and is unverified, a new link has been sent"}


# ===========================================================================
# FEATURE 3: TOTP Two-Factor Authentication
# ===========================================================================

def _hash_backup_code(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _generate_backup_codes() -> tuple[list[str], list[str]]:
    """Generate 8 random alphanumeric backup codes.

    Returns (plain_codes, hashed_codes).
    """
    plain: list[str] = []
    hashed: list[str] = []
    charset = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    for _ in range(8):
        code = "".join(secrets.choice(charset) for _ in range(8))
        plain.append(code)
        hashed.append(_hash_backup_code(code))
    return plain, hashed


@router.post("/2fa/setup", response_model=TOTPSetupResponse)
async def totp_setup(
    current_user: UserContext = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
):
    user = await auth_svc.get_user_by_id(current_user.user_id)

    secret = pyotp.random_base32()
    user.totp_secret = secret
    # totp_enabled stays False until verify-setup succeeds
    await db.commit()

    totp = pyotp.TOTP(secret)
    otpauth_url = totp.provisioning_uri(name=user.email, issuer_name="Nexus")

    return TOTPSetupResponse(
        secret=secret,
        otpauth_url=otpauth_url,
        qr_data=otpauth_url,  # Frontend can render this as a QR code
    )


@router.post("/2fa/verify-setup", response_model=TOTPVerifySetupResponse)
async def totp_verify_setup(
    body: TOTPVerifySetupRequest,
    current_user: UserContext = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
):
    user = await auth_svc.get_user_by_id(current_user.user_id)

    if not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="2FA setup not initiated. Call /2fa/setup first.",
        )

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(body.code, valid_window=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code"
        )

    plain_codes, hashed_codes = _generate_backup_codes()
    user.totp_enabled = True
    user.totp_backup_codes = json.dumps(hashed_codes)
    await db.commit()

    return TOTPVerifySetupResponse(backup_codes=plain_codes)


@router.post("/2fa/disable", status_code=status.HTTP_200_OK)
async def totp_disable(
    body: TOTPDisableRequest,
    current_user: UserContext = Depends(get_current_user),
    auth_svc: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
):
    user = await auth_svc.get_user_by_id(current_user.user_id)

    if not user.totp_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="2FA is not enabled"
        )

    verified = False

    if body.code and user.totp_secret:
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(body.code, valid_window=1):
            verified = True

    if not verified and body.backup_code:
        backup_codes: list[str] = json.loads(user.totp_backup_codes or "[]")
        hashed = _hash_backup_code(body.backup_code.upper())
        if hashed in backup_codes:
            verified = True

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid TOTP code or backup code",
        )

    user.totp_secret = None
    user.totp_enabled = False
    user.totp_backup_codes = None
    await db.commit()

    return {"message": "Two-factor authentication has been disabled"}


@router.post("/2fa/complete", response_model=TokenResponse)
async def totp_complete(
    request: Request,
    body: TwoFACompleteRequest,
    db: AsyncSession = Depends(get_db),
    auth_svc: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
):
    try:
        payload = decode_2fa_pending_token(
            body.temp_token,
            secret_key=settings.APP_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
    except AuthenticationError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user_id = payload["sub"]
    user = await auth_svc.get_user_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    verified = False
    backup_used: str | None = None

    if body.code and user.totp_secret:
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(body.code, valid_window=1):
            verified = True

    if not verified and body.backup_code:
        backup_codes: list[str] = json.loads(user.totp_backup_codes or "[]")
        hashed = _hash_backup_code(body.backup_code.upper())
        if hashed in backup_codes:
            verified = True
            backup_used = hashed

    if not verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid TOTP code or backup code",
        )

    # Remove used backup code
    if backup_used is not None:
        backup_codes_list: list[str] = json.loads(user.totp_backup_codes or "[]")
        backup_codes_list = [c for c in backup_codes_list if c != backup_used]
        user.totp_backup_codes = json.dumps(backup_codes_list)

    tokens = auth_svc.create_tokens(user)
    await _create_session(db, user.id, tokens["refresh_token"], request, settings)
    await db.commit()

    return TokenResponse(**tokens)


# ===========================================================================
# FEATURE 5: Session Management
# ===========================================================================

@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the current session (identified by the Authorization token's session)."""
    # We match by the token presented — extract from header directly
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()

    # For logout we identify the session by matching user_id + looking for a
    # non-revoked session. Since we track refresh tokens, we accept an
    # optional X-Refresh-Token header to pinpoint the exact session.
    refresh_token = request.headers.get("X-Refresh-Token")
    if refresh_token:
        token_hash = _token_hash(refresh_token)
        result = await db.execute(
            select(UserSession).where(
                UserSession.user_id == current_user.user_id,
                UserSession.refresh_token_hash == token_hash,
                UserSession.is_revoked == False,  # noqa: E712
            )
        )
        session = result.scalar_one_or_none()
        if session:
            session.is_revoked = True
            await db.commit()
    else:
        # Revoke the most-recently-used active session for this user
        result = await db.execute(
            select(UserSession)
            .where(
                UserSession.user_id == current_user.user_id,
                UserSession.is_revoked == False,  # noqa: E712
            )
            .order_by(UserSession.last_used_at.desc())
            .limit(1)
        )
        session = result.scalar_one_or_none()
        if session:
            session.is_revoked = True
            await db.commit()

    return {"message": "Logged out successfully"}


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions(
    request: Request,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == current_user.user_id,
            UserSession.is_revoked == False,  # noqa: E712
            UserSession.expires_at > datetime.now(timezone.utc),
        )
    )
    sessions = result.scalars().all()

    # Determine which session is "current" via X-Refresh-Token header
    current_hash: str | None = None
    refresh_token = request.headers.get("X-Refresh-Token")
    if refresh_token:
        current_hash = _token_hash(refresh_token)

    return [
        SessionResponse(
            id=s.id,
            user_agent=s.user_agent,
            ip_address=s.ip_address,
            created_at=s.created_at,
            last_used_at=s.last_used_at,
            is_current=(current_hash is not None and s.refresh_token_hash == current_hash),
        )
        for s in sessions
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_200_OK)
async def revoke_session(
    session_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == current_user.user_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    session.is_revoked = True
    await db.commit()
    return {"message": "Session revoked"}


@router.delete("/sessions", status_code=status.HTTP_200_OK)
async def revoke_all_other_sessions(
    request: Request,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke all sessions for this user except the current one."""
    current_hash: str | None = None
    refresh_token = request.headers.get("X-Refresh-Token")
    if refresh_token:
        current_hash = _token_hash(refresh_token)

    result = await db.execute(
        select(UserSession).where(
            UserSession.user_id == current_user.user_id,
            UserSession.is_revoked == False,  # noqa: E712
        )
    )
    sessions = result.scalars().all()
    revoked = 0
    for s in sessions:
        if current_hash and s.refresh_token_hash == current_hash:
            continue  # keep current session
        s.is_revoked = True
        revoked += 1

    await db.commit()
    return {"message": f"Revoked {revoked} session(s)"}
