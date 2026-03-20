"""
TDD Test Cases — Embedding Service (src/services/embedding_service.py)

Tests for embedding provider abstraction.
"""
import pytest


class TestEmbedText:
    """embedding_service.embed_text()"""

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_returns_float_list(self, embedding_service):
        pass

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_returns_correct_dimensions(self, embedding_service):
        pass

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_empty_string_raises(self, embedding_service):
        pass

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_consistent_output_for_same_input(self, embedding_service):
        pass

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_different_text_produces_different_embeddings(self, embedding_service):
        pass


class TestEmbedBatch:
    """embedding_service.embed_batch()"""

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_batch_returns_list_of_vectors(self, embedding_service):
        pass

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_batch_length_matches_input(self, embedding_service):
        pass

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_batch_empty_list_returns_empty(self, embedding_service):
        pass

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_batch_preserves_order(self, embedding_service):
        pass

    @pytest.mark.skip(reason="Requires running Ollama server")
    def test_batch_with_single_item(self, embedding_service):
        pass
