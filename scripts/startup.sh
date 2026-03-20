#!/bin/sh
set -e

echo "==> [1/9] Creating database tables and running column migrations..."
python scripts/init_db.py

echo "==> [2/9] Seeding Company One — TechCorp Inc. (structure only, skip embeddings)..."
python scripts/seed_company_one.py --skip-embeddings

echo "==> [3/9] Seeding Company Two — HealthFlow Systems (structure only, skip embeddings)..."
python scripts/seed_company_two.py --skip-embeddings

echo "==> [4/9] Pulling Ollama models (phi4-mini + nomic-embed-text)..."
python scripts/pull_models.py || echo "  Model pull failed (non-fatal) — embedding will run once models are available"

echo "==> [5/9] Ingesting documents — embedding all un-embedded documents..."
# Re-run seeds without --skip-embeddings to embed any un-embedded documents
python - <<'PYEOF' || echo "  Ingestion step encountered errors (non-fatal)"
import asyncio, sys
sys.path.insert(0, "/app")
from src.config import get_settings

async def run():
    from src.db.session import get_async_engine, get_session_factory
    from src.repositories.document_repository import DocumentRepository
    from src.repositories.audit_repository import AuditRepository
    from src.services.embedding_service import OllamaEmbeddingService
    from src.services.ingestion_service import IngestionService
    from src.vectorstore import get_vector_store
    from src.models.document import Document, DocumentTeamAccess
    from sqlalchemy import select

    settings = get_settings()
    # Disable slow LLM features during bulk startup ingestion.
    # KG extraction, auto-tagging and contextual retrieval all call the LLM
    # synchronously per chunk; on CPU this makes each document take minutes.
    # These features remain enabled at runtime for documents uploaded via the API.
    settings.CONTEXTUAL_RETRIEVAL_ENABLED = False
    settings.AUTO_TAGGING_ENABLED = False
    settings.KNOWLEDGE_GRAPH_ENABLED = False

    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    embedding_svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    vector_store = get_vector_store(settings)
    needs_llm = False

    async with factory() as session:
        result = await session.execute(
            select(Document).where(
                Document.status == "ready",
                Document.chunk_count == 0,
                Document.file_path.is_not(None),
            )
        )
        docs = list(result.scalars().all())
        doc_team_ids = {}
        for doc in docs:
            ta = await session.execute(
                select(DocumentTeamAccess.team_id).where(
                    DocumentTeamAccess.document_id == doc.id
                )
            )
            doc_team_ids[doc.id] = [r[0] for r in ta.all()]

    if not docs:
        print("  [ingest] No pending documents — all already embedded.")
        await engine.dispose()
        return

    print(f"  [ingest] Embedding {len(docs)} documents ...")
    success = failed = 0
    for i, doc in enumerate(docs, 1):
        async with factory() as session:
            svc = IngestionService(
                document_repo=DocumentRepository(session),
                audit_repo=AuditRepository(session),
                embedding_service=embedding_svc,
                vector_store=vector_store,
                settings=settings,
                llm=None,
                kg_service=None,
            )
            try:
                await svc.ingest_document(
                    document_id=doc.id,
                    file_path=doc.file_path,
                    file_type=doc.file_type,
                    visibility_metadata={
                        "owner_id": doc.owner_id,
                        "filename": doc.filename,
                        "visibility": doc.visibility,
                        "chunking_strategy": doc.chunking_strategy or "hierarchical",
                        "collection_id": doc.collection_id or "",
                        "allowed_teams": doc_team_ids.get(doc.id, []),
                        "allowed_users": [],
                    },
                )
                await session.commit()
                success += 1
                print(f"  [{i:>3}/{len(docs)}] ✓  {doc.filename}")
            except Exception as e:
                await session.rollback()
                failed += 1
                print(f"  [{i:>3}/{len(docs)}] ✗  {doc.filename}  ({e})")

    await engine.dispose()
    print(f"  [ingest] Done — {success} ok, {failed} failed")

asyncio.run(run())
PYEOF

echo "==> [6/9] Ingesting documents into Neo4j knowledge graph..."
python scripts/seed_neo4j.py || echo "  Neo4j ingestion step failed (non-fatal)"

echo "==> [7/9] Ensuring Neo4j full-text index on Entity nodes..."
python - <<'PYEOF'
import asyncio, os
async def ensure():
    try:
        from neo4j import AsyncGraphDatabase
        url = os.environ.get("NEO4J_URI", os.environ.get("NEO4J_URL", "bolt://neo4j:7687"))
        driver = AsyncGraphDatabase.driver(url, auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "neo4jpassword"),
        ))
        async with driver.session() as s:
            await s.run("CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS FOR (n:Entity) ON EACH [n.name, n.type]")
            await s.run("CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)")
            await s.run("CREATE INDEX document_id IF NOT EXISTS FOR (d:Document) ON (d.id)")
        await driver.close()
        print("  Neo4j indexes OK.")
    except Exception as e:
        print(f"  Neo4j index step failed (non-fatal): {e}")
asyncio.run(ensure())
PYEOF

echo "==> [8/9] ChromaDB migration — skipped (Qdrant is the primary vector store)..."

echo "==> [9/9] Rebuilding BM25 index from Qdrant-stored chunks..."
python scripts/rebuild_bm25.py || echo "  BM25 rebuild failed (non-fatal)"

echo ""
echo "========================================================"
echo "  Nexus startup complete — starting uvicorn..."
echo "========================================================"
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
