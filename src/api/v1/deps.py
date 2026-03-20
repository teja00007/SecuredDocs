"""FastAPI dependency injectors for auth, DB session, and services."""

import hashlib
import json
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings, Settings
from src.core.exceptions import AuthenticationError, AuthorizationError
from src.core.rbac import UserContext, has_permission
from src.core.security import decode_access_token
from src.db.session import get_async_engine, get_session_factory, get_async_session
from src.repositories.user_repository import UserRepository
from src.repositories.team_repository import TeamRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.collection_repository import CollectionRepository
from src.repositories.audit_repository import AuditRepository
from src.services.auth_service import AuthService
from src.services.embedding_service import OllamaEmbeddingService
from src.services.retrieval_service import RetrievalService
from src.services.generation_service import GenerationService
from src.services.ingestion_service import IngestionService
from src.services.document_service import DocumentService
from src.services.team_service import TeamService
from src.services.rag_service import RAGService
from src.services.query_rewriter import get_query_rewriter
from src.services.cross_encoder_reranker import get_reranker, NoOpReRanker
from src.services.knowledge_graph_service import get_kg_service
from src.vectorstore import get_vector_store
from src.llm import get_llm
from src.services.redis_cache import get_redis_client, SemanticCache, EmbeddingCache
from src.services.query_classifier import QueryClassifier
from src.services.parallel_rag_pipeline import ParallelRAGPipeline
from src.services.bm25_service import BM25Service

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# ──────────────────────────────────────────────────────────────
# DB-stored admin setting overrides (for RAG pipeline config)
# ──────────────────────────────────────────────────────────────

_RAG_BOOL_KEYS = {
    "hybrid_search_enabled", "query_rewriting_enabled", "contextual_retrieval_enabled",
    "auto_tagging_enabled", "knowledge_graph_enabled",
}
_RAG_INT_KEYS  = {
    "retrieval_top_k", "query_rewrite_count", "reranker_top_n",
    "chunk_size", "chunk_overlap", "hierarchical_parent_size", "hierarchical_child_size",
}
_RAG_STR_KEYS  = {"query_rewrite_mode", "reranker_type", "default_chunking_strategy"}

def _apply_db_overrides(settings: Settings, overrides: dict[str, str]) -> Settings:
    """Return a new Settings instance with DB admin overrides applied."""
    if not overrides:
        return settings
    data = settings.model_dump()
    key_map = {
        "hybrid_search_enabled": "HYBRID_SEARCH_ENABLED",
        "retrieval_top_k": "RETRIEVAL_TOP_K",
        "query_rewriting_enabled": "QUERY_REWRITING_ENABLED",
        "query_rewrite_mode": "QUERY_REWRITE_MODE",
        "query_rewrite_count": "QUERY_REWRITE_COUNT",
        "reranker_type": "RERANKER_TYPE",
        "reranker_top_n": "RERANKER_TOP_N",
        "contextual_retrieval_enabled": "CONTEXTUAL_RETRIEVAL_ENABLED",
        "chunk_size": "CHUNK_SIZE",
        "chunk_overlap": "CHUNK_OVERLAP",
        "hierarchical_parent_size": "HIERARCHICAL_PARENT_SIZE",
        "hierarchical_child_size": "HIERARCHICAL_CHILD_SIZE",
        "auto_tagging_enabled": "AUTO_TAGGING_ENABLED",
        "knowledge_graph_enabled": "KNOWLEDGE_GRAPH_ENABLED",
        "default_chunking_strategy": "DEFAULT_CHUNKING_STRATEGY",
        "llm_provider": "LLM_PROVIDER",
        "llm_model": "LLM_MODEL",
        "ollama_base_url": "OLLAMA_BASE_URL",
        "max_upload_size_mb": "MAX_UPLOAD_SIZE_MB",
    }
    for db_key, field in key_map.items():
        if db_key not in overrides:
            continue
        raw = overrides[db_key]
        try:
            if db_key in _RAG_BOOL_KEYS:
                data[field] = raw.lower() in ("true", "1", "yes")
            elif db_key in _RAG_INT_KEYS:
                data[field] = int(raw)
            else:
                data[field] = raw
        except Exception:
            pass
    return Settings.model_validate(data)


# ──────────────────────────────────────────────────────────────
# Database session
# ──────────────────────────────────────────────────────────────

async def get_db(
    settings: Settings = Depends(get_settings),
) -> AsyncGenerator[AsyncSession, None]:
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)
    async for session in get_async_session(factory):
        yield session


# ──────────────────────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────────────────────

async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    settings: Settings = Depends(get_settings),
) -> UserContext:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(
            token,
            secret_key=settings.APP_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return UserContext(
        user_id=payload["sub"],
        username=payload.get("username", ""),
        roles=payload.get("roles", []),
        team_ids=payload.get("team_ids", []),
        company_id=payload.get("company_id"),
        is_super_admin=payload.get("is_super_admin", False),
    )


def require_permission(permission: str):
    async def checker(user: UserContext = Depends(get_current_user)) -> UserContext:
        if not has_permission(user.roles, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission}' required",
            )
        return user
    return checker


# ──────────────────────────────────────────────────────────────
# API Key authentication
# ──────────────────────────────────────────────────────────────

def _hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_current_user_or_api_key(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserContext:
    """Authenticate via JWT access token OR an API key (Bearer nxs_...).

    - If the Authorization header carries a JWT, the existing JWT flow is used.
    - If it starts with "nxs_", the token is treated as an API key:
        1. Hash it and look up in api_keys table.
        2. Verify is_active=True and not expired.
        3. Update last_used_at.
        4. Build a UserContext from the owning user.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Detect service account key
    if token.startswith("sa_"):
        from src.models.deny import ServiceAccount

        key_hash = _hash_api_key(token)
        result = await db.execute(
            select(ServiceAccount).where(
                ServiceAccount.hashed_api_key == key_hash,
                ServiceAccount.is_active.is_(True),
            )
        )
        sa = result.scalar_one_or_none()

        if sa is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid service account key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if sa.is_expired():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Service account key has expired",
            )

        # Update last_used_at (best-effort)
        try:
            sa.last_used_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception:
            await db.rollback()

        return UserContext(
            user_id=sa.id,
            username=sa.name,
            roles=sa.get_roles(),
            team_ids=[],
            company_id=sa.company_id,
            is_super_admin=False,
        )

    # Detect API key by prefix
    if token.startswith("nxs_"):
        from src.models.api_key import APIKey

        key_hash = _hash_api_key(token)
        result = await db.execute(
            select(APIKey).where(APIKey.key_hash == key_hash)
        )
        api_key = result.scalar_one_or_none()

        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not api_key.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has been revoked",
            )
        if api_key.expires_at is not None and api_key.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API key has expired",
            )

        # Update last_used_at (best-effort — don't block on commit failure)
        try:
            api_key.last_used_at = datetime.now(timezone.utc)
            await db.commit()
        except Exception:
            await db.rollback()

        # Fetch the owning user to build a proper UserContext
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(api_key.user_id)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="The user associated with this API key is not active",
            )

        return UserContext(
            user_id=user.id,
            username=user.username,
            roles=[r.name for r in user.roles],
            team_ids=[m.team_id for m in user.team_memberships],
            company_id=user.company_id,
            is_super_admin=user.is_super_admin,
        )

    # Fall through to standard JWT flow
    try:
        payload = decode_access_token(
            token,
            secret_key=settings.APP_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )
    return UserContext(
        user_id=payload["sub"],
        username=payload.get("username", ""),
        roles=payload.get("roles", []),
        team_ids=payload.get("team_ids", []),
        company_id=payload.get("company_id"),
        is_super_admin=payload.get("is_super_admin", False),
    )


def require_scope(scope: str):
    """Dependency factory: require a specific API key scope (or full JWT auth).

    When the caller is authenticated via a JWT the scope check is skipped
    (JWT users have full access to the endpoints they're authorised for).
    For API key callers, the key must include the required scope.
    """
    async def checker(
        request: Request,
        token: str | None = Depends(oauth2_scheme),
        db: AsyncSession = Depends(get_db),
        settings: Settings = Depends(get_settings),
    ) -> UserContext:
        user = await get_current_user_or_api_key(
            request=request, token=token, db=db, settings=settings
        )

        # Only enforce scopes for API key callers
        raw_token = token or ""
        if raw_token.startswith("nxs_"):
            from src.models.api_key import APIKey

            key_hash = _hash_api_key(raw_token)
            result = await db.execute(select(APIKey).where(APIKey.key_hash == key_hash))
            api_key = result.scalar_one_or_none()
            if api_key:
                key_scopes: list[str] = json.loads(api_key.scopes or "[]")
                if scope not in key_scopes:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"API key does not have the required scope: '{scope}'",
                    )

        return user

    return checker


# ──────────────────────────────────────────────────────────────
# Repository factories
# ──────────────────────────────────────────────────────────────

def get_user_repo(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)

def get_team_repo(db: AsyncSession = Depends(get_db)) -> TeamRepository:
    return TeamRepository(db)

def get_document_repo(db: AsyncSession = Depends(get_db)) -> DocumentRepository:
    return DocumentRepository(db)

def get_collection_repo(db: AsyncSession = Depends(get_db)) -> CollectionRepository:
    return CollectionRepository(db)

def get_audit_repo(db: AsyncSession = Depends(get_db)) -> AuditRepository:
    return AuditRepository(db)


# ──────────────────────────────────────────────────────────────
# Infrastructure factories (singletons via lru_cache / module-level)
# ──────────────────────────────────────────────────────────────

def get_vector_store_dep(settings: Settings = Depends(get_settings)):
    return get_vector_store(settings)

def get_llm_dep(settings: Settings = Depends(get_settings)):
    return get_llm(settings)

def get_embedding_service(settings: Settings = Depends(get_settings)) -> OllamaEmbeddingService:
    svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
        query_prefix=getattr(settings, "EMBEDDING_QUERY_PREFIX", ""),
        doc_prefix=getattr(settings, "EMBEDDING_DOC_PREFIX", ""),
    )
    # Attach embedding cache when enabled
    if getattr(settings, "EMBEDDING_CACHE_ENABLED", False):
        try:
            cache_url = getattr(settings, "REDIS_CACHE_URL", "redis://localhost:6379/1")
            redis_client = get_redis_client(cache_url)
            svc.set_cache(EmbeddingCache(
                redis_client=redis_client,
                model=settings.EMBEDDING_MODEL,
                ttl_seconds=getattr(settings, "EMBEDDING_CACHE_TTL", 86400),
            ))
        except Exception as _exc:
            import logging as _log
            _log.getLogger(__name__).debug("Embedding cache unavailable (non-fatal): %s", _exc)
    return svc

def get_kg_service_dep(settings: Settings = Depends(get_settings)):
    """Return a KnowledgeGraphService instance or None when KG is disabled."""
    return get_kg_service(settings)


# ──────────────────────────────────────────────────────────────
# Service factories
# ──────────────────────────────────────────────────────────────

def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repo),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(user_repo=user_repo, settings=settings)


def get_generation_service(
    llm = Depends(get_llm_dep),
) -> GenerationService:
    return GenerationService(llm=llm)


async def get_rag_service(
    audit_repo: AuditRepository = Depends(get_audit_repo),
    embedding_svc = Depends(get_embedding_service),
    vector_store = Depends(get_vector_store_dep),
    llm = Depends(get_llm_dep),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    kg_svc = Depends(get_kg_service_dep),
) -> RAGService:
    # Apply DB admin overrides on top of env-based settings
    from src.models.admin_settings import AdminSetting
    result = await db.execute(select(AdminSetting))
    overrides = {row.key: row.value for row in result.scalars().all()}
    eff = _apply_db_overrides(settings, overrides)

    # Use ParallelRAGPipeline when enabled, otherwise fall back to sequential RetrievalService
    parallel_enabled = getattr(eff, "PARALLEL_PIPELINE_ENABLED", True)
    if parallel_enabled:
        from src.services.query_classifier import QueryClassifier
        retrieval = ParallelRAGPipeline(
            embedding_service=embedding_svc,
            vector_store=vector_store,
            bm25_service=BM25Service(),
            kg_service=kg_svc if getattr(eff, "KNOWLEDGE_GRAPH_ENABLED", False) else None,
            classifier=QueryClassifier(),
            hybrid_enabled=getattr(eff, "HYBRID_SEARCH_ENABLED", True),
            score_threshold=getattr(eff, "RETRIEVAL_SCORE_THRESHOLD", 0.0),
        )
    else:
        retrieval = RetrievalService(
            embedding_service=embedding_svc,
            vector_store=vector_store,
            hybrid_enabled=getattr(eff, "HYBRID_SEARCH_ENABLED", False),
            score_threshold=getattr(eff, "RETRIEVAL_SCORE_THRESHOLD", 0.0),
        )
    generation = GenerationService(llm=llm)

    rewriter = get_query_rewriter(eff, llm)
    reranker = get_reranker(eff)
    reranker_top_n = getattr(eff, "RERANKER_TOP_N", 5)
    retrieval_top_k = getattr(eff, "RETRIEVAL_TOP_K", 20)

    # Build semantic cache when enabled
    semantic_cache = None
    if getattr(eff, "SEMANTIC_CACHE_ENABLED", False):
        try:
            cache_url = getattr(eff, "REDIS_CACHE_URL", "redis://localhost:6379/1")
            redis_client = get_redis_client(cache_url)
            semantic_cache = SemanticCache(
                redis_client=redis_client,
                embedding_service=embedding_svc,
                similarity_threshold=getattr(eff, "SEMANTIC_CACHE_SIMILARITY", 0.95),
                ttl_seconds=getattr(eff, "SEMANTIC_CACHE_TTL", 3600),
            )
        except Exception as _exc:
            import logging as _log
            _log.getLogger(__name__).debug("Semantic cache unavailable (non-fatal): %s", _exc)

    return RAGService(
        retrieval_service=retrieval,
        generation_service=generation,
        audit_repo=audit_repo,
        query_rewriter=rewriter,
        reranker=reranker if not isinstance(reranker, NoOpReRanker) else None,
        reranker_top_n=reranker_top_n,
        retrieval_top_k=retrieval_top_k,
        kg_service=kg_svc,
        llm=llm,
        semantic_cache=semantic_cache,
        low_confidence_threshold=getattr(eff, "LOW_CONFIDENCE_THRESHOLD", 0.20),
    )


async def get_ingestion_service(
    document_repo: DocumentRepository = Depends(get_document_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    embedding_svc = Depends(get_embedding_service),
    vector_store = Depends(get_vector_store_dep),
    llm = Depends(get_llm_dep),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    kg_svc = Depends(get_kg_service_dep),
) -> IngestionService:
    from src.models.admin_settings import AdminSetting
    result = await db.execute(select(AdminSetting))
    overrides = {row.key: row.value for row in result.scalars().all()}
    eff = _apply_db_overrides(settings, overrides)

    needs_llm = (
        getattr(eff, "CONTEXTUAL_RETRIEVAL_ENABLED", False)
        or getattr(eff, "KNOWLEDGE_GRAPH_ENABLED", False)
        or getattr(eff, "AUTO_TAGGING_ENABLED", False)
    )
    llm_for_ingestion = llm if needs_llm else None

    # LlamaIndex IngestionPipeline (semantic chunking — optional)
    llamaindex_pipeline = None
    if getattr(eff, "LLAMAINDEX_PIPELINE_ENABLED", False):
        from src.ingestion.pipeline import get_pipeline
        llamaindex_pipeline = get_pipeline(eff)

    # LlamaIndex PropertyGraphIndex → Neo4j (optional, replaces EntityExtractor)
    llamaindex_graph = None
    if getattr(eff, "LLAMAINDEX_GRAPH_ENABLED", False):
        from src.ingestion.graph_ingestion import get_graph_ingestion
        llamaindex_graph = get_graph_ingestion(eff)

    return IngestionService(
        document_repo=document_repo,
        audit_repo=audit_repo,
        embedding_service=embedding_svc,
        vector_store=vector_store,
        settings=eff,
        llm=llm_for_ingestion,
        kg_service=kg_svc,
        llamaindex_pipeline=llamaindex_pipeline,
        llamaindex_graph=llamaindex_graph,
    )


def get_document_service(
    document_repo: DocumentRepository = Depends(get_document_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    vector_store = Depends(get_vector_store_dep),
) -> DocumentService:
    return DocumentService(
        document_repo=document_repo,
        audit_repo=audit_repo,
        vector_store=vector_store,
    )


def get_team_service(
    team_repo: TeamRepository = Depends(get_team_repo),
    document_repo: DocumentRepository = Depends(get_document_repo),
    audit_repo: AuditRepository = Depends(get_audit_repo),
    vector_store = Depends(get_vector_store_dep),
) -> TeamService:
    return TeamService(
        team_repo=team_repo,
        document_repo=document_repo,
        audit_repo=audit_repo,
        vector_store=vector_store,
    )
