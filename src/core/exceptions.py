"""Custom exception hierarchy for the RAG system."""


class RAGException(Exception):
    """Base exception for all RAG system errors."""

    def __init__(self, message: str = "", detail: dict | None = None):
        self.message = message
        self.detail = detail or {}
        super().__init__(self.message)


class AuthenticationError(RAGException):
    """Invalid credentials, expired token, or malformed token."""
    pass


class AuthorizationError(RAGException):
    """Insufficient permissions or document access denied."""
    pass


class DocumentNotFoundError(RAGException):
    """Requested document does not exist."""
    pass


class CollectionNotFoundError(RAGException):
    """Requested collection does not exist."""
    pass


class TeamNotFoundError(RAGException):
    """Requested team/DL does not exist."""
    pass


class UnsupportedFileTypeError(RAGException):
    """File type is not supported for ingestion."""
    pass


class PHIViolationError(RAGException):
    """Document contains Protected Health Information (PHI) — upload blocked."""
    pass


class IngestionError(RAGException):
    """Parsing or chunking failure during document ingestion."""
    pass


class EmbeddingError(IngestionError):
    """Embedding service failure (retries exhausted)."""
    pass


class VectorStoreError(RAGException):
    """Embedding storage or retrieval failure."""
    pass


class LLMError(RAGException):
    """LLM generation failure."""
    pass


class ConsistencyError(RAGException):
    """Database and vector store are out of sync."""
    pass
