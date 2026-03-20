"""Hierarchical (parent-child) chunker.

Strategy
--------
For each document the text is first split into large *parent* chunks
(~HIERARCHICAL_PARENT_SIZE chars).  Each parent chunk is then further split
into small *child* chunks (~HIERARCHICAL_CHILD_SIZE chars).

Only the child chunks are embedded and stored in the vector store.  The full
parent chunk text is stored in ``chunk.metadata["parent_text"]`` so that the
query pipeline can substitute the parent text when building the LLM context
window — giving the model much richer context than the narrow child chunk while
keeping embedding quality high.

Chunk metadata keys added:
  parent_text   : str   — full parent chunk text
  parent_index  : int   — index of the parent chunk (0-based)
  child_index   : int   — index of the child within the parent (0-based)
  chunk_index   : int   — global sequential index across all children

Usage:
    chunker = HierarchicalChunker(parent_size=1500, child_size=200)
    chunks  = chunker.chunk(text, metadata)
"""

from __future__ import annotations

import re

from src.ingestion.chunkers.base import BaseChunker, Chunk

_PARA_SEP = re.compile(r"\n\n+")
_SENTENCE_SEP = re.compile(r"(?<=[.!?])\s+")


def _split_by_size(text: str, target_size: int, overlap: int = 0) -> list[str]:
    """Split text into segments of ~target_size characters using paragraph boundaries."""
    paragraphs = _PARA_SEP.split(text)
    segments: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 2 <= target_size:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                segments.append(current)
                overlap_text = current[-overlap:] if overlap else ""
                current = (overlap_text + "\n\n" + para).strip() if overlap_text else para
            else:
                # Paragraph itself is larger than target_size — split by sentence
                sentences = _SENTENCE_SEP.split(para)
                for sent in sentences:
                    sent = sent.strip()
                    if not sent:
                        continue
                    if len(current) + len(sent) + 1 <= target_size:
                        current = (current + " " + sent).strip()
                    else:
                        if current:
                            segments.append(current)
                        current = sent

    if current:
        segments.append(current)

    return segments


class HierarchicalChunker(BaseChunker):
    """Split document into parent chunks, then child chunks within each parent.

    Child chunks carry ``parent_text`` in their metadata so the query pipeline
    can return the richer parent context to the LLM.
    """

    def __init__(
        self,
        parent_size: int = 1500,
        child_size: int = 200,
        child_overlap: int = 20,
        min_child_size: int = 30,
    ) -> None:
        self.parent_size = parent_size
        self.child_size = child_size
        self.child_overlap = child_overlap
        self.min_child_size = min_child_size

    def chunk(self, text: str, metadata: dict) -> list[Chunk]:
        if not text.strip():
            return []

        parent_segments = _split_by_size(text, self.parent_size, overlap=0)
        chunks: list[Chunk] = []
        global_index = 0

        for parent_idx, parent_text in enumerate(parent_segments):
            parent_text = parent_text.strip()
            if not parent_text:
                continue

            child_segments = _split_by_size(
                parent_text, self.child_size, overlap=self.child_overlap
            )

            for child_idx, child_text in enumerate(child_segments):
                child_text = child_text.strip()
                if len(child_text) < self.min_child_size:
                    continue

                chunk_meta = dict(metadata)
                chunk_meta["chunk_index"] = global_index
                chunk_meta["parent_index"] = parent_idx
                chunk_meta["child_index"] = child_idx
                chunk_meta["parent_text"] = parent_text

                chunks.append(
                    Chunk(
                        text=child_text,
                        metadata=chunk_meta,
                        token_count=len(child_text.split()),
                    )
                )
                global_index += 1

        return chunks
