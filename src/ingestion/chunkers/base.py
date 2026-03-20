"""Abstract base classes for text chunkers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Chunk:
    """A single text chunk ready for embedding."""
    text: str
    metadata: dict = field(default_factory=dict)
    token_count: int = 0


class BaseChunker(ABC):
    """Abstract chunker interface."""

    @abstractmethod
    def chunk(self, text: str, metadata: dict) -> list[Chunk]:
        """Split text into chunks, preserving metadata in each chunk."""
        ...
