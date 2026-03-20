"""Admin management Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class AdminUserResponse(BaseModel):
    id: str
    username: str
    email: str
    is_active: bool
    roles: list[str]
    teams: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminCreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    roles: list[str] = ["viewer"]


class AdminSetRolesRequest(BaseModel):
    roles: list[str]


class AdminAddTeamRequest(BaseModel):
    team_id: str
