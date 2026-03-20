"""
TDD Test Cases — Exceptions Module (src/core/exceptions.py)

Tests for custom exception hierarchy.
"""
import pytest

from src.core.exceptions import (
    RAGException,
    AuthenticationError,
    AuthorizationError,
    DocumentNotFoundError,
    TeamNotFoundError,
    UnsupportedFileTypeError,
    IngestionError,
    EmbeddingError,
    VectorStoreError,
    LLMError,
    ConsistencyError,
)


class TestExceptionHierarchy:
    """Verify all custom exceptions inherit from RAGException."""

    def test_rag_exception_is_base(self):
        """RAGException should be a subclass of Exception."""
        assert issubclass(RAGException, Exception)
        exc = RAGException("test")
        assert isinstance(exc, Exception)

    def test_authentication_error_is_rag_exception(self):
        """AuthenticationError should be a subclass of RAGException."""
        assert issubclass(AuthenticationError, RAGException)

    def test_authorization_error_is_rag_exception(self):
        """AuthorizationError should be a subclass of RAGException."""
        assert issubclass(AuthorizationError, RAGException)

    def test_document_not_found_is_rag_exception(self):
        """DocumentNotFoundError should be a subclass of RAGException."""
        assert issubclass(DocumentNotFoundError, RAGException)

    def test_team_not_found_is_rag_exception(self):
        """TeamNotFoundError should be a subclass of RAGException."""
        assert issubclass(TeamNotFoundError, RAGException)

    def test_unsupported_file_type_is_rag_exception(self):
        """UnsupportedFileTypeError should be a subclass of RAGException."""
        assert issubclass(UnsupportedFileTypeError, RAGException)

    def test_exceptions_carry_message(self):
        """All exceptions should accept and store a message string."""
        exc = RAGException("something went wrong")
        assert exc.message == "something went wrong"
        assert str(exc) == "something went wrong"

        auth_exc = AuthenticationError("bad token")
        assert auth_exc.message == "bad token"

    def test_exceptions_carry_detail_dict(self):
        """Exceptions should optionally accept a detail dict for structured error info."""
        exc = RAGException("err", detail={"code": "E001", "field": "email"})
        assert exc.detail == {"code": "E001", "field": "email"}

        exc_no_detail = RAGException("err")
        assert exc_no_detail.detail == {}
