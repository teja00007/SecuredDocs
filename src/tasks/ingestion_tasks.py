"""Celery tasks for document ingestion."""

import asyncio
import logging

from src.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_ingestion(document_id: str, file_path: str, file_type: str, visibility_metadata: dict) -> None:
    """Build service instances without FastAPI DI and run the ingestion pipeline."""
    from src.config import Settings
    from src.db.session import get_async_engine, get_session_factory
    from src.repositories.document_repository import DocumentRepository
    from src.repositories.audit_repository import AuditRepository
    from src.services.embedding_service import OllamaEmbeddingService
    from src.services.ingestion_service import IngestionService
    from src.vectorstore import get_vector_store
    from src.llm import get_llm
    from src.services.knowledge_graph_service import get_kg_service

    settings = Settings()

    embedding_svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
        query_prefix=getattr(settings, "EMBEDDING_QUERY_PREFIX", ""),
        doc_prefix=getattr(settings, "EMBEDDING_DOC_PREFIX", ""),
    )
    vector_store = get_vector_store(settings)
    llm = get_llm(settings)
    kg_svc = get_kg_service(settings)

    # LlamaIndex optional integrations
    llamaindex_pipeline = None
    if getattr(settings, "LLAMAINDEX_PIPELINE_ENABLED", False):
        from src.ingestion.pipeline import get_pipeline
        llamaindex_pipeline = get_pipeline(settings)

    llamaindex_graph = None
    if getattr(settings, "LLAMAINDEX_GRAPH_ENABLED", False):
        from src.ingestion.graph_ingestion import get_graph_ingestion
        llamaindex_graph = get_graph_ingestion(settings)

    # Repositories are created inside IngestionService.ingest_document using
    # a fresh session — we just need stub repos to satisfy the constructor.
    # The real per-operation repos are created inside the async method itself.
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    needs_llm = (
        getattr(settings, "CONTEXTUAL_RETRIEVAL_ENABLED", False)
        or getattr(settings, "KNOWLEDGE_GRAPH_ENABLED", False)
        or getattr(settings, "AUTO_TAGGING_ENABLED", False)
    )

    async def _async_run():
        async with factory() as session:
            doc_repo = DocumentRepository(session)
            audit_repo = AuditRepository(session)
            svc = IngestionService(
                document_repo=doc_repo,
                audit_repo=audit_repo,
                embedding_service=embedding_svc,
                vector_store=vector_store,
                settings=settings,
                llm=llm if needs_llm else None,
                kg_service=kg_svc,
                llamaindex_pipeline=llamaindex_pipeline,
                llamaindex_graph=llamaindex_graph,
            )
            await svc.ingest_document(
                document_id=document_id,
                file_path=file_path,
                file_type=file_type,
                visibility_metadata=visibility_metadata,
            )
        await engine.dispose()

    asyncio.run(_async_run())


async def _mark_failed(document_id: str) -> None:
    """Update document status to 'failed' using a fresh DB session."""
    from src.config import Settings
    from src.db.session import get_async_engine, get_session_factory
    from src.repositories.document_repository import DocumentRepository

    settings = Settings()
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)
    try:
        async with factory() as session:
            repo = DocumentRepository(session)
            await repo.set_status(document_id, "failed")
            await session.commit()
    finally:
        await engine.dispose()


@celery_app.task(bind=True, name="src.tasks.ingestion_tasks.ingest_document_task")
def ingest_document_task(
    self,
    document_id: str,
    file_path: str,
    file_type: str,
    visibility_metadata: dict,
):
    """Celery task: run the full document ingestion pipeline.

    Creates its own DB session and service instances — does not rely on
    FastAPI's dependency injection system.

    On unrecoverable failure the document status is set to 'failed' in the DB.
    On success IngestionService.ingest_document already sets status to 'ready'.
    """
    logger.info(
        "Starting Celery ingestion task for document %s (file_type=%s)",
        document_id,
        file_type,
    )
    try:
        _run_ingestion(document_id, file_path, file_type, visibility_metadata)
        logger.info("Ingestion task completed successfully for document %s", document_id)
    except Exception as exc:
        logger.error(
            "Ingestion task failed for document %s: %s",
            document_id,
            exc,
            exc_info=True,
        )
        # Best-effort status update — if this also fails, the document stays in
        # 'processing' which is visible in the UI and can be re-triggered.
        try:
            asyncio.run(_mark_failed(document_id))
        except Exception as mark_exc:
            logger.error(
                "Could not mark document %s as failed: %s",
                document_id,
                mark_exc,
            )
        # Re-raise so Celery records the task as FAILURE.
        raise
