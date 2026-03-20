"""OAuth2 SSO endpoints — Google and Microsoft Authorization Code flow.

===========================================================================
INTEGRATION NOTES (do not edit src/api/v1/__init__.py or src/main.py here)
===========================================================================

1.  Add to src/api/v1/__init__.py:

        from src.api.v1.oauth import router as oauth_router
        v1_router.include_router(oauth_router)

2.  Add to _add_missing_columns() in src/main.py (inside the existing helper
    that patches the "users" table at startup):

        # OAuth SSO columns
        {"table": "users", "column": "oauth_provider",    "type": "VARCHAR(32)"},
        {"table": "users", "column": "oauth_provider_id", "type": "VARCHAR(256)"},

===========================================================================
"""

import secrets
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_db, get_settings
from src.config import Settings
from src.core.security import hash_password
from src.models.admin_settings import AdminSetting
from src.models.user import User
from src.repositories.user_repository import UserRepository
from src.services.auth_service import AuthService

router = APIRouter(prefix="/auth/oauth", tags=["oauth-sso"])

# ---------------------------------------------------------------------------
# CSRF state token helpers
# ---------------------------------------------------------------------------

_STATE_MAX_AGE_SECONDS = 300  # 5 minutes


def _get_signer(settings: Settings) -> URLSafeTimedSerializer:
    secret = settings.OAUTH_STATE_SECRET or settings.APP_SECRET_KEY
    return URLSafeTimedSerializer(secret, salt="oauth-state")


def _create_state(settings: Settings) -> str:
    """Create a signed, time-limited state token."""
    nonce = secrets.token_urlsafe(32)
    signer = _get_signer(settings)
    return signer.dumps(nonce)


def _verify_state(state: str, settings: Settings) -> bool:
    """Verify that the state token is valid and was issued recently."""
    signer = _get_signer(settings)
    try:
        signer.loads(state, max_age=_STATE_MAX_AGE_SECONDS)
        return True
    except (BadSignature, SignatureExpired):
        return False


# ---------------------------------------------------------------------------
# Shared user-lookup / creation logic
# ---------------------------------------------------------------------------

async def _login_or_create_user(
    *,
    email: str,
    display_name: str,
    provider: str,
    provider_id: str,
    db: AsyncSession,
    settings: Settings,
) -> dict:
    """Find or create a user for an OAuth login.  Returns token dict."""
    # Look up by email
    result = await db.execute(select(User).where(User.email == email))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        # Registration gate — check invite_only and allowed domains
        invite_only: bool = getattr(settings, "INVITE_ONLY", False)
        if invite_only:
            # Allow if the email domain is in the allowed_signup_domains admin setting
            email_domain = email.split("@")[-1].lower()
            allowed_raw_result = await db.execute(
                select(AdminSetting).where(AdminSetting.key == "allowed_signup_domains")
            )
            allowed_raw = allowed_raw_result.scalar_one_or_none()
            allowed_domains = [
                d.strip().lower() for d in (allowed_raw.value if allowed_raw else "").split(",") if d.strip()
            ]
            if email_domain not in allowed_domains:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Registration is invite-only. Ask your admin for an invite.",
                )

        # Create new user
        username = email.split("@")[0]
        # Ensure username is unique by appending random suffix if needed
        check = await db.execute(select(User).where(User.username == username))
        if check.scalar_one_or_none():
            username = f"{username}_{secrets.token_urlsafe(4)}"

        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),  # random — unusable password
            is_active=True,
            display_name=display_name or None,
            oauth_provider=provider,
            oauth_provider_id=provider_id,
        )
        db.add(user)

        # Assign default "user" / "viewer" role
        user_repo = UserRepository(db)
        await db.flush()  # get user.id
        await db.refresh(user)

        viewer_role = await user_repo.get_role_by_name("viewer")
        if viewer_role:
            await user_repo.assign_role(user.id, viewer_role.id)

        await db.commit()
        await db.refresh(user)
    else:
        # Update provider info if not already set
        if not user.oauth_provider:
            user.oauth_provider = provider
            user.oauth_provider_id = provider_id
            await db.commit()
            await db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact your administrator.",
        )

    user_repo = UserRepository(db)
    auth_svc = AuthService(user_repo=user_repo, settings=settings)
    return auth_svc.create_tokens(user)


# ---------------------------------------------------------------------------
# Google OAuth2
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


@router.get("/google", summary="Initiate Google OAuth2 login")
async def google_login(
    settings: Settings = Depends(get_settings),
):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth not configured",
        )

    state = _create_state(settings)
    redirect_uri = f"{settings.OAUTH_REDIRECT_BASE}/api/v1/auth/oauth/google/callback"

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    # Store state in a short-lived cookie so the callback can verify it
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=_STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=not settings.APP_ENV == "development",
    )
    return response


@router.get("/google/callback", summary="Google OAuth2 callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error from Google: {error}",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter",
        )

    # Verify state — prefer cookie, fall back to query param comparison
    cookie_state = request.cookies.get("oauth_state")
    state_to_verify = cookie_state or state
    if not _verify_state(state_to_verify, settings) or (cookie_state and cookie_state != state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state. Please try logging in again.",
        )

    redirect_uri = f"{settings.OAUTH_REDIRECT_BASE}/api/v1/auth/oauth/google/callback"

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Google token exchange failed: {token_resp.text}",
            )
        token_data = token_resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Google did not return an access token",
            )

        # Fetch user info
        userinfo_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch user info from Google",
            )
        userinfo = userinfo_resp.json()

    email: str | None = userinfo.get("email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google did not return an email address",
        )

    name: str = userinfo.get("name", "")
    sub: str = userinfo.get("sub", "")

    tokens = await _login_or_create_user(
        email=email,
        display_name=name,
        provider="google",
        provider_id=sub,
        db=db,
        settings=settings,
    )

    frontend_url = (
        f"{settings.APP_URL}/auth/callback"
        f"?access_token={tokens['access_token']}"
        f"&refresh_token={tokens['refresh_token']}"
    )
    redirect_resp = RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)
    # Clear the state cookie
    redirect_resp.delete_cookie("oauth_state")
    return redirect_resp


# ---------------------------------------------------------------------------
# Microsoft OAuth2
# ---------------------------------------------------------------------------

MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"


@router.get("/microsoft", summary="Initiate Microsoft OAuth2 login")
async def microsoft_login(
    settings: Settings = Depends(get_settings),
):
    if not settings.MICROSOFT_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Microsoft OAuth not configured",
        )

    state = _create_state(settings)
    redirect_uri = f"{settings.OAUTH_REDIRECT_BASE}/api/v1/auth/oauth/microsoft/callback"

    params = {
        "client_id": settings.MICROSOFT_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile User.Read",
        "state": state,
        "response_mode": "query",
    }
    url = f"{MICROSOFT_AUTH_URL}?{urlencode(params)}"
    response = RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=_STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=not settings.APP_ENV == "development",
    )
    return response


@router.get("/microsoft/callback", summary="Microsoft OAuth2 callback")
async def microsoft_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error from Microsoft: {error_description or error}",
        )
    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing code or state parameter",
        )

    cookie_state = request.cookies.get("oauth_state")
    state_to_verify = cookie_state or state
    if not _verify_state(state_to_verify, settings) or (cookie_state and cookie_state != state):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired OAuth state. Please try logging in again.",
        )

    redirect_uri = f"{settings.OAUTH_REDIRECT_BASE}/api/v1/auth/oauth/microsoft/callback"

    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(
            MICROSOFT_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.MICROSOFT_CLIENT_ID,
                "client_secret": settings.MICROSOFT_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "scope": "openid email profile User.Read",
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Microsoft token exchange failed: {token_resp.text}",
            )
        token_data = token_resp.json()
        ms_access_token = token_data.get("access_token")
        if not ms_access_token:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Microsoft did not return an access token",
            )

        # Fetch user info from Microsoft Graph
        me_resp = await client.get(
            MICROSOFT_GRAPH_ME_URL,
            headers={"Authorization": f"Bearer {ms_access_token}"},
        )
        if me_resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch user info from Microsoft Graph",
            )
        me_data = me_resp.json()

    # Microsoft uses "mail" for the primary email (may be null for some tenants)
    email: str | None = me_data.get("mail") or me_data.get("userPrincipalName")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Microsoft did not return an email address",
        )

    display_name: str = me_data.get("displayName", "")
    ms_id: str = me_data.get("id", "")

    tokens = await _login_or_create_user(
        email=email,
        display_name=display_name,
        provider="microsoft",
        provider_id=ms_id,
        db=db,
        settings=settings,
    )

    # Azure AD group sync — assign Nexus roles based on AD group membership
    try:
        from src.services.azure_ad_sync import sync_azure_ad_groups, get_group_role_map, is_azure_ad_sync_enabled
        if is_azure_ad_sync_enabled() and ms_access_token:
            user_result = await db.execute(
                select(User).where(User.email == email)
            )
            user_obj = user_result.scalar_one_or_none()
            if user_obj:
                user_repo = UserRepository(db)
                group_role_map = get_group_role_map()
                assigned = await sync_azure_ad_groups(ms_access_token, user_obj, user_repo, group_role_map)
                if assigned:
                    import logging as _logging
                    _logging.getLogger(__name__).info(
                        "Azure AD sync: assigned roles %s to %s", assigned, email
                    )
    except Exception as _e:
        import logging as _logging
        _logging.getLogger(__name__).warning("Azure AD group sync failed (non-fatal): %s", _e)

    frontend_url = (
        f"{settings.APP_URL}/auth/callback"
        f"?access_token={tokens['access_token']}"
        f"&refresh_token={tokens['refresh_token']}"
    )
    redirect_resp = RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)
    redirect_resp.delete_cookie("oauth_state")
    return redirect_resp
