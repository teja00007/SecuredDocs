"""Document management endpoints."""

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import (
    get_current_user, get_db, get_document_repo, get_document_service,
    get_generation_service, get_ingestion_service, require_permission, get_rag_service,
)
from src.config import get_settings, Settings
from src.core.exceptions import DocumentNotFoundError, AuthorizationError, PHIViolationError
from src.core.phi_scanner import scan as phi_scan, extract_text_for_scan
from src.core.rbac import UserContext
from src.ingestion.parser_factory import list_supported_types
from src.models.document import Document, DocumentFolder, DocumentTag, DocumentVersion
from src.repositories.document_repository import DocumentRepository
from src.schemas.document import DocumentResponse, DocumentVersionResponse, VisibilityUpdateRequest
from src.services.document_service import DocumentService
from src.services.generation_service import GenerationService
from src.services.ingestion_service import IngestionService
from src.services.rag_service import RAGService

router = APIRouter(prefix="/documents", tags=["documents"])

_UPLOAD_DIR = Path("data/uploads")


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    visibility: str = Form(default="public"),
    collection_id: str | None = Form(default=None),
    chunking_strategy: str | None = Form(default=None),
    team_ids: str | None = Form(default=None),
    user_ids: str | None = Form(default=None),
    channel_id: str | None = Form(default=None),
    user: UserContext = Depends(require_permission("document:write")),
    document_repo: DocumentRepository = Depends(get_document_repo),
    ingestion_svc: IngestionService = Depends(get_ingestion_service),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    # Validate file type
    suffix = Path(file.filename or "").suffix.lower()
    supported = list_supported_types()
    if suffix not in supported:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type '{suffix}'. Supported: {supported}",
        )

    # Check file size
    content = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    # PHI / HIPAA compliance scan — block upload if protected health info is detected
    import asyncio
    doc_text = await asyncio.to_thread(extract_text_for_scan, content, suffix)
    if doc_text:
        violations = phi_scan(doc_text)
        if violations:
            frameworks = sorted({v.framework for v in violations})
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "COMPLIANCE_VIOLATION",
                    "message": (
                        f"Upload blocked: this document contains sensitive data that may violate "
                        f"{', '.join(frameworks)} regulations. "
                        "Remove or redact the sensitive data before uploading."
                    ),
                    "violations": [
                        {
                            "category": v.category,
                            "label": v.label,
                            "framework": v.framework,
                            "occurrences": v.count,
                        }
                        for v in violations
                    ],
                },
            )

    # Check if a document with the same filename already exists for this owner (version bump)
    existing_doc = await document_repo.get_by_filename_and_owner(
        file.filename or "upload", user.user_id
    )

    if existing_doc is not None:
        # ── Version bump path ─────────────────────────────────────────────────
        doc_id = existing_doc.id
        current_ver = getattr(existing_doc, "current_version", 1) or 1

        # Archive the current file to versions directory
        if existing_doc.file_path and Path(existing_doc.file_path).exists():
            version_dir = _UPLOAD_DIR / doc_id / "versions" / f"v{current_ver}"
            version_dir.mkdir(parents=True, exist_ok=True)
            archive_path = version_dir / existing_doc.filename
            shutil.copy2(existing_doc.file_path, archive_path)

            dv = DocumentVersion(
                id=str(uuid.uuid4()),
                document_id=doc_id,
                version_number=current_ver,
                filename=existing_doc.filename,
                file_path=str(archive_path),
                file_size=existing_doc.file_size or 0,
                chunk_count=existing_doc.chunk_count,
                uploaded_by_id=user.user_id,
                note=None,
            )
            db.add(dv)

        # Write the new file content over the current location
        upload_path = _UPLOAD_DIR / doc_id
        upload_path.mkdir(parents=True, exist_ok=True)
        new_file_path = upload_path / (file.filename or "upload")
        new_file_path.write_bytes(content)

        existing_doc.file_size = len(content)
        existing_doc.file_path = str(new_file_path)
        existing_doc.current_version = current_ver + 1
        existing_doc.status = "pending"
        await db.flush()
        await db.commit()

        background_tasks.add_task(ingestion_svc.reingest_document, document_id=doc_id)
        return {
            "document_id": doc_id,
            "status": "pending",
            "message": "Version updated, re-ingestion started",
            "version": current_ver + 1,
        }

    # Save to disk
    document_id = str(uuid.uuid4())
    upload_path = _UPLOAD_DIR / document_id
    upload_path.mkdir(parents=True, exist_ok=True)
    file_path = upload_path / (file.filename or "upload")
    file_path.write_bytes(content)

    # Parse team_ids/user_ids from comma-separated form strings
    parsed_team_ids = [t.strip() for t in team_ids.split(",") if t.strip()] if team_ids else []
    parsed_user_ids = [u.strip() for u in user_ids.split(",") if u.strip()] if user_ids else []

    # Channel visibility: resolve channel members → allowed_users so existing RBAC works
    if visibility == "channel" and channel_id:
        from sqlalchemy import select as sa_select
        from src.models.chat import ChannelMember
        result = await db.execute(
            sa_select(ChannelMember.user_id).where(ChannelMember.channel_id == channel_id)
        )
        member_ids = [row[0] for row in result.all()]
        # Merge with any explicit user_ids, always include owner
        combined = list({user.user_id} | set(member_ids) | set(parsed_user_ids))
        parsed_user_ids = combined

    # Confidential docs: owner is always in allowed_users so the RBAC vector filter works
    if visibility == "confidential" and user.user_id not in parsed_user_ids:
        parsed_user_ids.insert(0, user.user_id)

    # Create DB record
    doc = Document(
        id=document_id,
        filename=file.filename or "upload",
        file_type=suffix,
        file_size=len(content),
        visibility=visibility,
        collection_id=collection_id,
        owner_id=user.user_id,
        chunking_strategy=chunking_strategy,
        file_path=str(file_path),
        status="pending",
        current_version=1,
    )
    await document_repo.create(doc)

    if parsed_team_ids:
        await document_repo.set_team_access(document_id, parsed_team_ids)
    if parsed_user_ids:
        await document_repo.set_user_access(document_id, parsed_user_ids)

    await db.commit()

    # Build visibility metadata for ingestion
    visibility_metadata = {
        "owner_id": user.user_id,
        "filename": file.filename or "upload",
        "visibility": visibility,
        "chunking_strategy": chunking_strategy,
        "collection_id": collection_id or "",
        "company_id": user.company_id or "",
        "allowed_teams": "|" + "|".join(parsed_team_ids) + "|" if parsed_team_ids else "",
        "allowed_users": "|" + "|".join(parsed_user_ids) + "|" if parsed_user_ids else "",
        "channel_id": channel_id or "",
    }

    # Dispatch ingestion to Celery if Redis is available; fall back to
    # FastAPI BackgroundTasks for local dev environments without Redis.
    _celery_dispatched = False
    if os.getenv("REDIS_URL"):
        try:
            from src.tasks.ingestion_tasks import ingest_document_task
            ingest_document_task.delay(document_id, str(file_path), suffix, visibility_metadata)
            _celery_dispatched = True
        except Exception as _celery_err:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Celery dispatch failed (%s); falling back to BackgroundTasks", _celery_err
            )

    if not _celery_dispatched:
        background_tasks.add_task(
            ingestion_svc.ingest_document,
            document_id=document_id,
            file_path=str(file_path),
            file_type=suffix,
            visibility_metadata=visibility_metadata,
        )

    # Feature 4 — Outbound webhook: fire "document.uploaded" notification.
    # Runs in a background task so it never blocks the upload response.
    background_tasks.add_task(
        _trigger_document_uploaded_webhook,
        document_id=document_id,
        filename=file.filename or "upload",
        owner_id=user.user_id,
        settings=settings,
    )

    return {"document_id": document_id, "status": "pending", "message": "Ingestion started"}


async def _trigger_document_uploaded_webhook(
    document_id: str,
    filename: str,
    owner_id: str,
    settings,
) -> None:
    """Background task: deliver 'document.uploaded' webhook notification.

    Uses a fresh DB session so it is safe to call from BackgroundTasks after
    the request session has been closed.
    """
    try:
        from src.db.session import get_async_engine, get_session_factory
        from src.services.webhook_service import WebhookService
        engine = get_async_engine(settings.DATABASE_URL)
        factory = get_session_factory(engine)
        async with factory() as session:
            await WebhookService().trigger(
                event_type="document.uploaded",
                payload={"document_id": document_id, "filename": filename, "owner_id": owner_id},
                db=session,
            )
            await session.commit()
    except Exception:
        pass  # Non-fatal — never crash the upload flow


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    skip: int = 0,
    limit: int = 20,
    collection_id: str | None = None,
    folder_id: str | None = Query(default=None, description="Filter by folder ID"),
    tag: str | None = Query(default=None, description="Filter by tag"),
    user: UserContext = Depends(require_permission("document:read")),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    docs = await document_repo.list_accessible(
        user_id=user.user_id,
        user_team_ids=user.team_ids,
        skip=skip,
        limit=limit,
        collection_id=collection_id,
    )

    if folder_id is not None:
        docs = [d for d in docs if d.folder_id == folder_id]

    if tag:
        tag_normalized = tag.strip().lower()
        doc_ids = [d.id for d in docs]
        if doc_ids:
            tag_result = await db.execute(
                select(DocumentTag.document_id).where(
                    and_(
                        DocumentTag.document_id.in_(doc_ids),
                        DocumentTag.tag == tag_normalized,
                    )
                )
            )
            tagged_ids = {row[0] for row in tag_result.all()}
            docs = [d for d in docs if d.id in tagged_ids]

    return [_doc_to_response(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    user: UserContext = Depends(require_permission("document:read")),
    document_repo: DocumentRepository = Depends(get_document_repo),
):
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    from src.core.rbac import check_document_access
    meta = {
        "owner_id": doc.owner_id,
        "visibility": doc.visibility,
        "allowed_teams": [ta.team_id for ta in doc.team_access],
        "allowed_users": [ua.user_id for ua in doc.user_access],
    }
    if not check_document_access(user, meta):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    return _doc_to_response(doc)


@router.post("/{document_id}/summarize")
async def summarize_document(
    document_id: str,
    user: UserContext = Depends(require_permission("document:read")),
    document_repo: DocumentRepository = Depends(get_document_repo),
    generation_svc: GenerationService = Depends(get_generation_service),
):
    """Generate an AI summary of a document using its stored chunks.

    Retrieves up to 20 chunks from the BM25 index (or vector store fallback),
    concatenates up to 8000 chars, then calls the LLM synchronously.
    """
    # RBAC check — same as GET /documents/{document_id}
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    from src.core.rbac import check_document_access
    access_meta = {
        "owner_id": doc.owner_id,
        "visibility": doc.visibility,
        "allowed_teams": [ta.team_id for ta in doc.team_access],
        "allowed_users": [ua.user_id for ua in doc.user_access],
    }
    if not check_document_access(user, access_meta):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Retrieve up to 20 chunks for this document via BM25 chunk store
    from src.services.bm25_service import BM25Service
    import asyncio as _asyncio

    bm25_svc = BM25Service()
    # Filter chunk store by document_id directly
    doc_chunks = [
        entry
        for cid, entry in bm25_svc._chunk_store.items()
        if entry.get("metadata", {}).get("document_id") == document_id
    ]
    doc_chunks = doc_chunks[:20]

    # Build concatenated context (up to ~8000 chars)
    chunk_texts: list[str] = []
    total_chars = 0
    for entry in doc_chunks:
        text = entry.get("text", "")
        if total_chars + len(text) > 8000:
            remaining = 8000 - total_chars
            if remaining > 0:
                chunk_texts.append(text[:remaining])
            break
        chunk_texts.append(text)
        total_chars += len(text)

    chunk_count = len(doc_chunks)

    if not chunk_texts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No chunks found for this document. It may not have been ingested yet.",
        )

    combined_text = "\n\n".join(chunk_texts)
    prompt = f"Summarize the following document titled '{doc.filename}':\n\n{combined_text}"

    messages = [
        {"role": "system", "content": "You are Nexus, a helpful enterprise AI assistant. Produce a concise, accurate summary of the provided document. Focus on key topics, findings, and conclusions."},
        {"role": "user", "content": prompt},
    ]

    import asyncio
    from src.core.interfaces import LLMResponse
    try:
        response: LLMResponse = await asyncio.wait_for(
            generation_svc._llm.generate(messages, temperature=0.1),
            timeout=90.0,
        )
        summary = (response.content or "").strip()
        if not summary:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LLM returned an empty summary.")
    except asyncio.TimeoutError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="LLM request timed out.")

    return {
        "document_id": document_id,
        "filename": doc.filename,
        "summary": summary,
        "chunk_count": chunk_count,
    }


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if doc.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can delete")

    await document_repo.delete(document_id)
    await db.commit()


@router.patch("/{document_id}/visibility", status_code=status.HTTP_204_NO_CONTENT)
async def update_visibility(
    document_id: str,
    body: VisibilityUpdateRequest,
    user: UserContext = Depends(get_current_user),
    document_svc: DocumentService = Depends(get_document_service),
    db: AsyncSession = Depends(get_db),
):
    try:
        await document_svc.change_visibility(
            document_id=document_id,
            new_visibility=body.visibility,
            team_ids=body.team_ids,
            user_ids=body.user_ids,
            user=user,
        )
        await db.commit()
    except DocumentNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


class BulkDeleteRequest(BaseModel):
    document_ids: list[str]


class BulkMoveRequest(BaseModel):
    document_ids: list[str]
    collection_id: str | None  # None removes from collection


@router.post("/bulk/delete", status_code=status.HTTP_200_OK)
async def bulk_delete_documents(
    body: BulkDeleteRequest,
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    deleted = 0
    for doc_id in body.document_ids:
        doc = await document_repo.get_by_id(doc_id)
        if not doc:
            continue
        if doc.owner_id != user.user_id and "admin" not in user.roles:
            continue
        await document_repo.delete(doc_id)
        deleted += 1
    await db.commit()
    return {"deleted": deleted}


@router.patch("/bulk/collection", status_code=status.HTTP_200_OK)
async def bulk_move_documents(
    body: BulkMoveRequest,
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    moved = 0
    for doc_id in body.document_ids:
        doc = await document_repo.get_by_id(doc_id)
        if not doc:
            continue
        if doc.owner_id != user.user_id and "admin" not in user.roles:
            continue
        doc.collection_id = body.collection_id
        moved += 1
    await db.commit()
    return {"moved": moved}


@router.post("/{document_id}/reingest", status_code=status.HTTP_202_ACCEPTED)
async def reingest_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    ingestion_svc: IngestionService = Depends(get_ingestion_service),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if doc.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can re-ingest")
    if not doc.file_path:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No file stored for this document")

    await document_repo.set_status(document_id, "pending")
    await db.commit()

    background_tasks.add_task(ingestion_svc.reingest_document, document_id=document_id)
    return {"document_id": document_id, "status": "pending", "message": "Re-ingestion started"}


@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    user: UserContext = Depends(require_permission("document:read")),
    document_repo: DocumentRepository = Depends(get_document_repo),
):
    from fastapi.responses import FileResponse as FR
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    from src.core.rbac import check_document_access
    meta = {
        "owner_id": doc.owner_id,
        "visibility": doc.visibility,
        "allowed_teams": [ta.team_id for ta in doc.team_access],
        "allowed_users": [ua.user_id for ua in doc.user_access],
    }
    if not check_document_access(user, meta):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not stored on disk")

    import mimetypes
    disposition = "inline"
    media_type, _ = mimetypes.guess_type(doc.filename)
    if not media_type:
        media_type = "application/octet-stream"
        disposition = "attachment"
    headers = {"Content-Disposition": f'{disposition}; filename="{doc.filename}"'}
    return FR(path=doc.file_path, filename=doc.filename, media_type=media_type, headers=headers)


def _doc_to_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        visibility=doc.visibility,
        status=doc.status,
        owner_id=doc.owner_id,
        collection_id=doc.collection_id,
        folder_id=doc.folder_id,
        chunk_count=doc.chunk_count,
        chunking_strategy=doc.chunking_strategy,
        created_at=doc.created_at,
        tags=doc.tags,
    )


# ── Tagging ────────────────────────────────────────────────────────────────────

class TagsRequest(BaseModel):
    tags: list[str]


@router.get("/tags", response_model=list[dict])
async def list_all_tags(
    user: UserContext = Depends(require_permission("document:read")),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    """Return all unique tags used in documents the user can access, sorted by count desc."""
    docs = await document_repo.list_accessible(
        user_id=user.user_id,
        user_team_ids=user.team_ids,
        skip=0,
        limit=10000,
    )
    doc_ids = [d.id for d in docs]
    if not doc_ids:
        return []

    result = await db.execute(
        select(DocumentTag.tag, func.count(DocumentTag.document_id).label("count"))
        .where(DocumentTag.document_id.in_(doc_ids))
        .group_by(DocumentTag.tag)
        .order_by(func.count(DocumentTag.document_id).desc())
    )
    return [{"tag": row.tag, "count": row.count} for row in result.all()]


@router.post("/{document_id}/tags", status_code=status.HTTP_200_OK)
async def add_tags(
    document_id: str,
    body: TagsRequest,
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    """Add tags to a document. Only owner or admin can tag."""
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if doc.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can tag")

    # Normalize tags: lowercase, strip, max 64 chars, skip empty
    new_tags = list({t.strip().lower()[:64] for t in body.tags if t.strip()})

    # Enforce max 10 tags per document
    existing_tags = [dt.tag for dt in doc.document_tags]
    combined = list({*existing_tags, *new_tags})
    if len(combined) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document cannot have more than 10 tags (would have {len(combined)})",
        )

    # Upsert — add only tags that don't already exist
    existing_set = set(existing_tags)
    for tag_val in new_tags:
        if tag_val not in existing_set:
            db.add(DocumentTag(document_id=document_id, tag=tag_val))

    await db.commit()
    await db.refresh(doc)
    return {"tags": doc.tags}


@router.delete("/{document_id}/tags/{tag}", status_code=status.HTTP_200_OK)
async def remove_tag(
    document_id: str,
    tag: str,
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    """Remove a specific tag from a document."""
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if doc.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can remove tags")

    tag_normalized = tag.strip().lower()
    result = await db.execute(
        select(DocumentTag).where(
            and_(DocumentTag.document_id == document_id, DocumentTag.tag == tag_normalized)
        )
    )
    dt = result.scalar_one_or_none()
    if not dt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found on this document")

    await db.delete(dt)
    await db.commit()
    await db.refresh(doc)
    return {"tags": doc.tags}


# ── Version History ───────────────────────────────────────────────────────────

@router.get("/{document_id}/versions", response_model=list[DocumentVersionResponse])
async def list_versions(
    document_id: str,
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    """List all archived versions for a document (owner or admin only)."""
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if doc.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can view versions")

    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number)
    )
    versions = list(result.scalars().all())
    return [
        DocumentVersionResponse(
            id=v.id,
            document_id=v.document_id,
            version_number=v.version_number,
            filename=v.filename,
            file_path=v.file_path,
            file_size=v.file_size,
            chunk_count=v.chunk_count,
            uploaded_by_id=v.uploaded_by_id,
            created_at=v.created_at,
            note=v.note,
        )
        for v in versions
    ]


@router.post("/{document_id}/versions/{version_number}/restore", status_code=status.HTTP_202_ACCEPTED)
async def restore_version(
    document_id: str,
    version_number: int,
    background_tasks: BackgroundTasks,
    note: str | None = Query(default=None, description="Optional note for the restore action"),
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    ingestion_svc: IngestionService = Depends(get_ingestion_service),
    db: AsyncSession = Depends(get_db),
):
    """Restore a document to a previous version."""
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if doc.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can restore versions")

    result = await db.execute(
        select(DocumentVersion).where(
            and_(
                DocumentVersion.document_id == document_id,
                DocumentVersion.version_number == version_number,
            )
        )
    )
    target_ver = result.scalar_one_or_none()
    if not target_ver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found for this document",
        )
    if not Path(target_ver.file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Archived file for version {version_number} not found on disk",
        )

    current_ver = getattr(doc, "current_version", 1) or 1

    # Archive the current live file first
    if doc.file_path and Path(doc.file_path).exists():
        version_dir = _UPLOAD_DIR / document_id / "versions" / f"v{current_ver}"
        version_dir.mkdir(parents=True, exist_ok=True)
        archive_path = version_dir / doc.filename
        shutil.copy2(doc.file_path, archive_path)

        dv = DocumentVersion(
            id=str(uuid.uuid4()),
            document_id=document_id,
            version_number=current_ver,
            filename=doc.filename,
            file_path=str(archive_path),
            file_size=doc.file_size or 0,
            chunk_count=doc.chunk_count,
            uploaded_by_id=user.user_id,
            note=f"Auto-archived before restore to v{version_number}",
        )
        db.add(dv)

    # Restore the archived version file to the current location
    upload_path = _UPLOAD_DIR / document_id
    upload_path.mkdir(parents=True, exist_ok=True)
    restore_file_path = upload_path / target_ver.filename
    shutil.copy2(target_ver.file_path, restore_file_path)

    # Update document record
    doc.filename = target_ver.filename
    doc.file_path = str(restore_file_path)
    doc.file_size = target_ver.file_size
    doc.current_version = current_ver + 1
    doc.status = "pending"

    # Create a version entry for the restore action
    restore_note = note or f"Restored from version {version_number}"
    dv_restore = DocumentVersion(
        id=str(uuid.uuid4()),
        document_id=document_id,
        version_number=current_ver + 1,
        filename=target_ver.filename,
        file_path=str(restore_file_path),
        file_size=target_ver.file_size,
        chunk_count=target_ver.chunk_count,
        uploaded_by_id=user.user_id,
        note=restore_note,
    )
    db.add(dv_restore)

    await db.commit()

    background_tasks.add_task(ingestion_svc.reingest_document, document_id=document_id)
    return {
        "document_id": document_id,
        "status": "pending",
        "message": f"Restored to version {version_number}, re-ingestion started",
        "new_version": current_ver + 1,
    }


# ── Folder Hierarchy ──────────────────────────────────────────────────────────


class FolderCreateRequest(BaseModel):
    name: str
    collection_id: str
    parent_folder_id: str | None = None


class FolderRenameRequest(BaseModel):
    name: str | None = None
    parent_folder_id: str | None = None  # set to move the folder


class FolderMoveDocumentRequest(BaseModel):
    folder_id: str | None  # None = remove from folder (root of collection)


def _folder_to_tree(folder: DocumentFolder) -> dict:
    """Recursively convert a DocumentFolder ORM object to a tree dict."""
    return {
        "id": folder.id,
        "name": folder.name,
        "collection_id": folder.collection_id,
        "parent_folder_id": folder.parent_folder_id,
        "owner_id": folder.owner_id,
        "created_at": folder.created_at.isoformat(),
        "children": [_folder_to_tree(child) for child in (folder.children or [])],
    }


@router.post("/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: FolderCreateRequest,
    user: UserContext = Depends(require_permission("document:write")),
    db: AsyncSession = Depends(get_db),
):
    """Create a folder inside a collection. User must have collection access."""
    from src.models.document import Collection

    # Verify the collection exists and user has access
    col_result = await db.execute(
        select(Collection).where(Collection.id == body.collection_id)
    )
    collection = col_result.scalar_one_or_none()
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
        )
    if collection.owner_id != user.user_id and not collection.is_public and "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to collection"
        )

    # Validate parent folder if provided
    if body.parent_folder_id is not None:
        parent_result = await db.execute(
            select(DocumentFolder).where(
                and_(
                    DocumentFolder.id == body.parent_folder_id,
                    DocumentFolder.collection_id == body.collection_id,
                )
            )
        )
        if parent_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent folder not found in this collection",
            )

    folder = DocumentFolder(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        collection_id=body.collection_id,
        parent_folder_id=body.parent_folder_id,
        owner_id=user.user_id,
    )
    db.add(folder)
    await db.commit()
    await db.refresh(folder)

    return {
        "id": folder.id,
        "name": folder.name,
        "collection_id": folder.collection_id,
        "parent_folder_id": folder.parent_folder_id,
        "owner_id": folder.owner_id,
        "created_at": folder.created_at,
    }


@router.get("/folders")
async def list_folders(
    collection_id: str = Query(..., description="Collection ID to list folders for"),
    user: UserContext = Depends(require_permission("document:read")),
    db: AsyncSession = Depends(get_db),
):
    """Return all folders in a collection as a nested tree structure."""
    from src.models.document import Collection

    # Verify collection access
    col_result = await db.execute(
        select(Collection).where(Collection.id == collection_id)
    )
    collection = col_result.scalar_one_or_none()
    if collection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found"
        )
    if collection.owner_id != user.user_id and not collection.is_public and "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to collection"
        )

    # Fetch all root-level folders (parent_folder_id IS NULL) — children are
    # eagerly loaded via the relationship's selectin loading.
    result = await db.execute(
        select(DocumentFolder).where(
            and_(
                DocumentFolder.collection_id == collection_id,
                DocumentFolder.parent_folder_id.is_(None),
            )
        ).order_by(DocumentFolder.name)
    )
    root_folders = result.scalars().all()

    return [_folder_to_tree(f) for f in root_folders]


@router.patch("/folders/{folder_id}", status_code=status.HTTP_200_OK)
async def update_folder(
    folder_id: str,
    body: FolderRenameRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename or move a folder (update parent_folder_id). Owner or admin only."""
    result = await db.execute(
        select(DocumentFolder).where(DocumentFolder.id == folder_id)
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found"
        )
    if folder.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can update folder"
        )

    if body.name is not None:
        folder.name = body.name.strip()

    if body.parent_folder_id is not None:
        # Prevent cycles: new parent must not be a descendant of this folder
        if body.parent_folder_id == folder_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A folder cannot be its own parent",
            )
        parent_result = await db.execute(
            select(DocumentFolder).where(
                and_(
                    DocumentFolder.id == body.parent_folder_id,
                    DocumentFolder.collection_id == folder.collection_id,
                )
            )
        )
        if parent_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target parent folder not found in this collection",
            )
        folder.parent_folder_id = body.parent_folder_id
    elif "parent_folder_id" in body.model_fields_set and body.parent_folder_id is None:
        # Explicitly set to null — move to collection root
        folder.parent_folder_id = None

    await db.commit()
    await db.refresh(folder)

    return {
        "id": folder.id,
        "name": folder.name,
        "collection_id": folder.collection_id,
        "parent_folder_id": folder.parent_folder_id,
        "owner_id": folder.owner_id,
        "created_at": folder.created_at,
    }


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a folder. Documents inside are moved to the parent folder (or null).
    Owner or admin only.
    """
    result = await db.execute(
        select(DocumentFolder).where(DocumentFolder.id == folder_id)
    )
    folder = result.scalar_one_or_none()
    if folder is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found"
        )
    if folder.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can delete folder"
        )

    parent_folder_id = folder.parent_folder_id

    # Move all direct child documents to the parent folder (or null)
    docs_result = await db.execute(
        select(Document).where(Document.folder_id == folder_id)
    )
    docs_in_folder = docs_result.scalars().all()
    for doc in docs_in_folder:
        doc.folder_id = parent_folder_id

    # Move child sub-folders to the parent folder (or null) before deletion
    # so they are not cascade-deleted
    child_folders_result = await db.execute(
        select(DocumentFolder).where(DocumentFolder.parent_folder_id == folder_id)
    )
    child_folders = child_folders_result.scalars().all()
    for child in child_folders:
        child.parent_folder_id = parent_folder_id

    await db.flush()
    await db.delete(folder)
    await db.commit()


@router.patch("/{document_id}/folder", status_code=status.HTTP_200_OK)
async def move_document_to_folder(
    document_id: str,
    body: FolderMoveDocumentRequest,
    user: UserContext = Depends(get_current_user),
    document_repo: DocumentRepository = Depends(get_document_repo),
    db: AsyncSession = Depends(get_db),
):
    """Move a document to a different folder (must be in the same collection).

    Set folder_id to null to remove the document from any folder.
    Owner or admin only.
    """
    doc = await document_repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    if doc.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can move document"
        )

    if body.folder_id is not None:
        # Validate folder exists and belongs to the same collection
        folder_result = await db.execute(
            select(DocumentFolder).where(DocumentFolder.id == body.folder_id)
        )
        target_folder = folder_result.scalar_one_or_none()
        if target_folder is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Target folder not found"
            )
        if doc.collection_id and target_folder.collection_id != doc.collection_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Folder and document must be in the same collection",
            )

    doc.folder_id = body.folder_id
    await db.commit()
    await db.refresh(doc)
    return _doc_to_response(doc)
