"""SAML 2.0 Service Provider endpoints.

Uses the python3-saml library (package name: python3-saml>=1.15.0).
Falls back to a simplified implementation if the library is not installed.

===========================================================================
INTEGRATION NOTES (do not edit src/api/v1/__init__.py or src/main.py here)
===========================================================================

1.  Add to src/api/v1/__init__.py:

        from src.api.v1.saml import router as saml_router
        v1_router.include_router(saml_router)

2.  Add to _add_missing_columns() in src/main.py (if not already added by
    oauth.py instructions — these two share the same columns):

        {"table": "users", "column": "oauth_provider",    "type": "VARCHAR(32)"},
        {"table": "users", "column": "oauth_provider_id", "type": "VARCHAR(256)"},

3.  Install the dependency:

        pip install python3-saml>=1.15.0
        # OR as an alternative:
        pip install pysaml2>=7.5.0

    The system also needs xmlsec1 installed:
        macOS:   brew install libxmlsec1
        Debian:  apt-get install xmlsec1 libxmlsec1-dev

===========================================================================
"""

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_db, get_settings
from src.config import Settings
from src.core.security import hash_password
from src.models.user import User
from src.repositories.user_repository import UserRepository
from src.services.auth_service import AuthService

router = APIRouter(prefix="/saml", tags=["saml-sso"])

# ---------------------------------------------------------------------------
# Detect library availability
# ---------------------------------------------------------------------------

try:
    from onelogin.saml2.auth import OneLogin_Saml2_Auth
    from onelogin.saml2.settings import OneLogin_Saml2_Settings
    from onelogin.saml2.utils import OneLogin_Saml2_Utils
    _SAML_LIB = "python3-saml"
except ImportError:
    try:
        import saml2  # pysaml2
        _SAML_LIB = "pysaml2"
    except ImportError:
        _SAML_LIB = None


# ---------------------------------------------------------------------------
# Helpers — SP settings dict for python3-saml
# ---------------------------------------------------------------------------

def _sp_settings(settings: Settings) -> dict:
    """Build the python3-saml settings dict from app config."""
    entity_id = settings.SAML_SP_ENTITY_ID or f"{settings.APP_URL}/api/v1/saml/metadata"
    acs_url = settings.SAML_SP_ACS_URL or f"{settings.APP_URL}/api/v1/saml/acs"

    return {
        "strict": True,
        "debug": settings.APP_ENV == "development",
        "sp": {
            "entityId": entity_id,
            "assertionConsumerService": {
                "url": acs_url,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "x509cert": "",
            "privateKey": "",
        },
        "idp": {
            # These will be filled from IdP metadata at runtime.
            # Populated lazily in _get_idp_metadata().
            "entityId": "",
            "singleSignOnService": {
                "url": "",
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "x509cert": "",
        },
        "security": {
            "authnRequestsSigned": False,
            "wantAssertionsSigned": True,
            "wantMessagesSigned": False,
            "wantNameId": True,
            "requestedAuthnContext": False,
        },
    }


async def _fetch_idp_metadata(metadata_url: str) -> dict:
    """Fetch and parse IdP metadata XML, return dict with entityId, sso_url, cert."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        resp = await client.get(metadata_url)
        resp.raise_for_status()
        xml_text = resp.text

    if _SAML_LIB == "python3-saml":
        from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
        parsed = OneLogin_Saml2_IdPMetadataParser.parse(xml_text)
        return parsed.get("idp", {})

    # Fallback: minimal XML parse using stdlib
    import xml.etree.ElementTree as ET
    ns = {
        "md": "urn:oasis:names:tc:SAML:2.0:metadata",
        "ds": "http://www.w3.org/2000/09/xmldsig#",
    }
    root = ET.fromstring(xml_text)
    entity_id = root.get("entityID", "")
    sso_url = ""
    sso_el = root.find(".//md:SingleSignOnService[@Binding='urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect']", ns)
    if sso_el is not None:
        sso_url = sso_el.get("Location", "")
    cert_el = root.find(".//ds:X509Certificate", ns)
    cert = cert_el.text.strip() if cert_el is not None else ""
    return {"entityId": entity_id, "singleSignOnService": {"url": sso_url}, "x509cert": cert}


async def _build_saml_auth(request: Request, settings: Settings) -> Any:
    """Build a python3-saml Auth object for the current request."""
    if _SAML_LIB != "python3-saml":
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="python3-saml library is not installed. Run: pip install python3-saml",
        )

    sp_cfg = _sp_settings(settings)

    if settings.SAML_IDP_METADATA_URL:
        try:
            idp_info = await _fetch_idp_metadata(settings.SAML_IDP_METADATA_URL)
            sp_cfg["idp"].update(idp_info)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not fetch IdP metadata: {exc}",
            )

    # Build the request dict that python3-saml expects
    body = await request.body()
    form = await request.form() if request.method == "POST" else {}
    saml_request_data = {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": request.headers.get("host", "localhost"),
        "script_name": request.url.path,
        "server_port": str(request.url.port or (443 if request.url.scheme == "https" else 80)),
        "get_data": dict(request.query_params),
        "post_data": dict(form),
        "query_string": str(request.url.query),
    }

    auth = OneLogin_Saml2_Auth(saml_request_data, sp_cfg)
    return auth


# ---------------------------------------------------------------------------
# Shared user login/create helper (same as oauth.py)
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
    result = await db.execute(select(User).where(User.email == email))
    user: User | None = result.scalar_one_or_none()

    if user is None:
        invite_only: bool = getattr(settings, "INVITE_ONLY", False)
        if invite_only:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registration is invite-only. Ask your admin for an invite.",
            )

        username = email.split("@")[0]
        check = await db.execute(select(User).where(User.username == username))
        if check.scalar_one_or_none():
            username = f"{username}_{secrets.token_urlsafe(4)}"

        user = User(
            id=str(uuid.uuid4()),
            username=username,
            email=email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            is_active=True,
            display_name=display_name or None,
            oauth_provider=provider,
            oauth_provider_id=provider_id,
        )
        db.add(user)

        user_repo = UserRepository(db)
        await db.flush()
        await db.refresh(user)

        viewer_role = await user_repo.get_role_by_name("viewer")
        if viewer_role:
            await user_repo.assign_role(user.id, viewer_role.id)

        await db.commit()
        await db.refresh(user)
    else:
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
# SP Metadata — GET /api/v1/saml/metadata
# ---------------------------------------------------------------------------

@router.get("/metadata", summary="SAML SP metadata XML")
async def saml_metadata(
    settings: Settings = Depends(get_settings),
):
    if not settings.SAML_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="SAML SSO is not enabled. Set SAML_ENABLED=true in your configuration.",
        )

    entity_id = settings.SAML_SP_ENTITY_ID or f"{settings.APP_URL}/api/v1/saml/metadata"
    acs_url = settings.SAML_SP_ACS_URL or f"{settings.APP_URL}/api/v1/saml/acs"

    if _SAML_LIB == "python3-saml":
        sp_cfg = _sp_settings(settings)
        saml_settings = OneLogin_Saml2_Settings(settings=sp_cfg, sp_validation_only=True)
        metadata = saml_settings.get_sp_metadata()
        errors = saml_settings.validate_metadata(metadata)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"SP metadata validation errors: {errors}",
            )
        return Response(content=metadata, media_type="application/xml")

    # Fallback: hand-crafted SP metadata XML
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<md:EntityDescriptor
    xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
    xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
    entityID="{entity_id}"
    validUntil="2099-01-01T00:00:00Z">
  <md:SPSSODescriptor
      AuthnRequestsSigned="false"
      WantAssertionsSigned="true"
      protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:NameIDFormat>
      urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress
    </md:NameIDFormat>
    <md:AssertionConsumerService
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
        Location="{acs_url}"
        index="1"/>
  </md:SPSSODescriptor>
</md:EntityDescriptor>"""
    return Response(content=xml.strip(), media_type="application/xml")


# ---------------------------------------------------------------------------
# SAML Login — GET /api/v1/saml/login
# ---------------------------------------------------------------------------

@router.get("/login", summary="Initiate SAML SSO login")
async def saml_login(
    request: Request,
    settings: Settings = Depends(get_settings),
):
    if not settings.SAML_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="SAML SSO is not enabled.",
        )

    if _SAML_LIB == "python3-saml":
        auth = await _build_saml_auth(request, settings)
        sso_url = auth.login()
        return RedirectResponse(url=sso_url, status_code=status.HTTP_302_FOUND)

    # Fallback: generate AuthnRequest manually and redirect
    if not settings.SAML_IDP_METADATA_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SAML_IDP_METADATA_URL is not configured.",
        )

    try:
        idp_info = await _fetch_idp_metadata(settings.SAML_IDP_METADATA_URL)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not fetch IdP metadata: {exc}",
        )

    sso_url = idp_info.get("singleSignOnService", {}).get("url", "")
    if not sso_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not determine IdP SSO URL from metadata.",
        )

    entity_id = settings.SAML_SP_ENTITY_ID or f"{settings.APP_URL}/api/v1/saml/metadata"
    acs_url = settings.SAML_SP_ACS_URL or f"{settings.APP_URL}/api/v1/saml/acs"
    request_id = f"_{secrets.token_hex(16)}"
    issue_instant = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    authn_request = (
        f'<samlp:AuthnRequest'
        f' xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol"'
        f' xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion"'
        f' ID="{request_id}"'
        f' Version="2.0"'
        f' IssueInstant="{issue_instant}"'
        f' Destination="{sso_url}"'
        f' AssertionConsumerServiceURL="{acs_url}"'
        f' ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f'<saml:Issuer>{entity_id}</saml:Issuer>'
        f'<samlp:NameIDPolicy'
        f' Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"'
        f' AllowCreate="true"/>'
        f'</samlp:AuthnRequest>'
    )

    import base64
    import zlib
    from urllib.parse import quote as url_quote

    compressed = zlib.compress(authn_request.encode("utf-8"))[2:-4]  # raw deflate
    encoded = base64.b64encode(compressed).decode("ascii")
    redirect_url = f"{sso_url}?SAMLRequest={url_quote(encoded)}"
    return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# ACS — POST /api/v1/saml/acs  (IdP posts the SAML Response here)
# ---------------------------------------------------------------------------

@router.post("/acs", summary="SAML Assertion Consumer Service")
async def saml_acs(
    request: Request,
    SAMLResponse: str = Form(...),
    RelayState: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.SAML_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="SAML SSO is not enabled.",
        )

    if _SAML_LIB == "python3-saml":
        auth = await _build_saml_auth(request, settings)
        auth.process_response()
        errors = auth.get_errors()

        if errors:
            reason = auth.get_last_error_reason()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SAML authentication failed: {errors}. Reason: {reason}",
            )

        if not auth.is_authenticated():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SAML authentication was not successful",
            )

        attributes = auth.get_attributes()
        name_id = auth.get_nameid()

        # Try to extract email from attributes first, fall back to NameID
        email = None
        for attr_key in (
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "urn:oid:0.9.2342.19200300.100.1.3",  # mail OID
            "email",
            "mail",
        ):
            vals = attributes.get(attr_key, [])
            if vals:
                email = vals[0]
                break
        if not email:
            email = name_id

        # Display name
        display_name = ""
        for attr_key in (
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
            "urn:oid:2.5.4.3",  # cn OID
            "displayName",
            "cn",
        ):
            vals = attributes.get(attr_key, [])
            if vals:
                display_name = vals[0]
                break

        provider_id = name_id or email or ""

    else:
        # Fallback: decode the SAML Response and do minimal XML parsing
        # NOTE: This fallback does NOT verify the signature — for production,
        # install python3-saml for proper signature verification.
        import base64
        import xml.etree.ElementTree as ET

        try:
            decoded = base64.b64decode(SAMLResponse).decode("utf-8")
            root = ET.fromstring(decoded)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not decode SAML Response: {exc}",
            )

        ns = {
            "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
            "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
        }

        # Check status
        status_code_el = root.find(".//samlp:StatusCode", ns)
        if status_code_el is not None:
            status_value = status_code_el.get("Value", "")
            if "Success" not in status_value:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"SAML authentication failed with status: {status_value}",
                )

        # Extract NameID
        name_id_el = root.find(".//saml:NameID", ns)
        name_id = name_id_el.text.strip() if name_id_el is not None else ""

        # Extract email attribute
        email = None
        for attr_el in root.findall(".//saml:Attribute", ns):
            attr_name = attr_el.get("Name", "")
            if "email" in attr_name.lower() or "mail" in attr_name.lower():
                val_el = attr_el.find("saml:AttributeValue", ns)
                if val_el is not None and val_el.text:
                    email = val_el.text.strip()
                    break
        if not email:
            email = name_id

        # Extract display name
        display_name = ""
        for attr_el in root.findall(".//saml:Attribute", ns):
            attr_name = attr_el.get("Name", "")
            if "name" in attr_name.lower() or "displayname" in attr_name.lower():
                val_el = attr_el.find("saml:AttributeValue", ns)
                if val_el is not None and val_el.text:
                    display_name = val_el.text.strip()
                    break

        provider_id = name_id or email or ""

    if not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SAML assertion did not contain a usable email address",
        )

    tokens = await _login_or_create_user(
        email=email,
        display_name=display_name,
        provider="saml",
        provider_id=provider_id,
        db=db,
        settings=settings,
    )

    frontend_url = (
        f"{settings.APP_URL}/auth/callback"
        f"?access_token={tokens['access_token']}"
        f"&refresh_token={tokens['refresh_token']}"
    )
    return RedirectResponse(url=frontend_url, status_code=status.HTTP_302_FOUND)
