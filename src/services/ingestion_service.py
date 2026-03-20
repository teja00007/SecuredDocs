"""Document ingestion service — parse → chunk → embed → store.

After successful ingestion two optional side-effects are triggered:
  1. Outbound webhook delivery for "document.ingested" event
     (Feature 4 — wire WebhookService here)
  2. AI auto-tagging via AutoTagService
     (Feature 5 — enabled via config AUTO_TAGGING_ENABLED=true)

Advanced ingestion features (all opt-in via config flags):
  - Contextual retrieval (CONTEXTUAL_RETRIEVAL_ENABLED):
      Before embedding each chunk, call the LLM to generate 1-2 sentences of
      context describing where the chunk fits in the document, then prepend
      that context to the chunk text before embedding.
  - Parent-child hierarchical chunking (chunking_strategy="hierarchical"):
      Chunks carry parent_text in metadata.  The query pipeline returns the
      parent text to the LLM instead of the narrow child text.
"""

import asyncio
import logging
import time
import uuid

from src.core.exceptions import IngestionError, EmbeddingError
from src.core.interfaces import IEmbeddingService, IVectorStore
from src.repositories.document_repository import DocumentRepository
from src.repositories.audit_repository import AuditRepository

logger = logging.getLogger(__name__)


def _deterministic_chunk_id(document_id: str, chunk_index: int) -> str:
    """Return a deterministic UUID5 for (document_id, chunk_index).

    Same document at same position always produces the same ID, making
    Qdrant upsert idempotent — safe to re-run ingestion without duplicates.
    """
    name = f"{document_id}:{chunk_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


class IngestionService:
    def __init__(
        self,
        document_repo: DocumentRepository,
        audit_repo: AuditRepository,
        embedding_service: IEmbeddingService,
        vector_store: IVectorStore,
        settings,
        llm=None,
        kg_service=None,  # KnowledgeGraphService | None
        llamaindex_pipeline=None,   # LlamaIndexIngestionPipeline | None
        llamaindex_graph=None,      # LlamaIndexGraphIngestion | None
    ) -> None:
        self._doc_repo = document_repo
        self._audit_repo = audit_repo
        self._embedding = embedding_service
        self._vector_store = vector_store
        self._settings = settings
        self._llm = llm  # Optional ILLM — required for CONTEXTUAL_RETRIEVAL_ENABLED and KG
        self._kg_service = kg_service
        self._llamaindex_pipeline = llamaindex_pipeline
        self._llamaindex_graph = llamaindex_graph

    async def ingest_document(
        self,
        document_id: str,
        file_path: str,
        file_type: str,
        visibility_metadata: dict,
    ) -> None:
        """Run full ingestion pipeline.

        Always opens a *fresh* DB session so this is safe to call from
        FastAPI BackgroundTasks (the request session is already closed by then).
        """
        from src.db.session import get_async_engine, get_session_factory
        from src.repositories.document_repository import DocumentRepository
        from src.repositories.audit_repository import AuditRepository

        engine = get_async_engine(self._settings.DATABASE_URL)
        factory = get_session_factory(engine)

        start_ms = int(time.time() * 1000)

        async with factory() as session:
            doc_repo   = DocumentRepository(session)
            audit_repo = AuditRepository(session)

            await doc_repo.set_status(document_id, "processing")
            await session.commit()

            try:
                # 1. Parse document
                parse_result = await asyncio.to_thread(
                    self._parse_document, file_path, file_type
                )

                # 2. Select chunking strategy
                # If LlamaIndex pipeline is active, use semantic chunking;
                # otherwise fall back to the configured chunking strategy.
                if self._llamaindex_pipeline is not None:
                    chunks = await asyncio.to_thread(
                        self._llamaindex_pipeline.chunk,
                        parse_result.text,
                        {
                            "document_id": document_id,
                            "filename": visibility_metadata.get("filename", ""),
                            "owner_id": visibility_metadata.get("owner_id", ""),
                            "collection_id": visibility_metadata.get("collection_id", ""),
                            "company_id": visibility_metadata.get("company_id", ""),
                            "visibility": visibility_metadata.get("visibility", "public"),
                            "allowed_teams": visibility_metadata.get("allowed_teams", []),
                            "allowed_users": visibility_metadata.get("allowed_users", []),
                        },
                    )
                else:
                    strategy = (
                        visibility_metadata.get("chunking_strategy")
                        or getattr(self._settings, "DEFAULT_CHUNKING_STRATEGY", None)
                    )
                    chunks = await asyncio.to_thread(
                        self._chunk_document,
                        parse_result,
                        file_type,
                        strategy,
                        document_id,
                        visibility_metadata,
                    )

                if not chunks:
                    raise IngestionError("No chunks produced — document may be empty")

                # 3. Embed and store in batches
                # Pass the full document text so contextual retrieval can prepend
                # LLM-generated context to each chunk before embedding (opt-in).
                full_text = parse_result.text if parse_result else ""
                await self._embed_and_store(chunks, document_id, full_document_text=full_text)

                # 3b. Knowledge Graph extraction (non-fatal)
                await self._extract_and_store_graph(
                    chunks=chunks,
                    document_id=document_id,
                    filename=visibility_metadata.get("filename", ""),
                )

                # 4. Update document status
                await doc_repo.set_chunk_count(document_id, len(chunks))
                await doc_repo.set_status(document_id, "ready")

                duration = int(time.time() * 1000) - start_ms
                await audit_repo.log_ingestion(
                    document_id=document_id,
                    user_id=visibility_metadata.get("owner_id", ""),
                    status="success",
                    duration_ms=duration,
                )
                await session.commit()

                # 5. Trigger "document.ingested" webhook (Feature 4 — non-fatal)
                try:
                    from src.services.webhook_service import WebhookService
                    await WebhookService().trigger(
                        event_type="document.ingested",
                        payload={
                            "document_id": document_id,
                            "filename": visibility_metadata.get("filename", ""),
                            "owner_id": visibility_metadata.get("owner_id", ""),
                            "chunk_count": len(chunks),
                            "duration_ms": duration,
                        },
                        db=session,
                    )
                    await session.commit()
                except Exception as _wh_exc:
                    logger.warning("Webhook delivery failed (non-fatal): %s", _wh_exc)

                # 6. AI auto-tagging (Feature 5 — opt-in, non-fatal)
                try:
                    if self._settings.AUTO_TAGGING_ENABLED:
                        text_sample = parse_result.text[:2000] if parse_result and parse_result.text else ""
                        if text_sample:
                            from src.services.auto_tag_service import AutoTagService
                            from src.llm import get_llm
                            llm_instance = get_llm(self._settings)
                            tags = await AutoTagService().generate_tags(
                                document_id=document_id,
                                filename=visibility_metadata.get("filename", ""),
                                text_sample=text_sample,
                                llm=llm_instance,
                            )
                            if tags:
                                from src.models.document import DocumentTag
                                from sqlalchemy import select as _select
                                for tag_val in tags:
                                    existing_tag = await session.execute(
                                        _select(DocumentTag).where(
                                            DocumentTag.document_id == document_id,
                                            DocumentTag.tag == tag_val,
                                        )
                                    )
                                    if existing_tag.scalar_one_or_none() is None:
                                        session.add(DocumentTag(document_id=document_id, tag=tag_val))
                                await session.commit()
                                logger.info(
                                    "AutoTagService: added %d tag(s) to document %s: %s",
                                    len(tags),
                                    document_id,
                                    tags,
                                )
                except Exception as _tag_exc:
                    logger.warning(
                        "Auto-tagging failed for document %s (non-fatal): %s",
                        document_id,
                        _tag_exc,
                    )

            except EmbeddingError as e:
                logger.error("Embedding failed for document %s: %s", document_id, e)
                await session.rollback()
                await doc_repo.set_status(document_id, "embedding_failed")
                await audit_repo.log_ingestion(
                    document_id=document_id,
                    user_id=visibility_metadata.get("owner_id", ""),
                    status="embedding_failed",
                    error_message=str(e),
                )
                await session.commit()
            except Exception as e:
                logger.error("Ingestion failed for document %s: %s", document_id, e)
                await session.rollback()
                await doc_repo.set_status(document_id, "failed")
                await audit_repo.log_ingestion(
                    document_id=document_id,
                    user_id=visibility_metadata.get("owner_id", ""),
                    status="failed",
                    error_message=str(e),
                )
                await session.commit()
                raise

    def _parse_document(self, file_path: str, file_type: str):
        from src.ingestion.parser_factory import get_parser
        parser = get_parser(file_type)
        return parser.parse(file_path)

    def _chunk_document(
        self,
        parse_result,
        file_type: str,
        strategy: str | None,
        document_id: str,
        visibility_metadata: dict,
    ):
        from src.ingestion.parser_factory import get_chunker
        from src.ingestion.chunkers.hierarchical_chunker import HierarchicalChunker

        meta = {
            "document_id": document_id,
            "filename": visibility_metadata.get("filename", ""),
            "owner_id": visibility_metadata.get("owner_id", ""),
            "collection_id": visibility_metadata.get("collection_id", ""),
            "company_id": visibility_metadata.get("company_id", ""),
            "visibility": visibility_metadata.get("visibility", "public"),
            "allowed_teams": visibility_metadata.get("allowed_teams", []),
            "allowed_users": visibility_metadata.get("allowed_users", []),
            "sections": parse_result.sections,
        }
        meta.update(parse_result.metadata)

        # When the strategy is "hierarchical", instantiate with configured sizes
        if strategy == "hierarchical":
            parent_size = getattr(self._settings, "HIERARCHICAL_PARENT_SIZE", 1500)
            child_size = getattr(self._settings, "HIERARCHICAL_CHILD_SIZE", 200)
            chunker = HierarchicalChunker(
                parent_size=parent_size,
                child_size=child_size,
            )
        else:
            chunker = get_chunker(file_type, override=strategy)

        return chunker.chunk(parse_result.text, meta)

    # ------------------------------------------------------------------
    # Contextual retrieval — prepend LLM-generated context to chunk text
    # ------------------------------------------------------------------

    _CONTEXTUAL_PROMPT = (
        "Here is a document:\n<document>{doc_text}</document>\n\n"
        "Here is a chunk from this document:\n<chunk>{chunk_text}</chunk>\n\n"
        "Please provide a brief 1-2 sentence context explaining where this chunk "
        "fits in the document and what it is about.\n"
        "Context:"
    )

    async def _generate_chunk_context(
        self, full_document_text: str, chunk_text: str
    ) -> str:
        """Call the LLM to generate 1-2 sentence context for a single chunk.

        Returns the context string, or an empty string on failure.
        """
        if self._llm is None:
            return ""
        prompt = self._CONTEXTUAL_PROMPT.format(
            doc_text=full_document_text[:4000],  # truncate to avoid token overflow
            chunk_text=chunk_text,
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            result = await self._llm.generate(
                messages=messages, temperature=0.0, max_tokens=128
            )
            return result.content.strip()
        except Exception as exc:
            logger.warning("Contextual retrieval LLM call failed (non-fatal): %s", exc)
            return ""

    async def _embed_and_store(self, chunks, document_id: str, full_document_text: str = "") -> None:
        from src.services.bm25_service import BM25Service
        batch_size = 10

        # --- Contextual retrieval: prepend LLM context to each chunk before embedding ---
        contextual_enabled = getattr(
            self._settings, "CONTEXTUAL_RETRIEVAL_ENABLED", False
        )
        if contextual_enabled and self._llm is not None and full_document_text:
            logger.info(
                "Contextual retrieval enabled — generating context for %d chunks (doc %s)",
                len(chunks),
                document_id,
            )
            enhanced_texts: list[str] = []
            for chunk in chunks:
                ctx = await self._generate_chunk_context(full_document_text, chunk.text)
                if ctx:
                    enhanced_texts.append(f"{ctx}\n\n{chunk.text}")
                else:
                    enhanced_texts.append(chunk.text)
            texts = enhanced_texts
        else:
            texts = [c.text for c in chunks]

        embeddings = await self._embedding.embed_batch(texts)

        chunk_dicts: list[dict] = []
        bm25_chunks: list[dict] = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            chunk_id = _deterministic_chunk_id(document_id, i)
            chunk_dict = {
                "chunk_id": chunk_id,
                "embedding": emb,
                # Store the original chunk text in the vector store so that
                # source citations shown to users are the clean document text,
                # not the LLM-generated context prefix.
                "text": chunk.text,
            }
            chunk_dict.update(chunk.metadata)
            chunk_dicts.append(chunk_dict)

            # Prepare BM25 entry (no embedding needed).
            # Use the contextual text (texts[i]) so that BM25 keyword search
            # also benefits from the LLM-generated context — e.g. document title,
            # date, or topic summary that may not appear verbatim in the raw chunk.
            # Only include JSON-serializable scalar values in metadata.
            bm25_meta: dict = {}
            for k, v in chunk.metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    bm25_meta[k] = v
                elif v is None:
                    bm25_meta[k] = ""
                elif isinstance(v, list) and all(isinstance(x, str) for x in v):
                    bm25_meta[k] = v
            bm25_chunks.append({
                "id": chunk_id,
                "text": texts[i],
                "metadata": bm25_meta,
            })

        # Insert into vector store in batches
        for start in range(0, len(chunk_dicts), batch_size):
            batch = chunk_dicts[start: start + batch_size]
            await self._vector_store.insert(batch)

        # Index into BM25 (runs in a thread to keep event loop free)
        import asyncio as _asyncio
        bm25_svc = BM25Service()
        await _asyncio.to_thread(bm25_svc.add_chunks, bm25_chunks)

    async def _extract_and_store_graph(
        self,
        chunks,
        document_id: str,
        filename: str = "",
    ) -> None:
        """Extract entities/relationships from chunks and store in Neo4j.

        If LlamaIndex graph ingestion is available, uses PropertyGraphIndex
        (richer extraction). Otherwise falls back to the manual EntityExtractor.

        Failures are logged but never propagate — KG is non-fatal.
        """
        kg_enabled = getattr(self._settings, "KNOWLEDGE_GRAPH_ENABLED", False)
        if not kg_enabled:
            return

        # ── LlamaIndex PropertyGraphIndex path (preferred) ─────────────────
        if self._llamaindex_graph is not None:
            try:
                await asyncio.to_thread(
                    self._llamaindex_graph.ingest_chunks,
                    chunks,
                    document_id,
                    filename,
                )
            except Exception as exc:
                logger.warning(
                    "LlamaIndex graph ingestion failed for doc %s (non-fatal): %s",
                    document_id, exc,
                )
            return  # done — skip manual extractor

        # ── Manual EntityExtractor path (fallback) ─────────────────────────
        if self._kg_service is None or self._llm is None:
            return

        from src.services.entity_extractor import EntityExtractor
        extractor = EntityExtractor(self._llm)

        logger.info(
            "Knowledge Graph extraction: processing %d chunks for document %s",
            len(chunks),
            document_id,
        )
        # Extract from every other chunk to balance coverage vs LLM cost;
        # adjacent chunks share enough context that skipping every second is safe.
        sampled = chunks[::2] if len(chunks) > 4 else chunks
        for i, chunk in enumerate(sampled):
            chunk_id = f"{document_id}_{i * 2}"
            try:
                result = await extractor.extract(chunk.text)
                if result["entities"] or result["relations"]:
                    await self._kg_service.store_chunk_graph(
                        entities=result["entities"],
                        relations=result["relations"],
                        document_id=document_id,
                        chunk_id=chunk_id,
                        filename=filename,
                    )
            except Exception as exc:
                logger.warning(
                    "KG extraction failed for chunk %s (non-fatal): %s", chunk_id, exc
                )

    async def _get_doc_fresh(self, document_id: str):
        """Fetch a document record using a fresh DB session (safe for background tasks)."""
        from src.db.session import get_async_engine, get_session_factory
        engine = get_async_engine(self._settings.DATABASE_URL)
        factory = get_session_factory(engine)
        async with factory() as session:
            return await DocumentRepository(session).get_by_id(document_id)

    async def retry_failed_embeddings(self, document_id: str) -> None:
        doc = await self._get_doc_fresh(document_id)
        if not doc or doc.status != "embedding_failed":
            return
        if not doc.file_path:
            logger.error("Cannot retry — no file_path stored for document %s", document_id)
            return

        visibility_metadata = {
            "owner_id": doc.owner_id,
            "filename": doc.filename,
            "visibility": doc.visibility,
            "chunking_strategy": doc.chunking_strategy,
            "collection_id": doc.collection_id,
        }
        await self.ingest_document(document_id, doc.file_path, doc.file_type, visibility_metadata)

    async def reingest_document(self, document_id: str) -> None:
        doc = await self._get_doc_fresh(document_id)
        if not doc or not doc.file_path:
            raise IngestionError(f"Document {document_id} not found or has no file path")

        # Delete old vector store data, BM25 index, and KG graph for this document
        await self._vector_store.delete_by_document_id(document_id)
        from src.services.bm25_service import BM25Service
        import asyncio as _asyncio
        bm25_svc = BM25Service()
        await _asyncio.to_thread(bm25_svc.remove_document, document_id)
        if self._kg_service is not None:
            try:
                await self._kg_service.delete_document(document_id)
            except Exception as exc:
                logger.warning("KG delete for doc %s failed (non-fatal): %s", document_id, exc)

        visibility_metadata = {
            "owner_id": doc.owner_id,
            "filename": doc.filename,
            "visibility": doc.visibility,
            "chunking_strategy": doc.chunking_strategy,
            "collection_id": doc.collection_id,
        }
        await self.ingest_document(document_id, doc.file_path, doc.file_type, visibility_metadata)
