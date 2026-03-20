"""Nexus MCP Server — exposes the knowledge base as AI agent tools.

Runs as a standalone subprocess via stdio transport.

Tools exposed:
  - search_knowledge_base  : RAG retrieval returning chunks with text + metadata
  - list_documents         : list documents from DB (optional collection filter)
  - get_document_summary   : document metadata + summary if available
  - list_collections       : all collections

Usage:
  python -m src.mcp.server
  mcp run src/mcp/server.py
"""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


# ── Lazy infrastructure builders ──────────────────────────────────────────────

def _build_settings():
    """Load settings without the FastAPI lru_cache (standalone process)."""
    from src.config import Settings
    return Settings()


def _build_engine(settings):
    from src.db.session import get_async_engine
    return get_async_engine(settings.DATABASE_URL)


def _build_session_factory(engine):
    from src.db.session import get_session_factory
    return get_session_factory(engine)


def _build_retrieval_service(settings):
    from src.services.embedding_service import OllamaEmbeddingService
    from src.services.retrieval_service import RetrievalService
    from src.vectorstore import get_vector_store

    embedding_svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    vector_store = get_vector_store(settings)
    return RetrievalService(
        embedding_service=embedding_svc,
        vector_store=vector_store,
        hybrid_enabled=getattr(settings, "HYBRID_SEARCH_ENABLED", False),
        score_threshold=getattr(settings, "RETRIEVAL_SCORE_THRESHOLD", 0.0),
    )


# Module-level singletons (lazily initialised)
_settings = None
_engine = None
_session_factory = None
_retrieval_svc = None


def _get_infra():
    """Return (settings, session_factory, retrieval_svc) — lazily initialised."""
    global _settings, _engine, _session_factory, _retrieval_svc
    if _settings is None:
        _settings = _build_settings()
        _engine = _build_engine(_settings)
        _session_factory = _build_session_factory(_engine)
        _retrieval_svc = _build_retrieval_service(_settings)
    return _settings, _session_factory, _retrieval_svc


# ── Tool implementations ───────────────────────────────────────────────────────

async def _tool_search_knowledge_base(
    query: str,
    collection_id: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Call Nexus retrieval service and return chunks with text + source metadata."""
    _settings, _sf, retrieval_svc = _get_infra()

    chunks = await retrieval_svc.retrieve(
        query_text=query,
        filter={},  # MCP agent has full access — no RBAC filtering
        collection_id=collection_id,
        top_k=max(1, min(top_k, 20)),
    )

    return [
        {
            "text": c.text,
            "score": round(c.score, 4),
            "chunk_id": c.chunk_id,
            "document_id": c.document_id,
            "filename": c.metadata.get("filename", "unknown"),
            "collection_id": c.metadata.get("collection_id"),
            "chunk_index": c.metadata.get("chunk_index"),
        }
        for c in chunks
    ]


async def _tool_list_documents(
    collection_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return document list from DB, optionally filtered by collection."""
    _settings, session_factory, _rs = _get_infra()

    from sqlalchemy import select
    from src.models.document import Document

    limit = max(1, min(limit, 200))

    async with session_factory() as session:
        stmt = select(Document).where(Document.status == "ready")
        if collection_id:
            stmt = stmt.where(Document.collection_id == collection_id)
        stmt = stmt.order_by(Document.created_at.desc()).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "collection_id": doc.collection_id,
            "chunk_count": doc.chunk_count,
            "status": doc.status,
            "created_at": doc.created_at.isoformat(),
            "tags": doc.tags,
        }
        for doc in rows
    ]


async def _tool_get_document_summary(document_id: str) -> dict:
    """Return document metadata and a summary derived from its top chunks."""
    _settings, session_factory, retrieval_svc = _get_infra()

    from sqlalchemy import select
    from src.models.document import Document

    async with session_factory() as session:
        result = await session.execute(
            select(Document).where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()

    if doc is None:
        return {"error": f"Document '{document_id}' not found"}

    # Pull a representative set of chunks to build a text-based summary
    chunks = await retrieval_svc.retrieve(
        query_text=f"main topics and key points of {doc.filename}",
        filter={"document_id": {"$eq": document_id}},
        collection_id=doc.collection_id,
        top_k=6,
    )

    summary: str | None = None
    if chunks:
        # Simple extractive summary — first 300 chars from each top chunk
        excerpts = "\n\n".join(c.text[:300] for c in chunks[:4])
        summary = excerpts  # Callers can pass this to their own LLM if desired

    return {
        "document_id": document_id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "collection_id": doc.collection_id,
        "chunk_count": doc.chunk_count,
        "status": doc.status,
        "tags": doc.tags,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
        "summary": summary,
    }


async def _tool_list_collections() -> list[dict]:
    """Return all collections from DB."""
    _settings, session_factory, _rs = _get_infra()

    from sqlalchemy import select, func
    from src.models.document import Collection, Document

    async with session_factory() as session:
        count_subq = (
            select(
                Document.collection_id,
                func.count(Document.id).label("cnt"),
            )
            .where(Document.status == "ready")
            .group_by(Document.collection_id)
        ).subquery()

        stmt = (
            select(
                Collection.id,
                Collection.name,
                Collection.description,
                Collection.is_public,
                Collection.created_at,
                count_subq.c.cnt,
            )
            .outerjoin(count_subq, count_subq.c.collection_id == Collection.id)
            .order_by(Collection.name)
        )
        rows = (await session.execute(stmt)).all()

    return [
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "is_public": row.is_public,
            "document_count": row.cnt or 0,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


# ── MCP Server ────────────────────────────────────────────────────────────────

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types as mcp_types

    _server = Server("nexus-knowledge-base")

    @_server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name="search_knowledge_base",
                description=(
                    "Search the Nexus knowledge base using semantic retrieval. "
                    "Returns a list of relevant document chunks with text and source metadata."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The question or search query",
                        },
                        "collection_id": {
                            "type": "string",
                            "description": "Optional collection UUID to restrict the search scope",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "Number of chunks to retrieve (1–20, default 5)",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            ),
            mcp_types.Tool(
                name="list_documents",
                description=(
                    "List documents available in the Nexus knowledge base. "
                    "Optionally filter by collection and cap the result count."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "collection_id": {
                            "type": "string",
                            "description": "Filter by collection UUID",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of documents to return (default 20)",
                            "default": 20,
                        },
                    },
                },
            ),
            mcp_types.Tool(
                name="get_document_summary",
                description=(
                    "Return metadata and an extractive summary for a specific document."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "document_id": {
                            "type": "string",
                            "description": "UUID of the document",
                        }
                    },
                    "required": ["document_id"],
                },
            ),
            mcp_types.Tool(
                name="list_collections",
                description="Return all document collections with their document counts.",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]

    @_server.call_tool()
    async def _call_tool(
        name: str, arguments: dict
    ) -> list[mcp_types.TextContent]:
        try:
            if name == "search_knowledge_base":
                result = await _tool_search_knowledge_base(
                    query=arguments["query"],
                    collection_id=arguments.get("collection_id"),
                    top_k=int(arguments.get("top_k", 5)),
                )
            elif name == "list_documents":
                result = await _tool_list_documents(
                    collection_id=arguments.get("collection_id"),
                    limit=int(arguments.get("limit", 20)),
                )
            elif name == "get_document_summary":
                result = await _tool_get_document_summary(
                    document_id=arguments["document_id"]
                )
            elif name == "list_collections":
                result = await _tool_list_collections()
            else:
                result = {"error": f"Unknown tool: {name}"}
        except Exception as exc:
            logger.error("MCP tool %r failed: %s", name, exc, exc_info=True)
            result = {"error": str(exc)}

        return [mcp_types.TextContent(type="text", text=json.dumps(result, indent=2))]

    async def main() -> None:
        """Run the Nexus MCP server over stdio."""
        async with stdio_server() as (read_stream, write_stream):
            init_options = _server.create_initialization_options()
            await _server.run(read_stream, write_stream, init_options)

except ImportError:
    # mcp package not installed — provide a helpful stub
    logger.warning(
        "mcp package not installed. Install with: pip install 'mcp>=1.0.0'\n"
        "The Nexus MCP server will not be available until mcp is installed."
    )

    async def main() -> None:  # type: ignore[misc]
        raise RuntimeError(
            "mcp package is not installed. Run: pip install 'mcp>=1.0.0'"
        )


if __name__ == "__main__":
    asyncio.run(main())
