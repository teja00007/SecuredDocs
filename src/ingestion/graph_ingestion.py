"""LlamaIndex PropertyGraphIndex → Neo4j ingestion pipeline.

Replaces the manual EntityExtractor + KnowledgeGraphService.store_chunk_graph()
with LlamaIndex's built-in property graph construction which performs
richer entity/relationship extraction using a structured LLM prompt.

Activation
----------
    pip install llama-index llama-index-graph-stores-neo4j

    In .env:
        LLAMAINDEX_GRAPH_ENABLED=true
        NEO4J_URI=bolt://localhost:7687
        NEO4J_USER=neo4j
        NEO4J_PASSWORD=neo4jpassword

When the required packages are absent the module loads but ``get_graph_ingestion()``
returns None and the caller falls back to the existing EntityExtractor path.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Optional LlamaIndex core ──────────────────────────────────────────────────
try:
    from llama_index.core import Document as LIDocument
    from llama_index.core.indices import PropertyGraphIndex

    _LLAMAINDEX_AVAILABLE = True
except ImportError:
    _LLAMAINDEX_AVAILABLE = False

# ── Optional Neo4j graph store ────────────────────────────────────────────────
try:
    from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

    _NEO4J_GRAPH_AVAILABLE = True
except ImportError:
    _NEO4J_GRAPH_AVAILABLE = False


class LlamaIndexGraphIngestion:
    """Ingests document chunks into Neo4j via LlamaIndex PropertyGraphIndex.

    LlamaIndex uses an LLM-driven implicit entity extractor and stores the
    resulting property graph in Neo4j through ``Neo4jPropertyGraphStore``.
    This provides richer, schema-free entity/relationship coverage compared to
    the hand-written Cypher MERGE approach in KnowledgeGraphService.

    Usage
    -----
    ::

        gi = LlamaIndexGraphIngestion(uri, user, password)
        gi.ingest_chunks(chunks, document_id="doc-123", filename="report.pdf")
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
    ) -> None:
        if not _LLAMAINDEX_AVAILABLE:
            raise ImportError(
                "llama-index is not installed. Run: pip install llama-index"
            )
        if not _NEO4J_GRAPH_AVAILABLE:
            raise ImportError(
                "llama-index-graph-stores-neo4j is not installed. "
                "Run: pip install llama-index-graph-stores-neo4j"
            )

        self._graph_store = Neo4jPropertyGraphStore(
            username=neo4j_user,
            password=neo4j_password,
            url=neo4j_uri,
        )

    def ingest_chunks(
        self,
        chunks: list,
        document_id: str,
        filename: str = "",
    ) -> None:
        """Build a PropertyGraphIndex from chunks and persist to Neo4j.

        Args:
            chunks:      List of objects with ``.text`` and ``.metadata``
                         attributes (compatible with both ``Chunk`` from the
                         existing chunkers and ``PipelineChunk`` from pipeline.py).
            document_id: Parent document ID — tagged onto every LlamaIndex Document.
            filename:    Human-readable filename for display in the graph.
        """
        if not chunks:
            return

        documents: list[LIDocument] = []
        for i, chunk in enumerate(chunks):
            meta = dict(getattr(chunk, "metadata", {}))
            meta["document_id"] = document_id
            meta["filename"] = filename
            meta["chunk_index"] = i
            documents.append(LIDocument(text=chunk.text, metadata=meta))

        try:
            PropertyGraphIndex.from_documents(
                documents,
                property_graph_store=self._graph_store,
                show_progress=False,
            )
            logger.info(
                "PropertyGraphIndex: ingested %d chunks for document %s into Neo4j",
                len(chunks),
                document_id,
            )
        except Exception as exc:
            logger.warning(
                "PropertyGraphIndex ingestion failed for document %s (non-fatal): %s",
                document_id,
                exc,
            )


# ── Factory ───────────────────────────────────────────────────────────────────

def get_graph_ingestion(settings) -> Optional[LlamaIndexGraphIngestion]:
    """Return a configured graph ingestion instance or None when disabled / unavailable."""
    if not getattr(settings, "LLAMAINDEX_GRAPH_ENABLED", False):
        return None

    if not _LLAMAINDEX_AVAILABLE or not _NEO4J_GRAPH_AVAILABLE:
        logger.warning(
            "LLAMAINDEX_GRAPH_ENABLED=true but required packages are missing. "
            "Run: pip install llama-index llama-index-graph-stores-neo4j  "
            "Falling back to manual EntityExtractor."
        )
        return None

    try:
        neo4j_uri = getattr(settings, "NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = getattr(settings, "NEO4J_USER", "neo4j")
        neo4j_password = getattr(settings, "NEO4J_PASSWORD", "neo4jpassword")

        gi = LlamaIndexGraphIngestion(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
        )
        logger.info("LlamaIndexGraphIngestion initialized — Neo4j %s", neo4j_uri)
        return gi
    except Exception as exc:
        logger.warning(
            "Failed to initialize LlamaIndexGraphIngestion (non-fatal): %s  "
            "Falling back to manual EntityExtractor.",
            exc,
        )
        return None
