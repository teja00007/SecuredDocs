"""Training dataset models for fine-tuning.

TrainingExample
---------------
Stores a query+answer pair with a thumbs-up/down rating from a user.
Used to curate datasets for LLM fine-tuning.

Fine-tuning export formats supported:
- JSONL (OpenAI fine-tune chat format)
- Alpaca (instruction/input/output)
- ShareGPT (conversations list)
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Float, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class FeedbackEnum(str, enum.Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    NEUTRAL = "neutral"


class TrainingExample(Base):
    """A rated query-response pair for fine-tuning dataset curation."""

    __tablename__ = "training_examples"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # The query that was asked
    query: Mapped[str] = mapped_column(Text, nullable=False)
    # The RAG-generated answer
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # Context chunks that were retrieved (JSON string)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    # System prompt used
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which model produced the answer
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # User feedback
    feedback: Mapped[str] = mapped_column(
        Enum(FeedbackEnum), nullable=False, default=FeedbackEnum.NEUTRAL, index=True
    )
    # Free-form correction (human-edited ideal answer)
    corrected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Confidence score from the RAG pipeline
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Who rated it and when
    rated_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    company_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Whether this example is approved for export
    approved_for_training: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    rater = relationship("User", foreign_keys=[rated_by], lazy="selectin")

    def to_openai_jsonl(self) -> dict:
        """Format as OpenAI fine-tune chat completion entry."""
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if self.context:
            messages.append({
                "role": "system",
                "content": f"Retrieved context:\n{self.context}",
            })
        messages.append({"role": "user", "content": self.query})
        # Use corrected answer if available, otherwise the original
        answer = self.corrected_answer or self.answer
        messages.append({"role": "assistant", "content": answer})
        return {"messages": messages}

    def to_alpaca(self) -> dict:
        """Format as Alpaca instruction-tuning entry."""
        instruction = self.system_prompt or "Answer the user's question using the provided context."
        return {
            "instruction": instruction,
            "input": self.query,
            "output": self.corrected_answer or self.answer,
        }

    def to_sharegpt(self) -> dict:
        """Format as ShareGPT conversation entry."""
        conversations = []
        if self.system_prompt:
            conversations.append({"from": "system", "value": self.system_prompt})
        conversations.append({"from": "human", "value": self.query})
        conversations.append({"from": "gpt", "value": self.corrected_answer or self.answer})
        return {"conversations": conversations}

    def __repr__(self) -> str:
        return f"<TrainingExample {self.id} feedback={self.feedback}>"
