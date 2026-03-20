"""Training dataset API — feedback collection only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db
from src.config import get_settings
from src.services.training_service import TrainingService

router = APIRouter(prefix="/training", tags=["training"])


class FeedbackRequest(BaseModel):
    query: str
    answer: str
    feedback: str = Field(..., pattern="^(thumbs_up|thumbs_down|neutral)$")
    context: str | None = None
    system_prompt: str | None = None
    model_name: str | None = None
    confidence_score: float | None = None
    corrected_answer: str | None = None


def _svc(db: AsyncSession = Depends(get_db)) -> TrainingService:
    settings = get_settings()
    return TrainingService(db=db, openai_api_key=settings.OPENAI_API_KEY)


@router.post("/feedback")
async def record_feedback(
    body: FeedbackRequest,
    current_user=Depends(get_current_user),
    svc: TrainingService = Depends(_svc),
):
    """Record thumbs-up / thumbs-down on a RAG response."""
    example = await svc.record_feedback(
        query=body.query,
        answer=body.answer,
        feedback=body.feedback,
        context=body.context,
        system_prompt=body.system_prompt,
        model_name=body.model_name,
        confidence_score=body.confidence_score,
        corrected_answer=body.corrected_answer,
        rated_by=current_user.user_id,
        company_id=getattr(current_user, "company_id", None),
    )
    return {"id": example.id, "feedback": example.feedback, "approved": example.approved_for_training}
