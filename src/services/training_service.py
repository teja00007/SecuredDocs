"""Training dataset curation, export, and fine-tuning job management.

Features
--------
- Record thumbs-up / thumbs-down feedback on query responses
- Export approved examples in OpenAI JSONL / Alpaca / ShareGPT formats
- Submit fine-tuning jobs to OpenAI or track local LoRA runs
- Fine-tuned embedding model registry with per-collection model override
"""

from __future__ import annotations

import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.training import TrainingExample, FeedbackEnum

logger = logging.getLogger(__name__)

ExportFormat = Literal["openai_jsonl", "alpaca", "sharegpt"]


class TrainingService:
    """High-level API for training data curation and fine-tuning jobs."""

    def __init__(self, db: AsyncSession, openai_api_key: str = "") -> None:
        self._db = db
        self._openai_api_key = openai_api_key

    # ── Feedback recording ────────────────────────────────────────────────────

    async def record_feedback(
        self,
        query: str,
        answer: str,
        feedback: str,
        *,
        context: str | None = None,
        system_prompt: str | None = None,
        model_name: str | None = None,
        confidence_score: float | None = None,
        corrected_answer: str | None = None,
        rated_by: str | None = None,
        company_id: str | None = None,
    ) -> TrainingExample:
        """Record user feedback for a RAG response."""
        example = TrainingExample(
            id=str(uuid.uuid4()),
            query=query,
            answer=answer,
            feedback=FeedbackEnum(feedback),
            context=context,
            system_prompt=system_prompt,
            model_name=model_name,
            confidence_score=confidence_score,
            corrected_answer=corrected_answer,
            rated_by=rated_by,
            company_id=company_id,
            approved_for_training=(feedback == FeedbackEnum.THUMBS_UP),
        )
        self._db.add(example)
        await self._db.commit()
        await self._db.refresh(example)
        logger.info("Recorded training example %s (feedback=%s)", example.id, feedback)
        return example

    async def list_examples(
        self,
        company_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[TrainingExample]:
        """Return training examples, optionally filtered by company."""
        stmt = select(TrainingExample).order_by(TrainingExample.created_at.desc()).limit(limit).offset(offset)
        if company_id:
            stmt = stmt.where(TrainingExample.company_id == company_id)
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def approve_example(
        self,
        example_id: str,
        approved: bool = True,
        corrected_answer: str | None = None,
    ) -> TrainingExample:
        """Set approval status for a training example."""
        result = await self._db.execute(
            select(TrainingExample).where(TrainingExample.id == example_id)
        )
        example = result.scalar_one_or_none()
        if example is None:
            raise ValueError(f"Training example {example_id!r} not found")
        example.approved_for_training = approved
        if corrected_answer is not None:
            example.corrected_answer = corrected_answer
        await self._db.commit()
        return example

    # ── Export ────────────────────────────────────────────────────────────────

    async def export(
        self,
        fmt: ExportFormat = "openai_jsonl",
        company_id: str | None = None,
        approved_only: bool = True,
        feedback_filter: str | None = None,
    ) -> bytes:
        """Export training examples as bytes.

        Parameters
        ----------
        fmt:
            "openai_jsonl" | "alpaca" | "sharegpt"
        company_id:
            Filter to a specific company (None = all).
        approved_only:
            Only include examples marked approved_for_training=True.
        feedback_filter:
            "thumbs_up" | "thumbs_down" | None (all).

        Returns
        -------
        bytes
            UTF-8 encoded JSONL or JSON.
        """
        filters = []
        if approved_only:
            filters.append(TrainingExample.approved_for_training == True)  # noqa: E712
        if company_id:
            filters.append(TrainingExample.company_id == company_id)
        if feedback_filter:
            filters.append(TrainingExample.feedback == FeedbackEnum(feedback_filter))

        result = await self._db.execute(
            select(TrainingExample).where(and_(*filters)) if filters else select(TrainingExample)
        )
        examples = list(result.scalars().all())
        logger.info("Exporting %d training examples as %s", len(examples), fmt)

        if fmt == "openai_jsonl":
            lines = [json.dumps(ex.to_openai_jsonl()) for ex in examples]
            return "\n".join(lines).encode()
        elif fmt == "alpaca":
            records = [ex.to_alpaca() for ex in examples]
            return json.dumps(records, indent=2).encode()
        elif fmt == "sharegpt":
            records = [ex.to_sharegpt() for ex in examples]
            return json.dumps(records, indent=2).encode()
        else:
            raise ValueError(f"Unknown export format: {fmt!r}")

    # ── Fine-tuning job management ────────────────────────────────────────────

    async def submit_openai_finetune(
        self,
        company_id: str | None = None,
        base_model: str = "gpt-3.5-turbo",
        suffix: str | None = None,
    ) -> dict:
        """Export approved examples and submit a fine-tuning job to OpenAI.

        Returns the OpenAI fine-tuning job dict.
        """
        if not self._openai_api_key:
            raise ValueError("OPENAI_API_KEY required for fine-tuning submission")

        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai SDK not installed. Run: pip install openai")

        # Export examples in JSONL format
        data = await self.export("openai_jsonl", company_id=company_id)
        if not data.strip():
            raise ValueError("No approved training examples to export")

        client = OpenAI(api_key=self._openai_api_key)

        # Upload training file
        file_obj = io.BytesIO(data)
        file_obj.name = "training.jsonl"
        upload = client.files.create(file=file_obj, purpose="fine-tune")
        logger.info("Uploaded training file: %s", upload.id)

        # Submit fine-tuning job
        kwargs: dict = {"training_file": upload.id, "model": base_model}
        if suffix:
            kwargs["suffix"] = suffix
        job = client.fine_tuning.jobs.create(**kwargs)
        logger.info("Fine-tuning job submitted: %s", job.id)

        return {
            "job_id": job.id,
            "status": job.status,
            "model": job.model,
            "training_file": upload.id,
            "created_at": job.created_at,
        }

    async def get_openai_finetune_status(self, job_id: str) -> dict:
        """Check the status of an OpenAI fine-tuning job."""
        if not self._openai_api_key:
            raise ValueError("OPENAI_API_KEY required")
        from openai import OpenAI
        client = OpenAI(api_key=self._openai_api_key)
        job = client.fine_tuning.jobs.retrieve(job_id)
        return {
            "job_id": job.id,
            "status": job.status,
            "model": job.model,
            "fine_tuned_model": getattr(job, "fine_tuned_model", None),
            "trained_tokens": getattr(job, "trained_tokens", None),
        }

    async def list_openai_finetune_jobs(self, limit: int = 10) -> list[dict]:
        """List recent OpenAI fine-tuning jobs."""
        if not self._openai_api_key:
            raise ValueError("OPENAI_API_KEY required")
        from openai import OpenAI
        client = OpenAI(api_key=self._openai_api_key)
        jobs = client.fine_tuning.jobs.list(limit=limit)
        return [
            {
                "job_id": j.id,
                "status": j.status,
                "model": j.model,
                "fine_tuned_model": getattr(j, "fine_tuned_model", None),
                "created_at": j.created_at,
            }
            for j in jobs.data
        ]


# ── Embedding model registry ──────────────────────────────────────────────────

class EmbeddingModelRegistry:
    """Per-collection fine-tuned embedding model override.

    Stores a mapping: collection_id → embedding model name.
    Falls back to the global default when no override is set.

    The registry is backed by the admin_settings table
    (key: "embedding_model_overrides", value: JSON).
    """

    _KEY = "embedding_model_overrides"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_model(self, collection_id: str, default: str) -> str:
        """Return the embedding model for *collection_id*, or *default*."""
        overrides = await self._load()
        return overrides.get(collection_id, default)

    async def set_model(self, collection_id: str, model_name: str) -> None:
        """Set a custom embedding model for *collection_id*."""
        overrides = await self._load()
        overrides[collection_id] = model_name
        await self._save(overrides)
        logger.info("Embedding model override set: %s → %s", collection_id, model_name)

    async def remove_model(self, collection_id: str) -> None:
        """Remove the override for *collection_id* (reverts to global default)."""
        overrides = await self._load()
        overrides.pop(collection_id, None)
        await self._save(overrides)

    async def list_overrides(self) -> dict[str, str]:
        return await self._load()

    async def _load(self) -> dict[str, str]:
        from src.models.admin_settings import AdminSetting
        result = await self._db.execute(
            select(AdminSetting).where(AdminSetting.key == self._KEY)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return {}
        try:
            return json.loads(row.value)
        except (json.JSONDecodeError, TypeError):
            return {}

    async def _save(self, overrides: dict[str, str]) -> None:
        from src.models.admin_settings import AdminSetting
        result = await self._db.execute(
            select(AdminSetting).where(AdminSetting.key == self._KEY)
        )
        row = result.scalar_one_or_none()
        serialized = json.dumps(overrides)
        if row is None:
            self._db.add(AdminSetting(key=self._KEY, value=serialized))
        else:
            row.value = serialized
        await self._db.commit()
