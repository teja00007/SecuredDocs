"""Conversation (chat history) endpoints."""

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db, get_rag_service
from src.core.rbac import UserContext
from src.models.conversation import Conversation, ConversationMessage
from src.repositories.conversation_repository import ConversationRepository
from src.repositories.document_repository import DocumentRepository
from src.schemas.conversation import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationQueryRequest,
    ConversationResponse,
    MessageResponse,
)
from src.services.rag_service import RAGService


async def _enrich_staleness(sources: list[dict], db: AsyncSession) -> list[dict]:
    """Attach is_stale + days_since_update to each source dict."""
    if not sources:
        return sources
    doc_repo = DocumentRepository(db)
    doc_ids = list({s["document_id"] for s in sources})
    staleness: dict[str, dict] = {}
    for doc_id in doc_ids:
        doc = await doc_repo.get_by_id(doc_id)
        if doc:
            updated = doc.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - updated).days
            cycle = doc.review_cycle_days or 365
            staleness[doc_id] = {"is_stale": age_days > cycle, "days_since_update": age_days}
    return [
        {**s, **staleness.get(s["document_id"], {"is_stale": False, "days_since_update": None})}
        for s in sources
    ]

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _get_conv_repo(db: AsyncSession = Depends(get_db)) -> ConversationRepository:
    return ConversationRepository(db)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    db: AsyncSession = Depends(get_db),
):
    convs = await conv_repo.list_for_user(user.user_id)
    await db.commit()
    return [_conv_to_response(c) for c in convs]


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreateRequest,
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(
        user_id=user.user_id,
        title=body.title,
        collection_id=body.collection_id,
    )
    created = await conv_repo.create(conv)
    await db.commit()
    return _conv_to_response(created)


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    conversation_id: str,
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    db: AsyncSession = Depends(get_db),
):
    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Access denied")
    await db.commit()
    return _conv_to_detail(conv)


@router.patch("/{conversation_id}/title", response_model=ConversationResponse)
async def rename_conversation(
    conversation_id: str,
    body: ConversationCreateRequest,
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    db: AsyncSession = Depends(get_db),
):
    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    await conv_repo.update_title(conversation_id, body.title)
    await db.commit()
    conv = await conv_repo.get_by_id(conversation_id)
    return _conv_to_response(conv)  # type: ignore[arg-type]


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    db: AsyncSession = Depends(get_db),
):
    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Access denied")
    await conv_repo.delete(conversation_id)
    await db.commit()


@router.post("/{conversation_id}/query", response_model=MessageResponse)
async def query_in_conversation(
    conversation_id: str,
    body: ConversationQueryRequest,
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    rag_svc: RAGService = Depends(get_rag_service),
    db: AsyncSession = Depends(get_db),
):
    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Save user message
    user_msg = ConversationMessage(
        conversation_id=conversation_id,
        role="user",
        content=body.query,
    )
    await conv_repo.add_message(user_msg)

    # Build chat history for context (last 10 turns)
    existing = await conv_repo.get_messages(conversation_id)
    # Exclude the message we just added (it's the last one now)
    history_msgs = existing[:-1]
    chat_history = [{"role": m.role, "content": m.content} for m in history_msgs[-10:]]

    # RAG query with conversation context
    result = await rag_svc.query(
        query_text=body.query,
        user=user,
        collection_id=conv.collection_id,
        top_k=body.top_k,
        chat_history=chat_history,
    )
    enriched_sources = await _enrich_staleness(result["sources"], db)

    # Auto-title on first exchange
    if len(existing) <= 1 and conv.title == "New conversation":
        title = body.query[:60] + ("…" if len(body.query) > 60 else "")
        await conv_repo.update_title(conversation_id, title)

    # Save assistant response
    assistant_msg = ConversationMessage(
        conversation_id=conversation_id,
        role="assistant",
        content=result["answer"],
        sources=enriched_sources,
    )
    saved = await conv_repo.add_message(assistant_msg)
    await conv_repo.touch(conversation_id)
    await db.commit()

    return MessageResponse(
        id=saved.id,
        role=saved.role,
        content=saved.content,
        sources=saved.sources,
        follow_up_questions=result.get("follow_up_questions", []),
        created_at=saved.created_at,
    )


@router.patch("/{conversation_id}/messages/{message_id}/feedback", response_model=MessageResponse)
async def set_message_feedback(
    conversation_id: str,
    message_id: str,
    feedback: int | None = None,  # query param: 1, -1, or null to clear
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    db: AsyncSession = Depends(get_db),
):
    """Set thumbs up (1), thumbs down (-1), or clear (omit) feedback on an assistant message."""
    conv = await conv_repo.get_by_id(conversation_id)
    if not conv or conv.user_id != user.user_id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    msg = await conv_repo.set_feedback(message_id, feedback)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    await db.commit()
    return MessageResponse(
        id=msg.id, role=msg.role, content=msg.content,
        sources=msg.sources, feedback=msg.feedback, created_at=msg.created_at,
    )


@router.post("/{conversation_id}/stream")
async def stream_in_conversation(
    conversation_id: str,
    body: ConversationQueryRequest,
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    rag_svc: RAGService = Depends(get_rag_service),
    db: AsyncSession = Depends(get_db),
):
    """SSE streaming endpoint. Events: {"type":"token","content":"..."} then {"type":"done","sources":[...]}."""
    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Save user message
    user_msg = ConversationMessage(
        conversation_id=conversation_id,
        role="user",
        content=body.query,
    )
    await conv_repo.add_message(user_msg)

    # Build chat history (last 10 turns before this message)
    existing = await conv_repo.get_messages(conversation_id)
    history_msgs = existing[:-1]
    chat_history = [{"role": m.role, "content": m.content} for m in history_msgs[-10:]]

    # Auto-title on first exchange
    if len(existing) <= 1 and conv.title == "New conversation":
        title = body.query[:60] + ("…" if len(body.query) > 60 else "")
        await conv_repo.update_title(conversation_id, title)

    await db.commit()

    async def event_generator():
        full_answer_parts: list[str] = []
        sources_data: list[dict] = []

        try:
            async for event in rag_svc.query_stream(
                query_text=body.query,
                user=user,
                collection_id=conv.collection_id,
                top_k=body.top_k,
                chat_history=chat_history,
                scope=body.scope,
            ):
                if isinstance(event, str):
                    full_answer_parts.append(event)
                    yield f"data: {json.dumps({'type': 'token', 'content': event})}\n\n"
                else:
                    raw_sources = event.get("sources", [])
                    sources_data = await _enrich_staleness(raw_sources, db)
                    confidence_score = event.get("confidence_score", 0.0)
                    confidence_label = event.get("confidence_label", "Uncertain")
                    follow_up_questions = event.get("follow_up_questions", [])
                    yield f"data: {json.dumps({'type': 'done', 'sources': sources_data, 'confidence_score': confidence_score, 'confidence_label': confidence_label, 'follow_up_questions': follow_up_questions})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            # Always persist whatever was generated — even on client disconnect,
            # navigation away, or mid-stream abort. GeneratorExit (raised when the
            # client disconnects and Starlette calls aclose()) is not an Exception,
            # so it bypasses the except block above and lands here directly.
            full_answer = "".join(full_answer_parts)
            if full_answer.strip():
                try:
                    assistant_msg = ConversationMessage(
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_answer,
                        sources=sources_data,
                    )
                    await conv_repo.add_message(assistant_msg)
                    await conv_repo.touch(conversation_id)
                    await db.commit()
                except Exception as save_err:
                    logger.error("Failed to save assistant message to DB: %s", save_err, exc_info=True)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Deep Research (SSE streaming) ─────────────────────────────────────────────

class DeepResearchRequest(BaseModel):
    query: str
    collection_id: str | None = None


def _get_deep_research_service(
    rag_svc: RAGService = Depends(get_rag_service),
):
    """Build a DeepResearchService using the same retrieval + generation as RAGService."""
    from src.services.deep_research_service import DeepResearchService
    return DeepResearchService(
        retrieval_service=rag_svc._retrieval,
        generation_service=rag_svc._generation,
    )


@router.post("/{conversation_id}/deep-research")
async def deep_research_in_conversation(
    conversation_id: str,
    body: DeepResearchRequest,
    user: UserContext = Depends(get_current_user),
    conv_repo: ConversationRepository = Depends(_get_conv_repo),
    rag_svc: RAGService = Depends(get_rag_service),
    db: AsyncSession = Depends(get_db),
):
    """SSE streaming deep-research endpoint.

    Streams progress events as Server-Sent Events:
      - {"type": "step", "step": "...", "content": "..."}
      - {"type": "done", "answer": "...", "sources": [...], "sub_questions": [...], "steps_taken": N}
      - {"type": "error", "message": "..."}

    The final answer is saved to the conversation as an assistant message.
    """
    from src.services.deep_research_service import DeepResearchService

    conv = await conv_repo.get_by_id(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied")

    deep_svc = DeepResearchService(
        retrieval_service=rag_svc._retrieval,
        generation_service=rag_svc._generation,
    )

    # Save the user message
    user_msg = ConversationMessage(
        conversation_id=conversation_id,
        role="user",
        content=body.query,
    )
    await conv_repo.add_message(user_msg)

    # Auto-title on first exchange
    existing = await conv_repo.get_messages(conversation_id)
    if len(existing) <= 1 and conv.title == "New conversation":
        title = f"[Research] {body.query[:55]}" + ("…" if len(body.query) > 55 else "")
        await conv_repo.update_title(conversation_id, title)

    await db.commit()

    async def event_generator():
        final_answer = ""
        final_sources: list[dict] = []

        try:
            generator = await deep_svc.research(
                query=body.query,
                user=user,
                collection_id=body.collection_id,
            )
            async for event in generator:
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    final_answer = event.get("answer", "")
                    final_sources = event.get("sources", [])
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
            return

        # Persist final answer as an assistant message
        if final_answer:
            assistant_msg = ConversationMessage(
                conversation_id=conversation_id,
                role="assistant",
                content=final_answer,
                sources=final_sources,
            )
            await conv_repo.add_message(assistant_msg)
            await conv_repo.touch(conversation_id)
            await db.commit()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _conv_to_response(conv: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        collection_id=conv.collection_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


def _conv_to_detail(conv: Conversation) -> ConversationDetailResponse:
    messages = [
        MessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            sources=m.sources,
            created_at=m.created_at,
        )
        for m in conv.messages
    ]
    return ConversationDetailResponse(
        id=conv.id,
        title=conv.title,
        collection_id=conv.collection_id,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=messages,
    )
