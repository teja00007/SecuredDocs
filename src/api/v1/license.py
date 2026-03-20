"""License management endpoints."""

import json
import secrets
import string
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_db, get_current_user, get_settings, get_auth_service
from src.core.rbac import UserContext
from src.models.company import Company
from src.models.license import License, PLAN_LIMITS
from src.models.user import User, Role
from src.core.security import hash_password
from src.services.email_service import EmailService

router = APIRouter(prefix="/license", tags=["license"])


def _generate_license_key() -> str:
    """Generate SD-XXXX-XXXX-XXXX-XXXX format key."""
    charset = string.ascii_uppercase + string.digits
    parts = ["".join(secrets.choice(charset) for _ in range(4)) for _ in range(4)]
    return "SD-" + "-".join(parts)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ActivateRequest(BaseModel):
    organization: str
    email: EmailStr
    username: str
    password: str
    plan: str
    license_key: str
    billing_cycle: str = "monthly"

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        if v not in PLAN_LIMITS:
            raise ValueError(f"Invalid plan: {v}")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LicenseInfo(BaseModel):
    key: str
    plan: str
    organization: str
    max_users: int
    max_storage_gb: int
    features: list[str]
    is_active: bool
    is_expired: bool
    created_at: datetime
    expires_at: datetime | None
    current_users: int


class LicenseStatusResponse(BaseModel):
    activated: bool
    plan: str | None = None
    organization: str | None = None
    max_users: int | None = None
    max_storage_gb: int | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=LicenseStatusResponse)
async def license_status(db: AsyncSession = Depends(get_db)):
    """Public endpoint — returns whether any license is activated."""
    result = await db.execute(select(License).where(License.is_active == True).limit(1))  # noqa: E712
    lic = result.scalar_one_or_none()
    if not lic:
        return LicenseStatusResponse(activated=False)
    return LicenseStatusResponse(
        activated=True,
        plan=lic.plan,
        organization=lic.organization,
        max_users=lic.max_users,
        max_storage_gb=lic.max_storage_gb,
    )


@router.post("/activate", response_model=dict, status_code=status.HTTP_201_CREATED)
async def activate_license(
    body: ActivateRequest,
    db: AsyncSession = Depends(get_db),
    auth_svc=Depends(get_auth_service),
):
    """
    First-time setup: create admin user + activate license.
    Only works when no license exists yet.
    """
    # Check if already activated
    result = await db.execute(select(License).where(License.is_active == True).limit(1))  # noqa: E712
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="License already activated. Contact admin to manage licenses.",
        )

    # Validate license key format: SD-XXXX-XXXX-XXXX-XXXX = 22 chars
    if not body.license_key.startswith("SD-") or len(body.license_key) != 22:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid license key format.",
        )

    # Check if email already exists
    existing_user = await db.execute(select(User).where(User.email == body.email))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists.",
        )

    plan_limits = PLAN_LIMITS[body.plan]

    # Derive a slug from the organization name
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", body.organization.lower()).strip("-") or "org"
    # Ensure slug uniqueness by appending random suffix if needed
    existing_slug = await db.execute(select(Company).where(Company.slug == slug))
    if existing_slug.scalar_one_or_none():
        slug = slug + "-" + secrets.token_hex(3)

    # Create Company (tenant) record
    company = Company(
        name=body.organization,
        slug=slug,
        license_key=body.license_key,
        plan=body.plan,
        max_users=plan_limits["max_users"],
        max_storage_gb=plan_limits["max_storage_gb"],
        billing_cycle=body.billing_cycle,
        owner_email=body.email,
        is_active=True,
    )
    db.add(company)
    await db.flush()  # get company.id

    # Create license
    lic = License(
        key=body.license_key,
        plan=body.plan,
        organization=body.organization,
        admin_email=body.email,
        max_users=plan_limits["max_users"],
        max_storage_gb=plan_limits["max_storage_gb"],
        features_json=json.dumps(plan_limits["features"]),
        is_active=True,
    )
    db.add(lic)
    await db.flush()

    # Create admin user
    try:
        user = await auth_svc.register_user(body.username, body.email, body.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Link user to the company and mark as company admin
    user.company_id = company.id
    user.is_super_admin = False
    db.add(user)

    # Assign admin role
    admin_role = await auth_svc._user_repo.get_role_by_name("admin")
    if admin_role and admin_role not in user.roles:
        await auth_svc._user_repo.assign_role(user.id, admin_role.id)

    # Set email verification token
    import secrets as _secrets
    verify_token = _secrets.token_hex(32)
    user.email_verification_token = verify_token
    user.email_verified = False

    await db.commit()
    await db.refresh(user)

    # Send verification + welcome email
    email_svc = EmailService()
    try:
        await email_svc.send_license_welcome(
            to_email=body.email,
            username=body.username,
            organization=body.organization,
            plan=body.plan,
            verify_token=verify_token,
        )
    except Exception:
        pass

    return {
        "success": True,
        "message": "License activated. Admin account created. Check your email to verify.",
        "username": user.username,
        "plan": body.plan,
        "organization": body.organization,
    }


@router.get("/info", response_model=LicenseInfo)
async def license_info(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current license info. Requires authentication."""
    result = await db.execute(select(License).where(License.is_active == True).limit(1))  # noqa: E712
    lic = result.scalar_one_or_none()
    if not lic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active license found")

    # Count current users
    count_result = await db.execute(select(func.count(User.id)).where(User.is_active == True))  # noqa: E712
    current_users = count_result.scalar_one()

    return LicenseInfo(
        key=lic.key,
        plan=lic.plan,
        organization=lic.organization,
        max_users=lic.max_users,
        max_storage_gb=lic.max_storage_gb,
        features=lic.features,
        is_active=lic.is_active,
        is_expired=lic.is_expired,
        created_at=lic.created_at,
        expires_at=lic.expires_at,
        current_users=current_users,
    )
