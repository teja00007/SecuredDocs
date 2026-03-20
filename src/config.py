"""Application settings loaded from environment variables / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    APP_ENV: str = "development"
    APP_SECRET_KEY: str  # Required — app fails without it
    APP_VERSION: str = "0.1.0"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/rag.db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True

    # Vector Store
    VECTOR_STORE_TYPE: str = "chroma"
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    PGVECTOR_TABLE: str = "document_chunks"

    # Embedding
    EMBEDDING_PROVIDER: str = "ollama"
    EMBEDDING_MODEL: str = "nomic-embed-text"
    EMBEDDING_DIMENSIONS: int = 768
    # nomic-embed-text uses asymmetric prefixes for better retrieval discrimination.
    # Set to "" if using a model that doesn't require prefixes.
    EMBEDDING_QUERY_PREFIX: str = "search_query: "
    EMBEDDING_DOC_PREFIX: str = "search_document: "

    # LLM
    LLM_PROVIDER: str = "ollama"
    LLM_MODEL: str = "llama3.1:8b"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Google Gemini
    GEMINI_API_KEY: str = ""

    # Azure OpenAI
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""          # e.g. https://<resource>.openai.azure.com/
    AZURE_OPENAI_API_VERSION: str = "2024-02-01"

    # AWS Bedrock
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # vLLM (self-hosted OpenAI-compatible server)
    VLLM_BASE_URL: str = "http://localhost:8080/v1"

    # LDAP / Active Directory
    LDAP_ENABLED: bool = False
    LDAP_SERVER: str = "ldap://localhost:389"
    LDAP_BIND_DN: str = ""
    LDAP_BIND_PASSWORD: str = ""
    LDAP_BASE_DN: str = "DC=example,DC=com"
    LDAP_USER_FILTER: str = "(sAMAccountName={username})"
    LDAP_GROUP_BASE_DN: str = ""
    LDAP_GROUP_FILTER: str = "(member={user_dn})"
    LDAP_GROUP_ROLE_MAP: str = "{}"   # JSON: {"Group CN": "nexus_role"}
    LDAP_TLS: bool = False

    # Azure AD group sync (on top of existing Microsoft OAuth)
    AZURE_AD_SYNC_ENABLED: bool = False
    AZURE_AD_GROUP_ROLE_MAP: str = "{}"  # JSON: {"group-object-id": "nexus_role"}

    # RabbitMQ (optional — replace Celery+Redis at scale)
    RABBITMQ_ENABLED: bool = False
    RABBITMQ_URL: str = "amqp://guest:guest@localhost:5672/"

    # Image processing
    IMAGE_PROCESSING_MODE: str = "caption"    # "caption" or "clip"
    IMAGE_CAPTION_PROVIDER: str = "openai"
    IMAGE_CAPTION_MODEL: str = "gpt-4o"

    # Auth
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Ingestion
    MAX_UPLOAD_SIZE_MB: int = 100
    CHUNK_SIZE: int = 512
    CHUNK_OVERLAP: int = 64
    MIN_CHUNK_SIZE: int = 50
    MAX_CHUNK_SIZE: int = 1024

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Search & Retrieval
    HYBRID_SEARCH_ENABLED: bool = True
    RETRIEVAL_TOP_K: int = 20     # candidates to retrieve before re-ranking
    RETRIEVAL_SCORE_THRESHOLD: float = 0.65  # min cosine similarity; raise to 0.70+ for stricter filtering
    QUERY_REWRITING_ENABLED: bool = True

    # Re-ranking
    RERANKER_TYPE: str = "local"  # "none" | "local" | "cohere" | "bge"
    RERANKER_TOP_N: int = 8
    LOCAL_RERANKER_MODEL: str = "ms-marco-MiniLM-L-12-v2"  # flashrank model name
    COHERE_API_KEY: str = ""
    RERANKER_URL: str = "http://localhost:8081"  # for BGE TEI endpoint

    # Advanced query rewriting
    QUERY_REWRITE_MODE: str = "multi"   # "single" | "hyde" | "multi" | "none"
    QUERY_REWRITE_COUNT: int = 3

    # Contextual retrieval (prepend LLM-generated context to each chunk at ingestion)
    CONTEXTUAL_RETRIEVAL_ENABLED: bool = True

    # Chunking
    DEFAULT_CHUNKING_STRATEGY: str = "hierarchical"  # default for all uploads
    HIERARCHICAL_PARENT_SIZE: int = 1500
    HIERARCHICAL_CHILD_SIZE: int = 200

    # Auto-tagging
    AUTO_TAGGING_ENABLED: bool = True

    # Knowledge Graph (Neo4j)
    KNOWLEDGE_GRAPH_ENABLED: bool = True
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "neo4jpassword"

    # Compliance
    COMPLIANCE_LLM_ENABLED: bool = True
    COMPLIANCE_LLM_PROVIDER: str = "ollama"
    COMPLIANCE_LLM_MODEL: str = "llama3.1:8b"
    COMPLIANCE_LLM_TIMEOUT: int = 30
    COMPLIANCE_LLM_MAX_TEXT_LENGTH: int = 4000

    # Livekit (optional — huddle feature)
    LIVEKIT_URL: str = "ws://localhost:7880"
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""

    # TURN server (optional — required for Docker on macOS, or restrictive NATs)
    # Supports any standard TURN server: self-hosted coturn, metered.ca, Twilio NTS, etc.
    # Leave blank to use direct WebRTC only (works on Linux, fails on macOS Docker).
    TURN_URL: str = ""          # e.g. turn:192.168.0.161:3478?transport=tcp
    TURN_USERNAME: str = ""
    TURN_CREDENTIAL: str = ""
    # 'relay'  → force all media through TURN (recommended when TURN is set)
    # 'all'    → try direct UDP first, fall back to TURN (default WebRTC behaviour)
    ICE_TRANSPORT_POLICY: str = "all"

    # Invite-only registration
    INVITE_ONLY: bool = False

    # Email / SMTP
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_TLS: bool = True
    APP_URL: str = "http://localhost:3000"

    # OAuth2 SSO — Google
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # OAuth2 SSO — Microsoft
    MICROSOFT_CLIENT_ID: str = ""
    MICROSOFT_CLIENT_SECRET: str = ""

    # OAuth2 shared settings
    OAUTH_REDIRECT_BASE: str = "http://localhost:8000"
    # OAUTH_STATE_SECRET falls back to APP_SECRET_KEY at runtime if empty
    OAUTH_STATE_SECRET: str = ""

    # SAML 2.0 SSO
    SAML_ENABLED: bool = False
    SAML_IDP_METADATA_URL: str = ""
    SAML_SP_ENTITY_ID: str = ""   # defaults to "{APP_URL}/api/v1/saml/metadata" at runtime
    SAML_SP_ACS_URL: str = ""     # defaults to "{APP_URL}/api/v1/saml/acs" at runtime

    # Redis cache (separate DB from Celery to prevent data collision)
    REDIS_URL: str = "redis://localhost:6379/0"           # Celery broker
    REDIS_CACHE_URL: str = "redis://localhost:6379/1"     # Semantic + embedding cache

    # Semantic cache
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_TTL: int = 3600          # 1 hour
    SEMANTIC_CACHE_SIMILARITY: float = 0.95  # similarity threshold for cache hit

    # Embedding cache
    EMBEDDING_CACHE_ENABLED: bool = True
    EMBEDDING_CACHE_TTL: int = 86400        # 24 hours

    # Query classifier
    QUERY_CLASSIFIER_ENABLED: bool = True

    # Conversation memory (Redis-backed sliding window)
    CONVERSATION_MEMORY_ENABLED: bool = True
    CONVERSATION_WINDOW_SIZE: int = 6       # last 6 messages (3 turns)
    CONVERSATION_TTL: int = 3600            # 1 hour inactivity TTL

    # Low-confidence fallback threshold
    LOW_CONFIDENCE_THRESHOLD: float = 0.20

    # Parallel retrieval pipeline
    PARALLEL_PIPELINE_ENABLED: bool = True

    # LlamaIndex semantic ingestion pipeline
    # Requires: pip install llama-index llama-index-embeddings-ollama
    LLAMAINDEX_PIPELINE_ENABLED: bool = False

    # LlamaIndex PropertyGraphIndex → Neo4j ingestion
    # Requires: pip install llama-index llama-index-graph-stores-neo4j
    LLAMAINDEX_GRAPH_ENABLED: bool = False

    # Qdrant native sparse BM25 vectors (Lane 2 in parallel pipeline)
    # Requires: pip install fastembed
    QDRANT_SPARSE_ENABLED: bool = False

    # Storage backend: "local" or "minio"
    STORAGE_BACKEND: str = "local"
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "nexus-documents"
    MINIO_SECURE: bool = False
    MINIO_PRESIGN_EXPIRES: int = 3600       # seconds
    LOCAL_STORAGE_DIR: str = "./data/uploads"

    # OpenTelemetry
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "nexus-backend"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://localhost:4317"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
