"""Ingest seeded documents into ChromaDB (vectors) and Neo4j (knowledge graph).

Run after seed_company_one.py + seed_company_two.py:
  python scripts/seed_neo4j.py          # skip already-ingested docs
  python scripts/seed_neo4j.py --reset  # wipe both stores and re-ingest all

What this script does per document:
  1. Reads content from seed_company_one / seed_company_two DOC_CONTENT dicts
  2. Looks up the document record in PostgreSQL to get id, owner, visibility, etc.
  3. Pulls the Ollama embedding model if not yet available
  4. Chunks the markdown text and embeds each chunk via Ollama
  5. Upserts chunks into ChromaDB (with full RBAC metadata)
  6. Extracts named entities using regex patterns (no LLM required)
  7. Upserts entities + typed relationships into Neo4j
  8. Updates the document chunk_count in the DB
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from textwrap import shorten

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_neo4j")

# ─────────────────────────────────────────────────────────────────────────────
# Entity extraction (regex-based — no LLM required)
# ─────────────────────────────────────────────────────────────────────────────

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(
        r"\b(PostgreSQL|MySQL|MongoDB|Redis|Neo4j|ChromaDB|Qdrant|pgvector|FastAPI|"
        r"SQLAlchemy|Alembic|Celery|Docker|Kubernetes|Helm|Terraform|AWS|GCP|Azure|"
        r"GitHub|GitLab|Slack|Linear|Notion|Jira|Confluence|1Password|"
        r"Google\s+Workspace|Google\s+Drive|Ollama|Anthropic|OpenAI|Whisper|"
        r"LiveKit|LangChain|Next\.js|React|TypeScript|Python|SQLite|"
        r"Tesseract|OAuth|SAML|SSO|MFA|TOTP|S3|EC2|RDS|ECS|EKS|Lambda|"
        r"CloudWatch|VPC|IAM|AWS\s+HealthLake|TLS|JWT|BM25|Prometheus|Grafana|"
        r"HL7|FHIR|DICOM|EHR|LMS|HIS)\b"
    ), "Technology"),
    (re.compile(
        r"\b(HIPAA|GDPR|SOC\s*2|SOC2|FDA|FERPA|PCI[- ]?DSS|PHI|ePHI|BAA|"
        r"510\(k\)|ISO\s*27001|NIST|CCPA|HITRUST|DoD\s*5220|ICD-10|CPT|"
        r"HITECH|PIPEDA|DORA|NIS2)\b"
    ), "Regulation"),
    (re.compile(
        r"\b(TechCorp|HealthFlow(?:\s+Systems)?|Blue\s+Shield|Kaiser|"
        r"Delta\s+Dental|VSP|HHS|CMS|CDC)\b"
    ), "Organization"),
    (re.compile(r"\b(CEO|CTO|CFO|CMO|CPO|CHRO|CIO|CSO|COO|EVP|SVP)\b"), "Role"),
    (re.compile(
        r"\b(Compliance\s+Officer|Privacy\s+Officer|HIPAA\s+Officer|"
        r"Medical\s+Officer|Nursing\s+Officer)\b", re.I
    ), "Role"),
    (re.compile(
        r"\b(onboarding|performance\s+review|incident\s+response|CI/?CD|"
        r"code\s+review|data\s+anonymization|breach\s+notification|"
        r"risk\s+assessment|penetration\s+test(?:ing)?|security\s+audit|"
        r"PHI\s+audit|data\s+retention|access\s+control|disaster\s+recovery|"
        r"on-?call|deployment|runbook|change\s+management)\b", re.I
    ), "Process"),
    (re.compile(
        r"\b(RAG|knowledge\s+graph|vector\s+stor(?:e|age)|embedding|LLM|"
        r"machine\s+learning|NLP|natural\s+language\s+processing|"
        r"semantic\s+search|hybrid\s+search|rerank(?:ing)?|chunk(?:ing)?|"
        r"retrieval|fine.tuning|transformer)\b", re.I
    ), "Concept"),
    (re.compile(
        r"\b(401k|401\(k\)|PTO|stock\s+options?|vesting|parental\s+leave|"
        r"health\s+insurance|life\s+insurance|HSA|FSA|"
        r"learning\s+stipend|wellness\s+stipend)\b", re.I
    ), "Benefit"),
    (re.compile(
        r"\b(OKR|KPI|SLA|SLO|uptime|latency|throughput|MTTR|MTBF|RTO|RPO|"
        r"p99|p95|error\s+budget)\b"
    ), "Metric"),
    (re.compile(
        r"\b(HIPAA\s+Policy|Code\s+of\s+Conduct|Privacy\s+Policy|"
        r"Security\s+Policy|Compliance\s+Policy|Data\s+Policy|"
        r"Acceptable\s+Use\s+Policy|Retention\s+Policy|"
        r"Business\s+Continuity\s+Plan|Disaster\s+Recovery\s+Plan|"
        r"BAA\s+Template|Data\s+Processing\s+Agreement)\b", re.I
    ), "Policy"),
]

_TYPE_RELATIONS: dict[tuple[str, str], str] = {
    ("Regulation",   "Organization"): "APPLIES_TO",
    ("Regulation",   "Process"):      "GOVERNS",
    ("Regulation",   "Policy"):       "REQUIRES",
    ("Technology",   "Organization"): "USED_BY",
    ("Technology",   "Process"):      "SUPPORTS",
    ("Technology",   "Concept"):      "IMPLEMENTS",
    ("Process",      "Role"):         "PERFORMED_BY",
    ("Policy",       "Organization"): "OWNED_BY",
    ("Concept",      "Technology"):   "ENABLED_BY",
    ("Benefit",      "Organization"): "PROVIDED_BY",
}


def _extract_entities(text: str) -> list[dict]:
    if not text:
        return []
    seen: set[str] = set()
    result: list[dict] = []
    for pattern, etype in _PATTERNS:
        for m in pattern.finditer(text):
            name = re.sub(r"\s+", " ", m.group(0)).strip()
            key = name.lower()
            if key not in seen and len(name) > 1:
                seen.add(key)
                result.append({"name": name, "type": etype})
    return result[:20]


def _extract_relations(entities: list[dict]) -> list[dict]:
    seen_pairs: set[tuple] = set()
    result: list[dict] = []
    for i, e1 in enumerate(entities):
        for e2 in entities[i + 1:]:
            pair = (e1["type"], e2["type"])
            rev  = (e2["type"], e1["type"])
            label = _TYPE_RELATIONS.get(pair) or _TYPE_RELATIONS.get(rev)
            if label:
                src, tgt = (e1, e2) if pair in _TYPE_RELATIONS else (e2, e1)
                key = (src["name"].lower(), label, tgt["name"].lower())
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    result.append({
                        "source": src["name"],
                        "relation": label,
                        "target": tgt["name"],
                    })
    return result[:15]


# ─────────────────────────────────────────────────────────────────────────────
# Text chunking (simple paragraph-aware splitter — no dependency on parsers)
# ─────────────────────────────────────────────────────────────────────────────

def _chunk_text(text: str, max_chars: int = 800, min_section_chars: int = 60) -> list[str]:
    """Split markdown into one-section-per-chunk for precise semantic embedding.

    Each meaningful ## section becomes its own chunk so its embedding closely
    represents that section's topic. Only very short sections (< min_section_chars)
    are merged with neighbours. Oversized sections are split by paragraph.
    """
    sections = re.split(r"(?=^#{1,3} )", text, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    def _split_large(section: str) -> list[str]:
        """Paragraph-split a section that exceeds max_chars."""
        paras = [p.strip() for p in re.split(r"\n{2,}", section) if p.strip()]
        result, part = [], ""
        for para in paras:
            if len(part) + len(para) + 2 <= max_chars:
                part = (part + "\n\n" + para).strip() if part else para
            else:
                if part:
                    result.append(part)
                part = para if len(para) <= max_chars else para[:max_chars]
        if part:
            result.append(part)
        return result or [section[:max_chars]]

    chunks: list[str] = []
    tiny_buf = ""  # accumulator for very short sections only

    for section in sections:
        if len(section) >= min_section_chars:
            # Meaningful section — flush any accumulated tiny sections first
            if tiny_buf:
                chunks.append(tiny_buf)
                tiny_buf = ""
            if len(section) > max_chars:
                chunks.extend(_split_large(section))
            else:
                chunks.append(section)
        else:
            # Tiny section — merge with tiny buffer
            candidate = (tiny_buf + "\n\n" + section).strip() if tiny_buf else section
            if len(candidate) <= max_chars:
                tiny_buf = candidate
            else:
                chunks.append(tiny_buf)
                tiny_buf = section

    if tiny_buf:
        chunks.append(tiny_buf)

    return chunks or ([text[:max_chars]] if text else [])


# ─────────────────────────────────────────────────────────────────────────────
# Load seed scripts — import DOC_CONTENT without running __main__
# ─────────────────────────────────────────────────────────────────────────────

def _load_doc_content() -> dict[str, str]:
    """Merge DOC_CONTENT from both seed scripts into {filename: content}."""
    combined: dict[str, str] = {}
    scripts_dir = Path(__file__).parent
    for fname in ("seed_company_one.py", "seed_company_two.py"):
        path = scripts_dir / fname
        if not path.exists():
            print(f"  Warning: {fname} not found — skipping")
            continue
        try:
            spec = importlib.util.spec_from_file_location(fname.replace(".py", ""), path)
            mod  = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            combined.update(getattr(mod, "DOC_CONTENT", {}))
        except Exception as exc:
            print(f"  Warning: could not load {fname}: {exc}")
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# Ollama helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _wait_for_ollama(base_url: str, timeout: int = 180) -> None:
    import httpx, time
    print(f"  Waiting for Ollama at {base_url} (up to {timeout}s) …", flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=5.0) as c:
                r = await c.get(f"{base_url}/api/version")
                if r.status_code == 200:
                    print("  Ollama ready.")
                    return
        except Exception:
            pass
        await asyncio.sleep(5)
    raise RuntimeError(f"Ollama not reachable at {base_url} after {timeout}s")


async def _ensure_model(base_url: str, model: str) -> None:
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(f"{base_url}/api/show", json={"model": model})
        if r.status_code == 200:
            return  # model already present
    print(f"  Pulling model '{model}' — this may take several minutes …", flush=True)
    async with httpx.AsyncClient(timeout=600.0) as c:
        r = await c.post(f"{base_url}/api/pull", json={"model": model, "stream": False})
        r.raise_for_status()
    print(f"  Model '{model}' ready.")


async def _embed(base_url: str, model: str, text: str) -> list[float]:
    """Embed a single text string. Tries /api/embed first, falls back to /api/embeddings."""
    import httpx
    async with httpx.AsyncClient(timeout=60.0) as c:
        try:
            r = await c.post(f"{base_url}/api/embed", json={"model": model, "input": text})
            if r.status_code == 200:
                data = r.json().get("embeddings", [])
                return data[0] if data else []
        except Exception:
            pass
        r = await c.post(f"{base_url}/api/embeddings", json={"model": model, "prompt": text})
        r.raise_for_status()
        return r.json().get("embedding", [])


# ─────────────────────────────────────────────────────────────────────────────
# ChromaDB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_chroma_collection(persist_dir: str):
    import chromadb
    client = chromadb.PersistentClient(path=persist_dir)
    return client.get_or_create_collection(
        name="rag_documents",
        metadata={"hnsw:space": "cosine"},
    )


def _chroma_has_doc(collection, document_id: str) -> bool:
    try:
        result = collection.get(
            where={"document_id": {"$eq": document_id}},
            include=[],
        )
        return len(result.get("ids", [])) > 0
    except Exception:
        return False


def _chroma_delete_doc(collection, document_id: str) -> None:
    try:
        result = collection.get(
            where={"document_id": {"$eq": document_id}},
            include=[],
        )
        ids = result.get("ids", [])
        if ids:
            collection.delete(ids=ids)
    except Exception:
        pass


def _flatten_meta(meta: dict) -> dict:
    flat: dict = {}
    for k, v in meta.items():
        if isinstance(v, list):
            flat[k] = "|" + "|".join(str(x) for x in v) + "|" if v else ""
        elif isinstance(v, (str, int, float, bool)):
            flat[k] = v
        elif v is None:
            flat[k] = ""
        else:
            flat[k] = str(v)
    return flat


# ─────────────────────────────────────────────────────────────────────────────
# Neo4j helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _neo4j_ensure_indexes(session) -> None:
    for stmt in [
        "CREATE INDEX entity_name  IF NOT EXISTS FOR (e:Entity)   ON (e.name)",
        "CREATE INDEX doc_id       IF NOT EXISTS FOR (d:Document)  ON (d.id)",
        "CREATE INDEX company_name IF NOT EXISTS FOR (c:Company)   ON (c.name)",
    ]:
        try:
            await session.run(stmt)
        except Exception:
            pass


async def _neo4j_store(session, entities, relations, doc_id: str, filename: str, company: str) -> None:
    if not entities and not relations:
        return
    # Document node
    await session.run(
        "MERGE (d:Document {id: $id}) ON CREATE SET d.filename = $fn, d.company = $co",
        id=doc_id, fn=filename, co=company,
    )
    # Company node + link
    await session.run(
        "MERGE (c:Company {name: $co}) MERGE (d:Document {id: $id}) MERGE (d)-[:BELONGS_TO]->(c)",
        co=company, id=doc_id,
    )
    for ent in entities:
        name = (ent.get("name") or "").strip()
        etype = ent.get("type", "Unknown")
        if not name:
            continue
        await session.run(
            """
            MERGE (e:Entity {name: $name})
            ON CREATE SET e.type = $type
            WITH e
            MATCH (d:Document {id: $id})
            MERGE (e)-[:MENTIONED_IN]->(d)
            """,
            name=name, type=etype, id=doc_id,
        )
    for rel in relations:
        src = (rel.get("source") or "").strip()
        tgt = (rel.get("target") or "").strip()
        label = ((rel.get("relation") or "RELATED_TO").strip().upper().replace(" ", "_"))
        if src and tgt:
            await session.run(
                """
                MERGE (a:Entity {name: $src})
                MERGE (b:Entity {name: $tgt})
                MERGE (a)-[r:RELATES_TO {relation: $rel}]->(b)
                ON CREATE SET r.document_id = $id
                """,
                src=src, tgt=tgt, rel=label, id=doc_id,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_docs_from_db(session, content_map: dict) -> list[dict]:
    """Return DB documents that have seed content available."""
    from sqlalchemy import select, text
    from src.models.document import Document, DocumentTeamAccess

    result = await session.execute(select(Document))
    all_docs = result.scalars().all()

    docs = []
    for doc in all_docs:
        content = content_map.get(doc.filename, "")
        if not content:
            continue

        # Team access
        ta_result = await session.execute(
            select(DocumentTeamAccess).where(
                DocumentTeamAccess.document_id == doc.id
            )
        )
        allowed_teams = [ta.team_id for ta in ta_result.scalars().all()]

        vis = doc.visibility.value if hasattr(doc.visibility, "value") else str(doc.visibility)
        docs.append({
            "id":            str(doc.id),
            "filename":      doc.filename,
            "collection_id": str(doc.collection_id) if doc.collection_id else "",
            "owner_id":      str(doc.owner_id) if doc.owner_id else "",
            "visibility":    vis,
            "allowed_teams": allowed_teams,
            "content":       content,
            "company":       "",  # filled below from company table
        })
    return docs


async def _resolve_companies(session, docs: list[dict]) -> None:
    """Set doc['company'] from the users.company_id → companies.name lookup."""
    from sqlalchemy import text
    try:
        result = await session.execute(text(
            "SELECT u.id, c.name "
            "FROM users u JOIN companies c ON c.id = u.company_id "
            "WHERE u.company_id IS NOT NULL"
        ))
        user_company = {str(row[0]): row[1] for row in result.fetchall()}
        for doc in docs:
            doc["company"] = user_company.get(doc["owner_id"], "Unknown")
    except Exception:
        for doc in docs:
            doc["company"] = "Unknown"


async def _update_chunk_count(session, doc_id: str, count: int) -> None:
    from sqlalchemy import text
    try:
        await session.execute(
            text("UPDATE documents SET chunk_count = :n, status = 'ready' WHERE id = :id"),
            {"n": count, "id": doc_id},
        )
        await session.commit()
    except Exception:
        await session.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# Main ingestion loop
# ─────────────────────────────────────────────────────────────────────────────

async def run(reset: bool) -> None:
    from src.config import get_settings
    from src.db.session import get_async_engine, get_session_factory
    from neo4j import AsyncGraphDatabase

    settings = get_settings()

    # ── ChromaDB ──────────────────────────────────────────────────────────────
    chroma_dir = getattr(settings, "CHROMA_PERSIST_DIR", "data/chroma")
    # Resolve relative path from project root
    if not os.path.isabs(chroma_dir):
        chroma_dir = str(Path(__file__).resolve().parent.parent / chroma_dir)
    os.makedirs(chroma_dir, exist_ok=True)
    collection = _get_chroma_collection(chroma_dir)

    if reset:
        print("  Resetting ChromaDB collection …")
        try:
            import chromadb
            client = chromadb.PersistentClient(path=chroma_dir)
            try:
                client.delete_collection("rag_documents")
            except Exception:
                pass
            collection = client.get_or_create_collection(
                "rag_documents", metadata={"hnsw:space": "cosine"}
            )
        except Exception as exc:
            print(f"  ChromaDB reset warning: {exc}")

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_url  = getattr(settings, "OLLAMA_BASE_URL",       "http://localhost:11434")
    embed_model = getattr(settings, "EMBEDDING_MODEL",        "nomic-embed-text")
    doc_prefix  = getattr(settings, "EMBEDDING_DOC_PREFIX",   "")

    await _wait_for_ollama(ollama_url)
    await _ensure_model(ollama_url, embed_model)

    # ── Neo4j ─────────────────────────────────────────────────────────────────
    neo4j_uri  = getattr(settings, "NEO4J_URI",      "bolt://localhost:7687")
    neo4j_user = getattr(settings, "NEO4J_USER",     "neo4j")
    neo4j_pass = getattr(settings, "NEO4J_PASSWORD", "neo4jpassword")

    neo_driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
    try:
        await neo_driver.verify_connectivity()
        print(f"  Neo4j connected at {neo4j_uri}")
    except Exception as exc:
        print(f"  Neo4j connection failed: {exc} — graph seeding will be skipped")
        neo_driver = None

    if neo_driver and reset:
        print("  Resetting Neo4j graph …")
        async with neo_driver.session() as s:
            await s.run("MATCH (n) DETACH DELETE n")

    if neo_driver:
        async with neo_driver.session() as s:
            await _neo4j_ensure_indexes(s)

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    engine  = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    content_map = _load_doc_content()
    print(f"  Loaded content for {len(content_map)} documents from seed scripts")

    async with factory() as session:
        docs = await _get_docs_from_db(session, content_map)
        await _resolve_companies(session, docs)
        print(f"  Found {len(docs)} DB documents with seed content\n")

        total_chunks = total_ents = total_rels = 0
        skipped = 0

        for doc in docs:
            doc_id   = doc["id"]
            filename = doc["filename"]
            company  = doc["company"]

            # Skip if already in ChromaDB (unless reset)
            if not reset and _chroma_has_doc(collection, doc_id):
                skipped += 1
                continue

            if reset:
                _chroma_delete_doc(collection, doc_id)

            content = doc["content"]
            chunks  = _chunk_text(content)

            # ── Embed + store in ChromaDB ─────────────────────────────────────
            chroma_records: list[dict] = []
            for i, chunk_text in enumerate(chunks):
                embedding = await _embed(ollama_url, embed_model, doc_prefix + chunk_text)
                chunk_id  = f"{doc_id}_{i}"
                chroma_records.append({
                    "chunk_id":      chunk_id,
                    "embedding":     embedding,
                    "text":          chunk_text,
                    "document_id":   doc_id,
                    "filename":      filename,
                    "owner_id":      doc["owner_id"],
                    "collection_id": doc["collection_id"],
                    "visibility":    doc["visibility"],
                    "allowed_teams": doc["allowed_teams"],
                    "allowed_users": [],
                })

            # Upsert to ChromaDB
            ids        = [r["chunk_id"]  for r in chroma_records]
            embeddings = [r["embedding"] for r in chroma_records]
            documents  = [r["text"]      for r in chroma_records]
            metadatas  = [_flatten_meta({k: v for k, v in r.items()
                                         if k not in ("chunk_id", "embedding", "text")})
                          for r in chroma_records]
            collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
            total_chunks += len(chunks)

            # ── Update chunk count in DB ──────────────────────────────────────
            await _update_chunk_count(session, doc_id, len(chunks))

            # ── Entity extraction + Neo4j ─────────────────────────────────────
            n_ents = n_rels = 0
            if neo_driver:
                entities  = _extract_entities(content)
                relations = _extract_relations(entities)
                async with neo_driver.session() as ns:
                    await _neo4j_store(ns, entities, relations, doc_id, filename, company)
                n_ents = len(entities)
                n_rels = len(relations)
                total_ents += n_ents
                total_rels += n_rels

            label = shorten(filename, 46, placeholder="…")
            print(
                f"  [{company:10}] {label:<48} "
                f"{len(chunks):>2} chunks  {n_ents:>2} entities  {n_rels:>2} rels"
            )

    if neo_driver:
        await neo_driver.close()
    await engine.dispose()

    print(f"\n  Skipped (already ingested): {skipped}")
    print(
        f"  Ingested: {len(docs) - skipped} documents | "
        f"{total_chunks} chunks | {total_ents} entities | {total_rels} relations"
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed ChromaDB + Neo4j from seeded documents")
    parser.add_argument("--reset", action="store_true",
                        help="Wipe ChromaDB + Neo4j and re-ingest everything")
    args = parser.parse_args()

    try:
        await run(reset=args.reset)
        print("\nIngestion complete.")
    except Exception as exc:
        print(f"\nIngestion failed (non-fatal): {exc}")
        import traceback; traceback.print_exc()
        sys.exit(0)   # exit 0 so startup.sh proceeds to start the server


if __name__ == "__main__":
    asyncio.run(main())
