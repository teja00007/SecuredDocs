"""Team (Distribution List) Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel, Field

from src.schemas.auth import UserResponse


class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    member_ids: list[str] | None = None


class TeamResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_by: str
    member_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamDetailResponse(BaseModel):
    id: str
    name: str
    description: str | None
    created_by: str
    members: list[UserResponse]
    created_at: datetime

    model_config = {"from_attributes": True}


class AddMembersRequest(BaseModel):
    user_ids: list[str]
