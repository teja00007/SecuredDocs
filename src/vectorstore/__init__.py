"""Vector store factory."""

from src.core.interfaces import IVectorStore
from src.config import Settings


def get_vector_store(settings: Settings) -> IVectorStore:
    """Instantiate the configured vector store."""
    store_type = settings.VECTOR_STORE_TYPE.lower()

    if store_type == "chroma":
        from src.vectorstore.chroma_store import ChromaStore
        return ChromaStore(persist_dir=settings.CHROMA_PERSIST_DIR)
    elif store_type == "qdrant":
        from src.vectorstore.qdrant_store import QdrantStore
        return QdrantStore(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            dimensions=settings.EMBEDDING_DIMENSIONS,
            sparse_enabled=getattr(settings, "QDRANT_SPARSE_ENABLED", False),
        )
    elif store_type == "pgvector":
        from src.vectorstore.pgvector_store import PgVectorStore
        return PgVectorStore(
            connection_string=settings.DATABASE_URL,
            dimensions=settings.EMBEDDING_DIMENSIONS,
        )
    else:
        raise ValueError(f"Unknown vector store type: {store_type!r}. Use 'chroma', 'qdrant', or 'pgvector'.")


__all__ = ["get_vector_store", "IVectorStore"]
