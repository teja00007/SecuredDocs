#!/usr/bin/env bash
# =============================================================================
# Nexus RAG — One-time startup + migration script
# Run ONCE after bringing up the new stack for the first time.
#
# Usage (from project root, stack must be up):
#   chmod +x scripts/startup_and_migration.sh
#   ./scripts/startup_and_migration.sh
#
# What this does:
#   1. Wait for Ollama to be ready
#   2. Pull phi4:mini (LLM) + nomic-embed-text (embeddings)
#   3. Wait for Qdrant to be ready
#   4. Migrate existing ChromaDB collections → Qdrant
#   5. Verify / create Neo4j full-text index on Entity nodes
#   6. Rebuild BM25 index from the database
# =============================================================================
set -euo pipefail

OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
NEO4J_URL="${NEO4J_URL:-bolt://localhost:7687}"
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-neo4jpassword}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# ── 0. Check we're in the project root ────────────────────────────────────────
if [[ ! -f "src/main.py" ]]; then
  error "Run this script from the project root (where src/main.py lives)."
  exit 1
fi

# ── 1. Wait for Ollama ────────────────────────────────────────────────────────
info "Waiting for Ollama at ${OLLAMA_URL} ..."
for i in $(seq 1 30); do
  if curl -sf "${OLLAMA_URL}/api/tags" > /dev/null 2>&1; then
    info "Ollama is ready."
    break
  fi
  if [[ $i -eq 30 ]]; then
    error "Ollama did not become ready within 150s. Is it running?"
    exit 1
  fi
  sleep 5
done

# ── 2. Pull LLM + embedding models ───────────────────────────────────────────
pull_model() {
  local model="$1"
  info "Pulling model: ${model} ..."
  if curl -sf "${OLLAMA_URL}/api/tags" | python3 -c "import sys,json; tags=json.load(sys.stdin); exit(0 if any('${model}' in m.get('name','') for m in tags.get('models',[])) else 1)" 2>/dev/null; then
    info "  ${model} already present — skipping pull."
  else
    curl -sf -X POST "${OLLAMA_URL}/api/pull" \
      -H "Content-Type: application/json" \
      -d "{\"name\": \"${model}\", \"stream\": false}" | \
      python3 -c "import sys,json; d=json.load(sys.stdin); print('  Status:', d.get('status','?'))"
    info "  ${model} pull complete."
  fi
}

pull_model "phi4:mini"
pull_model "nomic-embed-text"

# ── 3. Wait for Qdrant ────────────────────────────────────────────────────────
info "Waiting for Qdrant at ${QDRANT_URL} ..."
for i in $(seq 1 20); do
  if curl -sf "${QDRANT_URL}/health" > /dev/null 2>&1; then
    info "Qdrant is ready."
    break
  fi
  if [[ $i -eq 20 ]]; then
    error "Qdrant did not become ready within 100s. Is it running?"
    exit 1
  fi
  sleep 5
done

# ── 4. Migrate ChromaDB → Qdrant ─────────────────────────────────────────────
CHROMA_DIR="${CHROMA_DIR:-./data/chroma}"
if [[ -d "${CHROMA_DIR}" ]]; then
  info "Migrating ChromaDB data from ${CHROMA_DIR} to Qdrant ..."
  python3 scripts/migrate_chroma_to_qdrant.py \
    --chroma-path "${CHROMA_DIR}" \
    --qdrant-url "${QDRANT_URL}" && \
    info "ChromaDB → Qdrant migration complete." || \
    warn "Migration script reported a non-fatal error — check output above."
else
  warn "No ChromaDB directory found at ${CHROMA_DIR} — skipping migration."
fi

# ── 5. Verify / create Neo4j full-text index ─────────────────────────────────
info "Ensuring Neo4j full-text index on Entity nodes ..."
python3 - <<'PYEOF'
import asyncio, os, sys

async def ensure_index():
    try:
        from neo4j import AsyncGraphDatabase
        url  = os.environ.get("NEO4J_URL",      "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER",      "neo4j")
        pwd  = os.environ.get("NEO4J_PASSWORD",  "neo4jpassword")
        driver = AsyncGraphDatabase.driver(url, auth=(user, pwd))
        async with driver.session() as session:
            # Create full-text index idempotently
            await session.run("""
                CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
                FOR (n:Entity) ON EACH [n.name, n.type]
            """)
        await driver.close()
        print("[INFO]  Neo4j full-text index OK.")
    except ImportError:
        print("[WARN]  neo4j driver not installed — skipping index check.")
    except Exception as e:
        print(f"[WARN]  Neo4j index check failed (non-fatal): {e}")

asyncio.run(ensure_index())
PYEOF

# ── 6. Rebuild BM25 index ─────────────────────────────────────────────────────
info "Rebuilding BM25 index from database ..."
python3 scripts/rebuild_bm25.py && \
  info "BM25 index rebuilt." || \
  warn "BM25 rebuild reported an error — non-fatal, will rebuild on next query."

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "========================================================"
info "  Migration complete. Services summary:"
info "    Backend  → http://localhost:8000"
info "    Frontend → http://localhost:3000"
info "    Grafana  → http://localhost:3001  (admin / \${GRAFANA_PASSWORD:-admin})"
info "    Prometheus → http://localhost:9090"
info "    Qdrant   → http://localhost:6333"
info "    Neo4j    → http://localhost:7474"
info "========================================================"
