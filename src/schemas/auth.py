"""Authentication and user Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    invite_token: str | None = None  # Required when INVITE_ONLY=True

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class ProfileUpdateRequest(BaseModel):
    display_name: str | None = Field(None, max_length=255)
    bio: str | None = Field(None, max_length=500)


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    is_active: bool
    roles: list[str]
    teams: list[str]
    created_at: datetime
    display_name: str | None = None
    bio: str | None = None
    company_id: str | None = None
    is_super_admin: bool = False

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# TOTP / 2FA
# ---------------------------------------------------------------------------

class TOTPSetupResponse(BaseModel):
    secret: str
    otpauth_url: str
    qr_data: str


class TOTPVerifySetupRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)


class TOTPVerifySetupResponse(BaseModel):
    backup_codes: list[str]


class TOTPDisableRequest(BaseModel):
    code: str | None = None
    backup_code: str | None = None


class TwoFACompleteRequest(BaseModel):
    temp_token: str
    code: str | None = None
    backup_code: str | None = None


class LoginResponse(BaseModel):
    """Returned by /login when 2FA is required."""
    requires_2fa: bool
    temp_token: str


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

class InviteCreateRequest(BaseModel):
    email: EmailStr
    roles: list[str] = ["viewer"]
    team_ids: list[str] = []


class InviteResponse(BaseModel):
    invite_id: str
    token: str
    email: str
    roles: list[str]
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None = None

    model_config = {"from_attributes": True}


class InviteValidateResponse(BaseModel):
    email: str
    valid: bool
    expires_at: datetime


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class SessionResponse(BaseModel):
    id: str
    user_agent: str | None
    ip_address: str | None
    created_at: datetime
    last_used_at: datetime
    is_current: bool

    model_config = {"from_attributes": True}
