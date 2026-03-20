"""Seed project documentation as public documents.

Ingests all .md files from the project root so there's real content to query.
Run AFTER the backend has been started at least once (tables must exist) and
AFTER Ollama is running with nomic-embed-text pulled.

  python scripts/seed_documents.py
"""

import asyncio
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
from src.db.session import get_async_engine, get_session_factory, get_async_session
from src.models.document import Document
from src.repositories.document_repository import DocumentRepository
from src.repositories.audit_repository import AuditRepository
from src.repositories.user_repository import UserRepository
from src.services.embedding_service import OllamaEmbeddingService
from src.services.ingestion_service import IngestionService
from src.vectorstore import get_vector_store

# ── files to seed ─────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"

DOCS_TO_SEED = [
    (PROJECT_ROOT / "BUILD.md",                  "RAG System Build Guide"),
    (PROJECT_ROOT / "startapp.md",               "Start App — Accounts & Commands"),
    (PROJECT_ROOT / "FEATURES_ROADMAP.md",       "Features Roadmap"),
    (PROJECT_ROOT / "ENTERPRISE_PROBLEMS_AND_FEATURES.md", "Enterprise Problems & Features"),
    (PROJECT_ROOT / "frontend" / "specs.md",     "Frontend Specification"),
]


async def seed() -> None:
    settings = get_settings()
    engine   = get_async_engine(settings.DATABASE_URL)
    factory  = get_session_factory(engine)

    embedding_svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    vector_store = get_vector_store(settings)

    async for session in get_async_session(factory):
        user_repo = UserRepository(session)
        doc_repo  = DocumentRepository(session)
        audit_repo = AuditRepository(session)

        # Use admin as owner
        admin = await user_repo.get_by_username("admin")
        if not admin:
            print("  [error] admin user not found — run seed_users.py first")
            return

        ingestion_svc = IngestionService(
            document_repo=doc_repo,
            audit_repo=audit_repo,
            embedding_service=embedding_svc,
            vector_store=vector_store,
            settings=settings,
        )

        for file_path, label in DOCS_TO_SEED:
            if not file_path.exists():
                print(f"  [skip] not found: {file_path.name}")
                continue

            # Check if already seeded (by filename)
            existing = await doc_repo.get_by_filename_and_owner(file_path.name, admin.id)
            if existing:
                print(f"  [skip] already seeded: {file_path.name}")
                continue

            # Copy to upload dir
            doc_id   = str(uuid.uuid4())
            dest_dir = UPLOAD_DIR / doc_id
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest     = dest_dir / file_path.name
            shutil.copy2(file_path, dest)

            # Create DB record
            doc = Document(
                id=doc_id,
                filename=file_path.name,
                file_type=".md",
                file_size=file_path.stat().st_size,
                visibility="public",
                collection_id=None,
                owner_id=admin.id,
                chunking_strategy=None,
                file_path=str(dest),
                status="pending",
            )
            await doc_repo.create(doc)
            await session.commit()

            # Ingest (parse → chunk → embed → store)
            visibility_meta = {
                "owner_id": admin.id,
                "filename": file_path.name,
                "visibility": "public",
                "chunking_strategy": None,
                "collection_id": "",
                "allowed_teams": "",
                "allowed_users": "",
            }

            print(f"  [ingesting] {file_path.name} ({label}) …")
            try:
                await ingestion_svc.ingest_document(
                    document_id=doc_id,
                    file_path=str(dest),
                    file_type=".md",
                    visibility_metadata=visibility_meta,
                )
                await session.commit()
                print(f"  [done] {file_path.name}")
            except Exception as e:
                print(f"  [failed] {file_path.name}: {e}")
                await session.rollback()

    await engine.dispose()
    print("\nDocument seeding complete.")
    print("Try asking: 'How do I start the app?' or 'What compliance rules are supported?'")


if __name__ == "__main__":
    asyncio.run(seed())
