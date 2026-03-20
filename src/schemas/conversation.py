"""Conversation Pydantic schemas."""

from datetime import datetime
from pydantic import BaseModel


class ConversationCreateRequest(BaseModel):
    title: str = "New conversation"
    collection_id: str | None = None


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    sources: list | None = None
    feedback: int | None = None
    follow_up_questions: list[str] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: str
    title: str
    collection_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse]


class ConversationQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    scope: str = "all"  # "all" | "personal" | "team:<team_id>"
