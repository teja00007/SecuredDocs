"""Abstract base class for all external document connectors."""

from abc import ABC, abstractmethod

from src.models.connector import Connector


class BaseConnector(ABC):
    """All external connectors must implement this interface."""

    def __init__(self, connector: Connector, db_session) -> None:
        self.connector = connector
        self.db = db_session

    @abstractmethod
    async def list_documents(self) -> list[dict]:
        """Return a list of document descriptors from the remote source.

        Each dict must contain:
            external_id  (str) — unique identifier in the source system
            title        (str) — human-readable document title
            url          (str | None) — canonical URL to the document
            modified_at  (str | None) — ISO-8601 last-modified timestamp
            content_hash (str | None) — MD5 hex digest of content; used to
                                        skip re-ingestion when unchanged
        """
        ...

    @abstractmethod
    async def fetch_content(self, external_id: str) -> bytes:
        """Fetch raw content bytes for the document identified by *external_id*."""
        ...

    @property
    @abstractmethod
    def file_extension(self) -> str:
        """Default file extension (including leading dot) for this connector's output.

        Examples: ".txt", ".html", ".pdf"
        """
        ...
