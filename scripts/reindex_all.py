"""Re-index all documents into ChromaDB (vector) and Neo4j (knowledge graph).

Fetches every document that has a stored file from the database and calls
reingest_document(), which deletes the old vectors / BM25 / KG data and
rebuilds them from the original file using the current chunking + embedding
settings.

Usage (inside the backend container):
    docker compose exec backend python scripts/reindex_all.py

Options:
    ready            Only reindex documents with status "ready"
    embedding_failed Only reindex documents with status "embedding_failed"
    all              Reindex all documents with a stored file (default)
    --dry-run        Print what would be reindexed without doing anything

Examples:
    docker compose exec backend python scripts/reindex_all.py
    docker compose exec backend python scripts/reindex_all.py embedding_failed
    docker compose exec backend python scripts/reindex_all.py --dry-run
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from src.config import get_settings
from src.db.session import get_async_engine, get_session_factory
from src.llm import get_llm
from src.models.document import Document
from src.repositories.audit_repository import AuditRepository
from src.repositories.document_repository import DocumentRepository
from src.services.embedding_service import OllamaEmbeddingService
from src.services.ingestion_service import IngestionService
from src.services.knowledge_graph_service import get_kg_service
from src.vectorstore import get_vector_store


async def reindex_all(status_filter: str = "all", dry_run: bool = False) -> None:
    settings = get_settings()
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    # ── fetch document list ───────────────────────────────────────────────────
    async with factory() as session:
        stmt = select(Document).where(Document.file_path.isnot(None))
        if status_filter != "all":
            stmt = stmt.where(Document.status == status_filter)
        result = await session.execute(stmt)
        docs = list(result.scalars().all())
        # collect plain values before session closes
        doc_ids = [(d.id, d.filename, d.status) for d in docs]

    if not doc_ids:
        print(f"No documents found (filter: status={status_filter}).")
        return

    print(f"Found {len(doc_ids)} document(s) to reindex (filter: status={status_filter})")

    if dry_run:
        for doc_id, filename, status in doc_ids:
            print(f"  [dry-run] {filename}  id={doc_id}  status={status}")
        return

    # ── build ingestion service ───────────────────────────────────────────────
    # ingest_document() and reingest_document() always open their own fresh DB
    # sessions, so the repos passed here are placeholders only.
    async with factory() as session:
        dummy_doc_repo = DocumentRepository(session)
        dummy_audit_repo = AuditRepository(session)

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

        ingestion_svc = IngestionService(
            document_repo=dummy_doc_repo,
            audit_repo=dummy_audit_repo,
            embedding_service=embedding_svc,
            vector_store=vector_store,
            settings=settings,
            llm=llm,
            kg_service=kg_svc,
        )

        # ── reindex each document ─────────────────────────────────────────────
        ok = failed = 0
        for i, (doc_id, filename, status) in enumerate(doc_ids, 1):
            print(f"  [{i}/{len(doc_ids)}] {filename} (id={doc_id}) … ", end="", flush=True)
            try:
                await ingestion_svc.reingest_document(doc_id)
                print("done")
                ok += 1
            except Exception as exc:
                print(f"FAILED — {exc}")
                failed += 1

    print(f"\nReindex complete: {ok} succeeded, {failed} failed.")


if __name__ == "__main__":
    status_filter = "all"
    dry_run = False
    for arg in sys.argv[1:]:
        if arg == "--dry-run":
            dry_run = True
        elif arg in ("ready", "embedding_failed", "all"):
            status_filter = arg

    asyncio.run(reindex_all(status_filter=status_filter, dry_run=dry_run))
