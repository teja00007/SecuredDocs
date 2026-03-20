"""Confluence connector — syncs pages from one or more Confluence spaces.

Config JSON schema:
{
    "url": "https://yourcompany.atlassian.net",
    "username": "user@example.com",
    "api_token": "your-confluence-api-token",
    "space_keys": ["ENG", "PRODUCT"],
    "include_labels": [],
    "exclude_labels": []
}
"""

import asyncio
import hashlib
import json
import logging

from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector
from src.models.connector import Connector

logger = logging.getLogger(__name__)


class ConfluenceConnector(BaseConnector):
    """Connector that syncs Confluence wiki pages via the Atlassian REST API."""

    def __init__(self, connector: Connector, db_session) -> None:
        super().__init__(connector, db_session)
        raw_config = connector.config if isinstance(connector.config, dict) else {}
        if isinstance(connector.config, str):
            try:
                raw_config = json.loads(connector.config)
            except json.JSONDecodeError:
                raw_config = {}
        self._config = raw_config

    @property
    def file_extension(self) -> str:
        return ".txt"

    def _build_client(self):
        """Instantiate and return an atlassian.Confluence client."""
        from atlassian import Confluence

        # Accept both "base_url" (frontend key) and "url" (legacy key)
        url = self._config.get("base_url") or self._config.get("url", "")
        return Confluence(
            url=url,
            username=self._config["username"],
            password=self._config["api_token"],
            cloud=True,
        )

    def _page_passes_label_filters(self, page: dict) -> bool:
        """Return True if *page* passes the include/exclude label filters."""
        include_labels: list[str] = self._config.get("include_labels", [])
        exclude_labels: list[str] = self._config.get("exclude_labels", [])

        if not include_labels and not exclude_labels:
            return True

        # Confluence page label data may not be expanded in the initial listing;
        # we check whatever is available and fall through gracefully.
        labels_container = page.get("metadata", {}).get("labels", {}).get("results", [])
        page_labels = {lbl.get("name", "") for lbl in labels_container}

        if include_labels:
            if not page_labels.intersection(set(include_labels)):
                return False
        if exclude_labels:
            if page_labels.intersection(set(exclude_labels)):
                return False
        return True

    async def list_documents(self) -> list[dict]:
        """Return document descriptors for all matching Confluence pages."""
        confluence = self._build_client()
        space_keys: list[str] = self._config.get("space_keys", [])

        results: list[dict] = []

        for space_key in space_keys:
            logger.info(
                "ConfluenceConnector: listing pages in space '%s'", space_key
            )
            try:
                # Run the synchronous SDK call in a thread to keep the event loop free
                pages = await asyncio.to_thread(
                    confluence.get_all_pages_from_space,
                    space_key,
                    expand="version,metadata.labels",
                )
            except Exception as err:
                logger.error(
                    "ConfluenceConnector: failed to list pages in space '%s': %s",
                    space_key,
                    err,
                )
                continue

            for page in pages:
                if not self._page_passes_label_filters(page):
                    continue

                page_id = str(page.get("id", ""))
                page_title = page.get("title", page_id)

                # Build canonical URL
                base_url = (self._config.get("base_url") or self._config.get("url", "")).rstrip("/")
                page_url = f"{base_url}/wiki/spaces/{space_key}/pages/{page_id}"

                # Use version number as a cheap change indicator
                version_number = (
                    page.get("version", {}).get("number", 0)
                    if isinstance(page.get("version"), dict)
                    else 0
                )
                content_hash = hashlib.md5(
                    f"{page_id}:{version_number}".encode()
                ).hexdigest()

                results.append(
                    {
                        "external_id": page_id,
                        "title": page_title,
                        "url": page_url,
                        "modified_at": page.get("version", {}).get("when") if isinstance(page.get("version"), dict) else None,
                        "content_hash": content_hash,
                    }
                )

        logger.info(
            "ConfluenceConnector: found %d pages across %d spaces",
            len(results),
            len(space_keys),
        )
        return results

    async def fetch_content(self, external_id: str) -> bytes:
        """Fetch a Confluence page by ID and return its body as plain UTF-8 text."""
        confluence = self._build_client()
        page_id = external_id

        page = await asyncio.to_thread(
            confluence.get_page_by_id,
            page_id,
            expand="body.storage",
        )

        html_body: str = (
            page.get("body", {}).get("storage", {}).get("value", "")
            if isinstance(page, dict)
            else ""
        )

        # Strip HTML to get clean plain text
        soup = BeautifulSoup(html_body, "html.parser")
        plain_text = soup.get_text(separator="\n", strip=True)

        return plain_text.encode("utf-8")
