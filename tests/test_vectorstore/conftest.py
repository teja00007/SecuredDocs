"""Fixtures for vector store tests."""
import pytest
import tempfile
import os

from src.vectorstore.chroma_store import ChromaStore


@pytest.fixture
def chroma_store(tmp_path):
    """Temporary ChromaDB instance for testing."""
    store = ChromaStore(persist_dir=str(tmp_path / "chroma_test"))
    yield store


@pytest.fixture
def sample_chunks():
    """A list of sample chunk dicts for testing."""
    return [
        {
            "chunk_id": f"doc1_chunk_{i}",
            "embedding": [0.1 * i] * 768,
            "text": f"Sample text chunk {i}",
            "document_id": "doc1",
            "filename": "test.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
        }
        for i in range(3)
    ]


@pytest.fixture
async def seeded_chunks(chroma_store, sample_chunks):
    """Chunks pre-inserted into chroma_store."""
    await chroma_store.insert(sample_chunks)
    return sample_chunks


@pytest.fixture
async def mixed_visibility_chunks(chroma_store):
    """Chunks with different visibility levels inserted into chroma_store."""
    chunks = [
        {
            "chunk_id": "pub_chunk_0",
            "embedding": [0.1] * 768,
            "text": "Public document chunk",
            "document_id": "doc_public",
            "filename": "public.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
            "allowed_teams": [],
            "allowed_users": [],
        },
        {
            "chunk_id": "team_chunk_0",
            "embedding": [0.2] * 768,
            "text": "Team document chunk",
            "document_id": "doc_team",
            "filename": "team.pdf",
            "visibility": "team",
            "owner_id": "user2",
            "collection_id": "col1",
            "allowed_teams": ["team1"],
            "allowed_users": [],
        },
        {
            "chunk_id": "conf_chunk_0",
            "embedding": [0.3] * 768,
            "text": "Confidential document chunk",
            "document_id": "doc_conf",
            "filename": "conf.pdf",
            "visibility": "confidential",
            "owner_id": "user3",
            "collection_id": "col1",
            "allowed_teams": [],
            "allowed_users": ["user4"],
        },
    ]
    await chroma_store.insert(chunks)
    return chunks


@pytest.fixture
async def multi_doc_chunks(chroma_store):
    """Chunks from two different documents inserted into chroma_store."""
    chunks = [
        {
            "chunk_id": f"docA_chunk_{i}",
            "embedding": [0.1 * (i + 1)] * 768,
            "text": f"Doc A chunk {i}",
            "document_id": "docA",
            "filename": "a.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
        }
        for i in range(2)
    ] + [
        {
            "chunk_id": f"docB_chunk_{i}",
            "embedding": [0.5 * (i + 1)] * 768,
            "text": f"Doc B chunk {i}",
            "document_id": "docB",
            "filename": "b.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
        }
        for i in range(2)
    ]
    await chroma_store.insert(chunks)
    return chunks


@pytest.fixture
async def multi_collection_chunks(chroma_store):
    """Chunks from two different collections inserted into chroma_store."""
    chunks = [
        {
            "chunk_id": f"col1_chunk_{i}",
            "embedding": [0.1 * (i + 1)] * 768,
            "text": f"Collection 1 chunk {i}",
            "document_id": "doc_col1",
            "filename": "col1.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col1",
        }
        for i in range(2)
    ] + [
        {
            "chunk_id": f"col2_chunk_{i}",
            "embedding": [0.5 * (i + 1)] * 768,
            "text": f"Collection 2 chunk {i}",
            "document_id": "doc_col2",
            "filename": "col2.pdf",
            "visibility": "public",
            "owner_id": "user1",
            "collection_id": "col2",
        }
        for i in range(2)
    ]
    await chroma_store.insert(chunks)
    return chunks
