"""Companies (tenants) management — super-admin only."""

import re
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_db, get_current_user
from src.core.rbac import UserContext
from src.models.company import Company
from src.models.user import User

router = APIRouter(prefix="/companies", tags=["companies"])


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def _require_super_admin(current_user: UserContext = Depends(get_current_user)) -> UserContext:
    if not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super-admin access required",
        )
    return current_user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CompanyCreate(BaseModel):
    name: str
    plan: str = "starter"
    billing_cycle: str = "monthly"
    owner_email: EmailStr | None = None
    max_users: int | None = None
    max_storage_gb: int | None = None
    notes: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None
    plan: str | None = None
    billing_cycle: str | None = None
    owner_email: str | None = None
    max_users: int | None = None
    max_storage_gb: int | None = None
    is_active: bool | None = None
    logo_url: str | None = None
    brand_color: str | None = None
    custom_domain: str | None = None
    notes: str | None = None


class CompanyResponse(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    billing_cycle: str
    max_users: int
    max_storage_gb: int
    is_active: bool
    owner_email: str | None
    logo_url: str | None
    brand_color: str | None
    custom_domain: str | None
    notes: str | None
    created_at: datetime
    user_count: int = 0

    model_config = {"from_attributes": True}


_PLAN_DEFAULTS = {
    "free":       {"max_users": 3,   "max_storage_gb": 1},
    "starter":    {"max_users": 10,  "max_storage_gb": 10},
    "team":       {"max_users": 25,  "max_storage_gb": 50},
    "business":   {"max_users": 75,  "max_storage_gb": 200},
    "enterprise": {"max_users": 9999, "max_storage_gb": 9999},
}


def _slug_from_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "org"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[CompanyResponse])
async def list_companies(
    db: AsyncSession = Depends(get_db),
    _: UserContext = Depends(_require_super_admin),
):
    """List all companies (tenants)."""
    result = await db.execute(select(Company).order_by(Company.created_at.desc()))
    companies = result.scalars().all()

    out = []
    for c in companies:
        count_res = await db.execute(
            select(func.count(User.id)).where(User.company_id == c.id, User.is_active == True)  # noqa: E712
        )
        user_count = count_res.scalar_one()
        out.append(CompanyResponse(
            id=c.id, name=c.name, slug=c.slug, plan=c.plan,
            billing_cycle=c.billing_cycle, max_users=c.max_users,
            max_storage_gb=c.max_storage_gb, is_active=c.is_active,
            owner_email=c.owner_email, logo_url=c.logo_url,
            brand_color=c.brand_color, custom_domain=c.custom_domain,
            notes=c.notes, created_at=c.created_at, user_count=user_count,
        ))
    return out


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    body: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    _: UserContext = Depends(_require_super_admin),
):
    """Create a new company (tenant) manually."""
    slug = _slug_from_name(body.name)
    existing = await db.execute(select(Company).where(Company.slug == slug))
    if existing.scalar_one_or_none():
        slug = slug + "-" + secrets.token_hex(3)

    defaults = _PLAN_DEFAULTS.get(body.plan, _PLAN_DEFAULTS["starter"])
    company = Company(
        name=body.name,
        slug=slug,
        plan=body.plan,
        billing_cycle=body.billing_cycle,
        max_users=body.max_users or defaults["max_users"],
        max_storage_gb=body.max_storage_gb or defaults["max_storage_gb"],
        owner_email=body.owner_email,
        notes=body.notes,
        is_active=True,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)

    return CompanyResponse(
        id=company.id, name=company.name, slug=company.slug, plan=company.plan,
        billing_cycle=company.billing_cycle, max_users=company.max_users,
        max_storage_gb=company.max_storage_gb, is_active=company.is_active,
        owner_email=company.owner_email, logo_url=company.logo_url,
        brand_color=company.brand_color, custom_domain=company.custom_domain,
        notes=company.notes, created_at=company.created_at, user_count=0,
    )


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Get company details. Super-admins can get any company; company admins can get their own."""
    if not current_user.is_super_admin and current_user.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    count_res = await db.execute(
        select(func.count(User.id)).where(User.company_id == company_id, User.is_active == True)  # noqa: E712
    )
    user_count = count_res.scalar_one()

    return CompanyResponse(
        id=company.id, name=company.name, slug=company.slug, plan=company.plan,
        billing_cycle=company.billing_cycle, max_users=company.max_users,
        max_storage_gb=company.max_storage_gb, is_active=company.is_active,
        owner_email=company.owner_email, logo_url=company.logo_url,
        brand_color=company.brand_color, custom_domain=company.custom_domain,
        notes=company.notes, created_at=company.created_at, user_count=user_count,
    )


@router.patch("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: str,
    body: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Update company settings. Super-admins can update any; company admins can update branding only."""
    is_super = current_user.is_super_admin
    is_own_admin = "admin" in current_user.roles and current_user.company_id == company_id

    if not is_super and not is_own_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    # Company admins can only update branding fields
    allowed_for_admin = {"logo_url", "brand_color", "notes"}
    updates = body.model_dump(exclude_none=True)

    for field, value in updates.items():
        if not is_super and field not in allowed_for_admin:
            continue  # silently skip privileged fields for company admins
        setattr(company, field, value)

    await db.commit()
    await db.refresh(company)

    count_res = await db.execute(
        select(func.count(User.id)).where(User.company_id == company_id, User.is_active == True)  # noqa: E712
    )
    user_count = count_res.scalar_one()

    return CompanyResponse(
        id=company.id, name=company.name, slug=company.slug, plan=company.plan,
        billing_cycle=company.billing_cycle, max_users=company.max_users,
        max_storage_gb=company.max_storage_gb, is_active=company.is_active,
        owner_email=company.owner_email, logo_url=company.logo_url,
        brand_color=company.brand_color, custom_domain=company.custom_domain,
        notes=company.notes, created_at=company.created_at, user_count=user_count,
    )


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    _: UserContext = Depends(_require_super_admin),
):
    """Deactivate (soft-delete) a company. Super-admin only."""
    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    company.is_active = False
    await db.commit()


@router.get("/{company_id}/users", response_model=list[dict])
async def list_company_users(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """List users in a company. Super-admins or company admins only."""
    is_super = current_user.is_super_admin
    is_own_admin = "admin" in current_user.roles and current_user.company_id == company_id

    if not is_super and not is_own_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    result = await db.execute(
        select(User).where(User.company_id == company_id).order_by(User.username)
    )
    users = result.scalars().all()

    return [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "display_name": u.display_name,
            "is_active": u.is_active,
            "is_super_admin": u.is_super_admin,
            "roles": [r.name for r in u.roles],
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]
