"""Abstract interfaces for all service dependencies.

All service code depends on these interfaces, never on concrete implementations.
This enables swapping implementations (e.g., ChromaDB → Qdrant) via configuration.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class ChunkResult:
    """A single chunk returned from vector search."""
    chunk_id: str
    document_id: str
    text: str
    metadata: dict
    score: float


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str
    model: str
    usage: dict  # {"prompt_tokens": int, "completion_tokens": int}


class IEmbeddingService(ABC):
    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        ...

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        ...


class IVectorStore(ABC):
    @abstractmethod
    async def insert(self, chunks: list[dict]) -> None:
        ...

    @abstractmethod
    async def search(
        self, embedding: list[float], filter: dict, top_k: int = 5
    ) -> list[ChunkResult]:
        ...

    @abstractmethod
    async def delete_by_document_id(self, document_id: str) -> int:
        ...

    @abstractmethod
    async def update_metadata(self, document_id: str, metadata: dict) -> None:
        ...

    @abstractmethod
    async def count(self) -> int:
        ...


class ILLM(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        ...

    async def stream(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Yield response tokens one at a time.

        Default implementation falls back to non-streaming generate so that
        providers which haven't implemented true streaming still work.
        """
        response = await self.generate(messages, temperature, max_tokens)
        yield response.content


class IDocumentRepository(ABC):
    @abstractmethod
    async def get_by_id(self, document_id: str):
        ...

    @abstractmethod
    async def list_accessible(self, user_id: str, skip: int = 0, limit: int = 20):
        ...

    @abstractmethod
    async def create(self, document):
        ...

    @abstractmethod
    async def update(self, document):
        ...

    @abstractmethod
    async def delete(self, document_id: str) -> None:
        ...


class IUserRepository(ABC):
    @abstractmethod
    async def get_by_id(self, user_id: str):
        ...

    @abstractmethod
    async def get_by_username(self, username: str):
        ...

    @abstractmethod
    async def get_by_email(self, email: str):
        ...

    @abstractmethod
    async def create(self, user):
        ...


class ITeamRepository(ABC):
    @abstractmethod
    async def get_by_id(self, team_id: str):
        ...

    @abstractmethod
    async def list_for_user(self, user_id: str):
        ...

    @abstractmethod
    async def create(self, team):
        ...

    @abstractmethod
    async def delete(self, team_id: str) -> None:
        ...

    @abstractmethod
    async def add_member(self, team_id: str, user_id: str) -> None:
        ...

    @abstractmethod
    async def remove_member(self, team_id: str, user_id: str) -> None:
        ...

    @abstractmethod
    async def get_documents_only_in_team(self, team_id: str) -> list:
        ...
