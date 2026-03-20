"""Knowledge Graph service — Neo4j-backed entity and relationship store.

Stores entities and relationships extracted from document chunks and
provides graph-augmented context for RAG queries.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from neo4j import AsyncGraphDatabase
    _NEO4J_AVAILABLE = True
except ImportError:
    _NEO4J_AVAILABLE = False


class KnowledgeGraphService:
    """Neo4j-backed knowledge graph for entity relationship storage and retrieval."""

    def __init__(self, uri: str, user: str, password: str) -> None:
        if not _NEO4J_AVAILABLE:
            raise ImportError(
                "neo4j package is not installed. Run: pip install 'neo4j>=5.0.0'"
            )
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self) -> None:
        await self._driver.close()

    async def ensure_indexes(self) -> None:
        """Create performance indexes — idempotent, safe to call on startup."""
        async with self._driver.session() as session:
            try:
                await session.run(
                    "CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name)"
                )
                await session.run(
                    "CREATE INDEX document_id IF NOT EXISTS FOR (d:Document) ON (d.id)"
                )
            except Exception as exc:
                logger.warning("Failed to create Neo4j indexes (non-fatal): %s", exc)
        await self.ensure_fulltext_index()

    async def store_chunk_graph(
        self,
        entities: list[dict],
        relations: list[dict],
        document_id: str,
        chunk_id: str,
        filename: str = "",
    ) -> None:
        """Persist extracted entities and relationships for one chunk.

        Args:
            entities:    List of {"name": str, "type": str}
            relations:   List of {"source": str, "relation": str, "target": str}
            document_id: Parent document ID
            chunk_id:    Originating chunk ID
            filename:    Human-readable filename for display
        """
        if not entities and not relations:
            return

        async with self._driver.session() as session:
            # Upsert entity nodes and link to document
            for entity in entities:
                name = (entity.get("name") or "").strip()
                etype = (entity.get("type") or "Unknown").strip()
                if not name:
                    continue
                await session.run(
                    """
                    MERGE (e:Entity {name: $name})
                    ON CREATE SET e.type = $type, e.created_at = timestamp()
                    ON MATCH  SET e.type = CASE WHEN e.type IS NULL THEN $type ELSE e.type END
                    MERGE (d:Document {id: $doc_id})
                    ON CREATE SET d.filename = $filename
                    MERGE (e)-[:MENTIONED_IN {chunk_id: $chunk_id}]->(d)
                    """,
                    name=name,
                    type=etype,
                    doc_id=document_id,
                    filename=filename,
                    chunk_id=chunk_id,
                )

            # Upsert directional relationships between entities
            for rel in relations:
                src = (rel.get("source") or "").strip()
                tgt = (rel.get("target") or "").strip()
                relation = (
                    (rel.get("relation") or "RELATED_TO")
                    .strip()
                    .upper()
                    .replace(" ", "_")
                )
                if not src or not tgt:
                    continue
                await session.run(
                    """
                    MERGE (a:Entity {name: $src})
                    MERGE (b:Entity {name: $tgt})
                    MERGE (a)-[r:RELATES_TO {relation: $relation}]->(b)
                    ON CREATE SET r.document_id = $doc_id, r.chunk_id = $chunk_id
                    """,
                    src=src,
                    tgt=tgt,
                    relation=relation,
                    doc_id=document_id,
                    chunk_id=chunk_id,
                )

    async def get_context_for_query(
        self, query_entities: list[str], max_triples: int = 30
    ) -> str:
        """Find the subgraph connected to query entities and return as a text block.

        Traverses one hop in both directions from each matched entity and
        formats the results as human-readable relationship triples.

        Args:
            query_entities: Entity names extracted from the user query.
            max_triples:    Cap on number of relationship triples to include.

        Returns:
            A formatted string like "Knowledge Graph Context:\\n..." or "".
        """
        if not query_entities:
            return ""

        lines: list[str] = []

        async with self._driver.session() as session:
            for entity_name in query_entities[:6]:  # cap to avoid expensive traversal
                # Outgoing relationships
                result = await session.run(
                    """
                    MATCH (e:Entity)
                    WHERE toLower(e.name) CONTAINS toLower($name)
                    MATCH (e)-[r:RELATES_TO]->(target:Entity)
                    RETURN e.name AS source, r.relation AS relation, target.name AS target
                    LIMIT 20
                    """,
                    name=entity_name,
                )
                async for record in result:
                    lines.append(
                        f"{record['source']} —[{record['relation']}]→ {record['target']}"
                    )

                # Incoming relationships
                result2 = await session.run(
                    """
                    MATCH (source:Entity)-[r:RELATES_TO]->(e:Entity)
                    WHERE toLower(e.name) CONTAINS toLower($name)
                    RETURN source.name AS source, r.relation AS relation, e.name AS target
                    LIMIT 10
                    """,
                    name=entity_name,
                )
                async for record in result2:
                    entry = (
                        f"{record['source']} —[{record['relation']}]→ {record['target']}"
                    )
                    if entry not in lines:
                        lines.append(entry)

        if not lines:
            return ""

        unique = list(dict.fromkeys(lines))[:max_triples]
        return "Knowledge Graph Context:\n" + "\n".join(unique)

    async def ensure_fulltext_index(self) -> None:
        """Create Neo4j full-text index on Entity.name — idempotent."""
        async with self._driver.session() as session:
            try:
                await session.run(
                    "CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS "
                    "FOR (e:Entity) ON EACH [e.name, e.type]"
                )
            except Exception as exc:
                logger.debug("Fulltext index creation (non-fatal): %s", exc)

    async def fulltext_search(
        self, query_text: str, limit: int = 10
    ) -> list[ChunkResult]:
        """Full-text search over entity names in the graph.

        Returns pseudo-ChunkResults built from matching entities and their
        connected document chunks — useful as a third retrieval lane.
        """
        from src.core.interfaces import ChunkResult

        results: list[ChunkResult] = []
        try:
            async with self._driver.session() as session:
                result = await session.run(
                    """
                    CALL db.index.fulltext.queryNodes('entity_fulltext', $query)
                    YIELD node, score
                    MATCH (node)-[:MENTIONED_IN]->(d:Document)
                    RETURN node.name AS entity, node.type AS type,
                           d.id AS doc_id, d.filename AS filename,
                           score
                    ORDER BY score DESC
                    LIMIT $limit
                    """,
                    query=query_text,
                    limit=limit,
                )
                async for record in result:
                    entity = record["entity"] or ""
                    etype = record["type"] or "Unknown"
                    doc_id = record["doc_id"] or ""
                    filename = record["filename"] or ""
                    score = float(record["score"])
                    text = f"{entity} ({etype})"
                    results.append(
                        ChunkResult(
                            chunk_id=f"graph:{doc_id}:{entity}",
                            document_id=doc_id,
                            text=text,
                            metadata={"filename": filename, "entity": entity, "type": etype, "source": "graph"},
                            score=min(score / 10.0, 1.0),  # normalise Neo4j score to 0-1
                        )
                    )
        except Exception as exc:
            logger.debug("Neo4j fulltext_search failed (non-fatal): %s", exc)
        return results

    async def delete_document(self, document_id: str) -> None:
        """Remove all graph data (nodes and edges) associated with a document."""
        async with self._driver.session() as session:
            # Remove the document node and its MENTIONED_IN edges
            await session.run(
                "MATCH (d:Document {id: $doc_id}) DETACH DELETE d",
                doc_id=document_id,
            )
            # Prune orphaned entity nodes that are no longer mentioned in any document
            await session.run(
                """
                MATCH (e:Entity)
                WHERE NOT (e)-[:MENTIONED_IN]->()
                  AND NOT (e)-[:RELATES_TO]-()
                DETACH DELETE e
                """
            )


    async def delete_all(self) -> None:
        """Wipe the entire graph — used during seed reset."""
        async with self._driver.session() as session:
            await session.run("MATCH (n) DETACH DELETE n")


def get_kg_service(settings) -> "KnowledgeGraphService | None":
    """Factory — returns None when KG is disabled or neo4j is unavailable."""
    if not getattr(settings, "KNOWLEDGE_GRAPH_ENABLED", False):
        return None
    if not _NEO4J_AVAILABLE:
        logger.warning(
            "KNOWLEDGE_GRAPH_ENABLED=true but 'neo4j' package is not installed. "
            "Run: pip install 'neo4j>=5.0.0'"
        )
        return None
    uri = getattr(settings, "NEO4J_URI", "bolt://localhost:7687")
    user = getattr(settings, "NEO4J_USER", "neo4j")
    password = getattr(settings, "NEO4J_PASSWORD", "neo4jpassword")
    try:
        svc = KnowledgeGraphService(uri=uri, user=user, password=password)
        logger.info("KnowledgeGraphService connected to %s", uri)
        return svc
    except Exception as exc:
        logger.warning("Failed to create KnowledgeGraphService (non-fatal): %s", exc)
        return None
