"""LlamaIndex-powered ingestion pipeline.

Provides semantic chunking (SemanticSplitterNodeParser) + metadata enrichment
(TitleExtractor, KeywordExtractor) as an opt-in replacement for the manual
RecursiveChunker / HierarchicalChunker.

Activation
----------
    pip install llama-index llama-index-embeddings-ollama

    In .env:
        LLAMAINDEX_PIPELINE_ENABLED=true

When llama-index is not installed the module loads fine but `get_pipeline()`
returns None and the caller falls back to the existing chunker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Optional LlamaIndex imports ───────────────────────────────────────────────
try:
    from llama_index.core import Document as LIDocument
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.node_parser import SemanticSplitterNodeParser
    from llama_index.core.extractors import KeywordExtractor

    _LLAMAINDEX_AVAILABLE = True
except ImportError:
    _LLAMAINDEX_AVAILABLE = False

try:
    from llama_index.embeddings.ollama import OllamaEmbedding

    _OLLAMA_EMBED_AVAILABLE = True
except ImportError:
    _OLLAMA_EMBED_AVAILABLE = False


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class PipelineChunk:
    """Mirrors the interface of `Chunk` from the existing chunkers."""

    text: str
    metadata: dict = field(default_factory=dict)
    token_count: int = 0


# ── Pipeline class ────────────────────────────────────────────────────────────

class LlamaIndexIngestionPipeline:
    """Wraps LlamaIndex IngestionPipeline for semantic chunking + keyword extraction.

    The pipeline applies, in order:
        1. SemanticSplitterNodeParser — splits on semantic boundaries detected by
           the embedding model rather than fixed character counts.
        2. KeywordExtractor — appends a ``keywords`` field to each node's metadata
           (10 keywords per chunk) for BM25 / tag search enrichment.
    """

    def __init__(
        self,
        embed_model_name: str = "nomic-embed-text",
        ollama_base_url: str = "http://localhost:11434",
        buffer_size: int = 1,
        breakpoint_percentile: int = 95,
    ) -> None:
        if not _LLAMAINDEX_AVAILABLE:
            raise ImportError(
                "llama-index is not installed. "
                "Run: pip install llama-index llama-index-embeddings-ollama"
            )

        # Build embedding model used by the semantic splitter
        if _OLLAMA_EMBED_AVAILABLE:
            embed_model = OllamaEmbedding(
                model_name=embed_model_name,
                base_url=ollama_base_url,
            )
        else:
            # Fallback to whatever the global LlamaIndex settings have
            from llama_index.core import Settings

            embed_model = Settings.embed_model

        splitter = SemanticSplitterNodeParser(
            embed_model=embed_model,
            buffer_size=buffer_size,
            breakpoint_percentile_threshold=breakpoint_percentile,
        )

        self._pipeline = IngestionPipeline(
            transformations=[
                splitter,
                KeywordExtractor(keywords=10),
            ]
        )

    def chunk(self, text: str, metadata: dict) -> list[PipelineChunk]:
        """Run the LlamaIndex pipeline and return a list of PipelineChunk objects.

        Args:
            text:     Full document text.
            metadata: Base metadata dict to attach to every chunk
                      (document_id, owner_id, visibility, etc.).

        Returns:
            List of PipelineChunk instances compatible with the rest of the
            ingestion pipeline (_embed_and_store expects .text and .metadata).
        """
        li_doc = LIDocument(text=text, metadata=metadata)

        nodes = self._pipeline.run(documents=[li_doc], show_progress=False)

        chunks: list[PipelineChunk] = []
        for i, node in enumerate(nodes):
            node_meta = dict(metadata)
            node_meta["chunk_index"] = i
            # Merge node-level metadata (keywords, etc.) — LlamaIndex adds these
            # via KeywordExtractor and stores them in node.metadata.
            node_meta.update(node.metadata or {})
            content = node.get_content()
            chunks.append(
                PipelineChunk(
                    text=content,
                    metadata=node_meta,
                    token_count=len(content.split()),
                )
            )

        return chunks


# ── Factory ───────────────────────────────────────────────────────────────────

def get_pipeline(settings) -> Optional[LlamaIndexIngestionPipeline]:
    """Return a configured pipeline or None when disabled / unavailable.

    Called once during IngestionService construction so the pipeline is
    reused across document ingestions.
    """
    if not getattr(settings, "LLAMAINDEX_PIPELINE_ENABLED", False):
        return None

    if not _LLAMAINDEX_AVAILABLE:
        logger.warning(
            "LLAMAINDEX_PIPELINE_ENABLED=true but llama-index is not installed. "
            "Run: pip install llama-index llama-index-embeddings-ollama  "
            "Falling back to default chunker."
        )
        return None

    try:
        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        embed_model = getattr(settings, "EMBEDDING_MODEL", "nomic-embed-text")
        pipeline = LlamaIndexIngestionPipeline(
            embed_model_name=embed_model,
            ollama_base_url=ollama_url,
        )
        logger.info(
            "LlamaIndexIngestionPipeline ready — embed model: %s", embed_model
        )
        return pipeline
    except Exception as exc:
        logger.warning(
            "Failed to initialize LlamaIndexIngestionPipeline (non-fatal): %s  "
            "Falling back to default chunker.",
            exc,
        )
        return None
