"""Fixtures for service tests."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import timedelta

from src.models import User, Role, Team, TeamMembership, Collection, Document, user_roles
from src.core.security import hash_password, create_refresh_token
from src.repositories.team_repository import TeamRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.audit_repository import AuditRepository
from src.services.team_service import TeamService
from src.services.document_service import DocumentService
from src.services.retrieval_service import RetrievalService
from src.services.generation_service import GenerationService
from src.services.ingestion_service import IngestionService
from src.services.rag_service import RAGService
from src.services.embedding_service import OllamaEmbeddingService


# ---------------------------------------------------------------------------
# MOCK INFRASTRUCTURE
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    store.insert = AsyncMock()
    store.delete_by_document_id = AsyncMock(return_value=0)
    store.update_metadata = AsyncMock()
    store.count = AsyncMock(return_value=0)
    return store


@pytest.fixture
def mock_embedding_service():
    svc = AsyncMock()
    svc.embed_text = AsyncMock(return_value=[0.1] * 768)
    svc.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return svc


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=MagicMock(content="Mock answer"))
    return llm


@pytest.fixture
def failing_vector_store():
    store = AsyncMock()
    store.search = AsyncMock(side_effect=Exception("Vector store error"))
    store.insert = AsyncMock(side_effect=Exception("Vector store error"))
    store.update_metadata = AsyncMock(side_effect=Exception("Vector store error"))
    return store


@pytest.fixture
def failing_llm():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("LLM error"))
    return llm


@pytest.fixture
def failing_store():
    store = AsyncMock()
    store.search = AsyncMock(side_effect=Exception("Vector store unavailable"))
    store.insert = AsyncMock(side_effect=Exception("Vector store unavailable"))
    store.update_metadata = AsyncMock(side_effect=Exception("Vector store unavailable"))
    store.delete_by_document_id = AsyncMock(side_effect=Exception("Vector store unavailable"))
    return store


@pytest.fixture
def empty_store(mock_vector_store):
    return mock_vector_store


@pytest.fixture
def seeded_store(mock_vector_store):
    from src.core.interfaces import ChunkResult
    mock_vector_store.search = AsyncMock(return_value=[
        ChunkResult(chunk_id="c1", text="Relevant chunk", document_id="doc1",
                    metadata={"filename": "test.pdf"}, score=0.9),
    ])
    return mock_vector_store


@pytest.fixture
def multi_collection_store(mock_vector_store):
    return mock_vector_store


@pytest.fixture
def flaky_vector_store():
    store = AsyncMock()
    call_count = {"n": 0}

    async def flaky_search(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise Exception("Temporary failure")
        return []

    store.search = flaky_search
    store.insert = AsyncMock()
    store.update_metadata = AsyncMock()
    return store


@pytest.fixture
def flaky_embedding():
    svc = AsyncMock()
    call_count = {"n": 0}

    async def flaky_embed(text):
        call_count["n"] += 1
        if call_count["n"] <= 2:
            raise Exception("Temporary embedding failure")
        return [0.1] * 768

    svc.embed_text = flaky_embed
    svc.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return svc


@pytest.fixture
def always_failing_embedding():
    svc = AsyncMock()
    svc.embed_text = AsyncMock(side_effect=Exception("Embedding always fails"))
    svc.embed_batch = AsyncMock(side_effect=Exception("Embedding always fails"))
    return svc


@pytest.fixture
def partial_embedding():
    svc = AsyncMock()
    call_count = {"n": 0}

    async def partial_embed(texts):
        return [[0.1] * 768 for _ in texts]

    svc.embed_batch = partial_embed
    svc.embed_text = AsyncMock(return_value=[0.1] * 768)
    return svc


@pytest.fixture
def slow_embedding():
    svc = AsyncMock()
    svc.embed_text = AsyncMock(return_value=[0.1] * 768)
    svc.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return svc


@pytest.fixture
def recovered_embedding():
    svc = AsyncMock()
    svc.embed_text = AsyncMock(return_value=[0.1] * 768)
    svc.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    return svc


# ---------------------------------------------------------------------------
# USER FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
async def non_creator_user(db_session):
    user = User(username="noncreator", email="noncreator@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def non_owner_user(db_session):
    user = User(username="nonowner", email="nonowner@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def user_with_teams(db_session):
    user = User(username="teamuser", email="teamuser@example.com",
                hashed_password=hash_password("pass1234"))
    team = Team(name="User's Team", description="", created_by="system")
    db_session.add_all([user, team])
    await db_session.flush()
    db_session.add(TeamMembership(team_id=team.id, user_id=user.id))
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def mock_user(db_session):
    user = User(username="mockuser", email="mockuser@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# DOCUMENT / FILE FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_pdf(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 12 Tf 100 700 Td (Hello World) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000360 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
441
%%EOF"""
    pdf_path.write_bytes(pdf_content)
    return str(pdf_path)


@pytest.fixture
def sample_pdf_path(sample_pdf):
    return sample_pdf


@pytest.fixture
def empty_pdf(tmp_path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"%PDF-1.4\n%%EOF")
    return str(p)


@pytest.fixture
def corrupted_pdf(tmp_path):
    p = tmp_path / "corrupt.pdf"
    p.write_bytes(b"Not a valid PDF content at all!!!")
    return str(p)


@pytest.fixture
def unsupported_file(tmp_path):
    p = tmp_path / "file.xyz"
    p.write_bytes(b"unsupported content")
    return str(p)


@pytest.fixture
async def public_doc(db_session, registered_user):
    doc = Document(filename="public.pdf", file_type="application/pdf",
                   visibility="public", status="ready", owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.fixture
async def team_doc(db_session, registered_user):
    from src.models import DocumentTeamAccess
    team = Team(name="SvcTeam", description="", created_by=registered_user.id)
    db_session.add(team)
    await db_session.flush()
    doc = Document(filename="team.pdf", file_type="application/pdf",
                   visibility="team", status="ready", owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.fixture
async def confidential_doc(db_session, registered_user):
    doc = Document(filename="conf.pdf", file_type="application/pdf",
                   visibility="confidential", status="ready", owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.fixture
async def previously_ingested_doc(db_session, registered_user):
    doc = Document(filename="ingested.pdf", file_type="application/pdf",
                   visibility="public", status="ready", owner_id=registered_user.id,
                   file_path="/tmp/ingested.pdf", chunk_count=3)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.fixture
def many_large_chunks():
    return [{"chunk_id": f"c{i}", "text": "x" * 500, "embedding": [0.1] * 768,
             "document_id": "doc1", "filename": "large.pdf",
             "visibility": "public", "owner_id": "u1"} for i in range(20)]


@pytest.fixture
def sample_chunks():
    return [{"chunk_id": f"sc_{i}", "text": f"Chunk {i}", "embedding": [0.1 * i] * 768,
             "document_id": "doc1", "filename": "test.pdf",
             "visibility": "public", "owner_id": "u1"} for i in range(3)]


@pytest.fixture
def chat_history():
    return [{"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"}]


# ---------------------------------------------------------------------------
# TOKEN FIXTURES
# ---------------------------------------------------------------------------

_SECRET = "dev-secret-change-me-in-production-min-32-chars"


@pytest.fixture
def expired_refresh(registered_user):
    return create_refresh_token(
        user_id=registered_user.id,
        secret_key=_SECRET,
        expires_delta=timedelta(seconds=-1),
    )


# ---------------------------------------------------------------------------
# SERVICE FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def team_service(db_session, mock_vector_store):
    return TeamService(
        team_repo=TeamRepository(db_session),
        document_repo=DocumentRepository(db_session),
        audit_repo=AuditRepository(db_session),
        vector_store=mock_vector_store,
    )


@pytest.fixture
def doc_service(db_session, mock_vector_store):
    return DocumentService(
        document_repo=DocumentRepository(db_session),
        audit_repo=AuditRepository(db_session),
        vector_store=mock_vector_store,
    )


@pytest.fixture
def retrieval_service(mock_embedding_service, mock_vector_store):
    return RetrievalService(
        embedding_service=mock_embedding_service,
        vector_store=mock_vector_store,
    )


@pytest.fixture
def generation_service(mock_llm):
    return GenerationService(llm=mock_llm)


@pytest.fixture
def embedding_service():
    return OllamaEmbeddingService(
        base_url="http://localhost:11434",
        model="nomic-embed-text",
        dimensions=768,
    )


@pytest.fixture
def ingestion_service(db_session, mock_embedding_service, mock_vector_store):
    from src.config import get_settings
    return IngestionService(
        document_repo=DocumentRepository(db_session),
        audit_repo=AuditRepository(db_session),
        embedding_service=mock_embedding_service,
        vector_store=mock_vector_store,
        settings=get_settings(),
    )


@pytest.fixture
def rag_service(db_session, mock_embedding_service, mock_vector_store, mock_llm):
    retrieval = RetrievalService(
        embedding_service=mock_embedding_service,
        vector_store=mock_vector_store,
    )
    generation = GenerationService(llm=mock_llm)
    return RAGService(
        retrieval_service=retrieval,
        generation_service=generation,
        audit_repo=AuditRepository(db_session),
    )
