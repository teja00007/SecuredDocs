"""Structural chunker: split on headings, keep each section as a chunk."""

from src.ingestion.chunkers.base import BaseChunker, Chunk
from src.ingestion.parsers.base import Section


class StructuralChunker(BaseChunker):
    """Chunk by document structure (headings/sections)."""

    def __init__(
        self,
        min_chunk_size: int = 50,
        max_chunk_size: int = 1024,
    ) -> None:
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str, metadata: dict) -> list[Chunk]:
        """Chunk using sections if available, otherwise fall back to recursive."""
        sections: list[Section] = metadata.pop("sections", [])

        if not sections:
            from src.ingestion.chunkers.recursive_chunker import RecursiveChunker
            return RecursiveChunker(
                min_chunk_size=self.min_chunk_size,
                max_chunk_size=self.max_chunk_size,
            ).chunk(text, metadata)

        chunks: list[Chunk] = []
        for i, section in enumerate(sections):
            section_text = ""
            if section.heading:
                section_text = f"{section.heading}\n\n{section.body}"
            else:
                section_text = section.body

            section_text = section_text.strip()
            if len(section_text) < self.min_chunk_size:
                continue

            # Split large sections
            if len(section_text) > self.max_chunk_size:
                sub_chunks = self._split_large(section_text, metadata, i)
                chunks.extend(sub_chunks)
            else:
                chunk_meta = dict(metadata)
                chunk_meta["chunk_index"] = i
                chunk_meta["section_heading"] = section.heading
                if section.page_number:
                    chunk_meta["page_number"] = section.page_number
                chunks.append(Chunk(
                    text=section_text,
                    metadata=chunk_meta,
                    token_count=len(section_text.split()),
                ))

        return chunks

    def _split_large(self, text: str, metadata: dict, base_index: int) -> list[Chunk]:
        from src.ingestion.chunkers.recursive_chunker import RecursiveChunker
        sub = RecursiveChunker(
            chunk_size=self.max_chunk_size,
            min_chunk_size=self.min_chunk_size,
            max_chunk_size=self.max_chunk_size,
        ).chunk(text, dict(metadata))
        for j, c in enumerate(sub):
            c.metadata["chunk_index"] = f"{base_index}.{j}"
        return sub
