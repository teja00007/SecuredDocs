"""Query request/response Pydantic schemas."""

import re
from pydantic import BaseModel, Field, field_validator


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    collection_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        # Strip null bytes and control characters (except newlines/tabs)
        v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v)
        # Collapse runs of 3+ blank lines to 2
        v = re.sub(r"\n{3,}", "\n\n", v)
        return v.strip()


class SourceResponse(BaseModel):
    document_id: str
    filename: str
    chunk_text: str
    page_number: int | None
    score: float
    is_stale: bool = False
    days_since_update: int | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    confidence_score: float = 0.0
    confidence_label: str = "Uncertain"
    follow_up_questions: list[str] = []
