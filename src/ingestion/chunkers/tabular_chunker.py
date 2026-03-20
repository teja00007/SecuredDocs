"""Tabular chunker: group rows into chunks with column headers prepended."""

from src.ingestion.chunkers.base import BaseChunker, Chunk


class TabularChunker(BaseChunker):
    """Chunk CSV/XLSX content by grouping rows, always prepending headers."""

    def __init__(
        self,
        rows_per_chunk: int = 20,
        min_chunk_size: int = 50,
        max_chunk_size: int = 1024,
    ) -> None:
        self.rows_per_chunk = rows_per_chunk
        self.min_chunk_size = min_chunk_size
        self.max_chunk_size = max_chunk_size

    def chunk(self, text: str, metadata: dict) -> list[Chunk]:
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        header = lines[0]
        data_rows = lines[1:]

        if not data_rows:
            return []

        chunks: list[Chunk] = []
        for i in range(0, len(data_rows), self.rows_per_chunk):
            batch = data_rows[i: i + self.rows_per_chunk]
            chunk_text = header + "\n" + "\n".join(batch)

            if len(chunk_text) < self.min_chunk_size:
                continue
            if len(chunk_text) > self.max_chunk_size:
                chunk_text = chunk_text[: self.max_chunk_size]

            chunk_meta = dict(metadata)
            chunk_meta["chunk_index"] = i // self.rows_per_chunk
            chunk_meta["row_start"] = i + 1
            chunk_meta["row_end"] = i + len(batch)

            chunks.append(Chunk(
                text=chunk_text,
                metadata=chunk_meta,
                token_count=len(chunk_text.split()),
            ))

        return chunks
