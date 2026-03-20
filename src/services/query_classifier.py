"""Query classifier — routes retrieval to relevant lanes only.

Adds ~5ms overhead but saves 80-150ms per query by skipping
irrelevant retrieval lanes.

Lanes:
  vector  — dense semantic search (always active)
  bm25    — sparse keyword BM25 search
  graph   — entity relationship traversal (Neo4j)
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

_GRAPH_RE = re.compile(
    r"\b(who|what is the relationship|connected|related to|works with|"
    r"reports to|managed by|collaborated|associates?|linked|depends on|"
    r"between .+ and|how (does|is) .+ (connect|relate|relate to)|"
    r"network of|colleagues?|partners?|clients? of|employed by|hired by)\b",
    re.IGNORECASE,
)

_KEYWORD_RE = re.compile(
    r"\b(error|exception|function|class|method|config|file|path|"
    r"line \d+|version \d|specific\b|exact\b|verbatim|code|snippet|"
    r"find all|show me all|list all|where is)\b",
    re.IGNORECASE,
)

_SEMANTIC_RE = re.compile(
    r"\b(what is|explain|describe|summarize|overview|concept|"
    r"how does|what are|tell me about|understand|meaning of|definition of)\b",
    re.IGNORECASE,
)


class QueryClassifier:
    """Classify a query to determine which retrieval lanes to activate."""

    def classify(self, query: str) -> frozenset[str]:
        """Return frozenset of lanes: subset of {'vector', 'bm25', 'graph'}.

        Always returns at least {'vector'}.
        """
        words = query.split()
        lanes: set[str] = {"vector"}  # always active

        if len(words) <= 2:
            return frozenset(lanes)

        if _GRAPH_RE.search(query):
            lanes.add("graph")

        if _KEYWORD_RE.search(query):
            lanes.add("bm25")

        # Long queries benefit from both vector + BM25
        if len(words) >= 7:
            lanes.add("bm25")

        logger.debug("QueryClassifier: %r → %s", query[:60], sorted(lanes))
        return frozenset(lanes)

    def should_use_graph(self, query: str) -> bool:
        return "graph" in self.classify(query)

    def should_use_bm25(self, query: str) -> bool:
        return "bm25" in self.classify(query)
