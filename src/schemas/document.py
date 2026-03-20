"""Document Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel


class DocumentUploadRequest(BaseModel):
    visibility: str = "public"
    team_ids: list[str] | None = None
    user_ids: list[str] | None = None
    collection_id: str | None = None
    chunking_strategy: str | None = None


class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int | None
    visibility: str
    status: str
    owner_id: str
    collection_id: str | None
    folder_id: str | None = None
    chunk_count: int
    chunking_strategy: str | None
    created_at: datetime
    tags: list[str] = []

    model_config = {"from_attributes": True}


class VisibilityUpdateRequest(BaseModel):
    visibility: str
    team_ids: list[str] | None = None
    user_ids: list[str] | None = None


class DocumentVersionResponse(BaseModel):
    id: str
    document_id: str
    version_number: int
    filename: str
    file_path: str
    file_size: int
    chunk_count: int | None
    uploaded_by_id: str | None
    created_at: datetime
    note: str | None

    model_config = {"from_attributes": True}
