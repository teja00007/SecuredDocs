"""Collection Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel, Field


class CollectionCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class CollectionResponse(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str
    is_public: bool
    document_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
