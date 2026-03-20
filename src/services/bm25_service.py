"""In-memory BM25 index that runs alongside the vector store."""

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BM25_INDEX_PATH = Path("data/bm25_index.json")

try:
    from rank_bm25 import BM25Okapi  # type: ignore
    _BM25_AVAILABLE = True
except ImportError:
    _BM25_AVAILABLE = False
    logger.warning("rank-bm25 not installed — BM25Service will be non-functional. Run: pip install rank-bm25")


_STOPWORDS = frozenset([
    # ── Articles & determiners ──────────────────────────────────────────────
    "a", "an", "the", "this", "that", "these", "those", "some", "any",
    "every", "both", "either", "neither", "all", "each", "no", "own",
    "such", "same",
    # ── Personal pronouns ───────────────────────────────────────────────────
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves",
    "he", "him", "his", "himself", "she", "her", "hers", "herself",
    "it", "its", "itself", "they", "them", "their", "theirs", "themselves",
    # ── Interrogative / relative pronouns ───────────────────────────────────
    "what", "which", "who", "whom", "whose", "whoever", "whatever",
    "whichever",
    # ── Prepositions ────────────────────────────────────────────────────────
    "at", "by", "in", "of", "on", "to", "up", "as", "for", "or",
    "and", "but", "nor", "so", "yet",
    "from", "into", "onto", "upon", "with", "within", "without",
    "through", "throughout", "during", "before", "after",
    "above", "below", "between", "among", "against", "along",
    "around", "about", "near", "since", "until", "off", "out",
    "over", "under", "down", "here", "there", "per", "via",
    "across", "along", "beyond", "beside", "besides", "despite",
    "except", "inside", "outside", "regarding", "than",
    # ── Conjunctions & subordinators ────────────────────────────────────────
    "if", "when", "where", "whether", "whereas", "whenever", "wherever",
    "once", "unless", "although", "though", "while", "because", "since",
    "however", "therefore", "thus", "hence", "otherwise", "instead",
    "whereby", "thereby", "wherein", "therein",
    # ── Auxiliary & modal verbs ─────────────────────────────────────────────
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "do", "does", "did",
    "will", "would", "shall", "should", "may", "might", "must",
    "can", "could", "ought",
    # ── High-frequency adverbs with minimal signal ──────────────────────────
    "not", "now", "also", "back", "even", "still", "already", "always",
    "never", "ever", "quite", "rather", "almost", "else", "again",
    "indeed", "anyway", "perhaps", "maybe", "too", "very", "just",
    "so", "only", "more", "most", "less", "least", "far", "much",
    "yet", "soon", "often", "then", "thus", "hence", "thereby",
    "simply", "merely", "truly", "actually", "basically", "really",
    "generally", "typically", "usually", "certainly", "clearly",
    "probably", "likely", "particularly", "especially", "specifically",
    "relatively", "currently", "recently", "previously", "finally",
    "further", "furthermore", "moreover", "nevertheless", "nonetheless",
    "accordingly", "consequently", "subsequently",
    # ── Query filler words (very common in question phrasing) ───────────────
    "please", "thanks", "thank", "hi", "hey", "ok", "okay",
    "yes", "well", "like", "know", "thing", "things",
    "based", "related", "according", "including", "due",
    "given", "following", "across",
])


def _tokenize(text: str) -> list[str]:
    """Whitespace tokenizer with stopword removal for better BM25 precision."""
    return [
        t for t in text.lower().split()
        if t not in _STOPWORDS and len(t) > 1
    ]


class BM25Service:
    """Singleton BM25 index persisted to data/bm25_index.json."""

    _instance: "BM25Service | None" = None

    def __new__(cls) -> "BM25Service":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore[has-type]
            return
        # chunk_store: dict mapping chunk_id -> {"text": str, "metadata": dict}
        self._chunk_store: dict[str, dict[str, Any]] = {}
        self._bm25: "BM25Okapi | None" = None
        self._index_ids: list[str] = []  # ordered list of chunk ids matching BM25 corpus
        self._initialized = True
        self._load_from_disk()
        if self._chunk_store:
            self.rebuild_index()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load_from_disk(self) -> None:
        """Load chunk store from JSON. Handles missing file gracefully."""
        try:
            if _BM25_INDEX_PATH.exists():
                with open(_BM25_INDEX_PATH, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self._chunk_store = data if isinstance(data, dict) else {}
                logger.info("BM25 index loaded: %d chunks from %s", len(self._chunk_store), _BM25_INDEX_PATH)
        except FileNotFoundError:
            self._chunk_store = {}
        except Exception as exc:
            logger.warning("Failed to load BM25 index from disk: %s — starting fresh.", exc)
            self._chunk_store = {}

    def _save_to_disk(self) -> None:
        """Persist chunk store to JSON."""
        try:
            _BM25_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = _BM25_INDEX_PATH.with_suffix(".json.tmp")
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(self._chunk_store, fh, ensure_ascii=False)
            tmp_path.replace(_BM25_INDEX_PATH)
        except Exception as exc:
            logger.warning("Failed to persist BM25 index to disk: %s", exc)

    # ── Index Management ───────────────────────────────────────────────────────

    def add_chunks(self, chunks: list[dict]) -> None:
        """Add or update chunks in the index.

        Each chunk must have: {"id": str, "text": str, "metadata": dict}
        """
        if not chunks:
            return
        for chunk in chunks:
            chunk_id = chunk["id"]
            self._chunk_store[chunk_id] = {
                "text": chunk["text"],
                "metadata": chunk.get("metadata", {}),
            }
        self.rebuild_index()
        self._save_to_disk()
        logger.debug("BM25 index updated: %d total chunks after add.", len(self._chunk_store))

    def remove_document(self, document_id: str) -> None:
        """Remove all chunks for the given document_id from the index."""
        ids_to_remove = [
            cid for cid, entry in self._chunk_store.items()
            if entry.get("metadata", {}).get("document_id") == document_id
        ]
        if not ids_to_remove:
            return
        for cid in ids_to_remove:
            del self._chunk_store[cid]
        self.rebuild_index()
        self._save_to_disk()
        logger.debug("BM25 index: removed %d chunks for document %s.", len(ids_to_remove), document_id)

    def clear_all(self) -> None:
        """Remove all chunks and reset the index."""
        self._chunk_store.clear()
        self._corpus: list[str] = []
        self._ids: list[str] = []
        self._bm25 = None
        self._save_to_disk()
        logger.info("BM25 index cleared.")

    def rebuild_index(self) -> None:
        """Rebuild BM25Okapi index from the current chunk store."""
        if not _BM25_AVAILABLE:
            return
        if not self._chunk_store:
            self._bm25 = None
            self._index_ids = []
            return
        self._index_ids = list(self._chunk_store.keys())
        corpus = [_tokenize(self._chunk_store[cid]["text"]) for cid in self._index_ids]
        self._bm25 = BM25Okapi(corpus)

    # ── Search ─────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 10,
        filter_fn: Callable[[dict], bool] | None = None,
    ) -> list[dict]:
        """Return top_k chunks ranked by BM25 score.

        Returns list of {"id": str, "text": str, "metadata": dict, "score": float}.
        Returns empty list if index is empty or rank-bm25 is not installed.
        """
        if not _BM25_AVAILABLE or self._bm25 is None or not self._index_ids:
            return []

        query_tokens = _tokenize(query)
        scores = self._bm25.get_scores(query_tokens)

        # Build candidate list with scores
        candidates: list[tuple[float, str]] = [
            (float(scores[i]), cid)
            for i, cid in enumerate(self._index_ids)
        ]

        # Apply optional metadata filter
        if filter_fn is not None:
            candidates = [
                (score, cid)
                for score, cid in candidates
                if filter_fn(self._chunk_store[cid].get("metadata", {}))
            ]

        # Sort by score descending, take top_k
        candidates.sort(key=lambda x: x[0], reverse=True)
        candidates = candidates[:top_k]

        results: list[dict] = []
        for score, cid in candidates:
            entry = self._chunk_store[cid]
            results.append({
                "id": cid,
                "text": entry["text"],
                "metadata": entry.get("metadata", {}),
                "score": score,
            })
        return results
