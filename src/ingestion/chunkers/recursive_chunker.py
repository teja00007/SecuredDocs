"""Recursive text chunker: paragraph → sentence → character fallback."""

import re

from src.ingestion.chunkers.base import BaseChunker, Chunk


_PARA_SEP = re.compile(r"\n\n+")
_SENTENCE_SEP = re.compile(r"(?<=[.!?])\s+")


class RecursiveChunker(BaseChunker):
    """Split by paragraph, then sentence, then character to meet size limits."""

    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        min_chunk_size: int = 50,
        max_chunk_size: int = 1024,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str, metadata: dict) -> list[Chunk]:
        if not text.strip():
            return []

        raw_chunks = self._split(text)
        chunks: list[Chunk] = []

        for i, chunk_text in enumerate(raw_chunks):
            chunk_text = chunk_text.strip()
            if len(chunk_text) < self.min_chunk_size:
                continue
            # Truncate oversized chunks
            if len(chunk_text) > self.max_chunk_size:
                chunk_text = chunk_text[: self.max_chunk_size]
            chunk_meta = dict(metadata)
            chunk_meta["chunk_index"] = i
            chunks.append(Chunk(
                text=chunk_text,
                metadata=chunk_meta,
                token_count=len(chunk_text.split()),
            ))

        return chunks

    def _split(self, text: str) -> list[str]:
        """Split text into chunks of ~chunk_size characters with overlap."""
        paragraphs = _PARA_SEP.split(text)
        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current) + len(para) + 2 <= self.chunk_size:
                current = (current + "\n\n" + para).strip()
            else:
                if current:
                    chunks.append(current)
                    # Overlap: keep last overlap chars
                    overlap = current[-self.chunk_overlap:] if self.chunk_overlap else ""
                    current = (overlap + "\n\n" + para).strip() if overlap else para
                else:
                    # Para itself too long — split by sentence
                    sentences = _SENTENCE_SEP.split(para)
                    for sent in sentences:
                        sent = sent.strip()
                        if not sent:
                            continue
                        if len(current) + len(sent) + 1 <= self.chunk_size:
                            current = (current + " " + sent).strip()
                        else:
                            if current:
                                chunks.append(current)
                            current = sent

        if current:
            chunks.append(current)

        return chunks
