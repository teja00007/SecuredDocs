"""Web URL / website scraper connector.

Crawls one or more seed URLs (with optional link-following) and extracts
clean article text using trafilatura.

Config JSON schema:
{
    "urls": ["https://docs.example.com"],
    "crawl_depth": 1,
    "include_pattern": "",
    "exclude_pattern": "",
    "user_agent": "NexusBot/1.0"
}
"""

import hashlib
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from src.connectors.base import BaseConnector
from src.models.connector import Connector

logger = logging.getLogger(__name__)

_MAX_URLS = 200


class WebConnector(BaseConnector):
    """Connector that fetches and cleans web pages from configured seed URLs."""

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

    def _build_headers(self) -> dict[str, str]:
        user_agent = self._config.get("user_agent", "NexusBot/1.0")
        return {"User-Agent": user_agent}

    @staticmethod
    def _same_domain(base_url: str, candidate_url: str) -> bool:
        """Return True if *candidate_url* shares the same netloc as *base_url*."""
        try:
            base_netloc = urlparse(base_url).netloc
            cand_netloc = urlparse(candidate_url).netloc
            return base_netloc == cand_netloc
        except Exception:
            return False

    def _passes_patterns(self, url: str) -> bool:
        """Return True if *url* passes include/exclude pattern filters."""
        include_pattern = self._config.get("include_pattern", "")
        exclude_pattern = self._config.get("exclude_pattern", "")
        if include_pattern:
            if not re.search(include_pattern, url):
                return False
        if exclude_pattern:
            if re.search(exclude_pattern, url):
                return False
        return True

    @staticmethod
    def _extract_links(html: str, page_url: str) -> list[str]:
        """Extract absolute hrefs from *html* using a simple regex approach."""
        from html.parser import HTMLParser

        class _LinkParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links: list[str] = []

            def handle_starttag(self, tag, attrs):
                if tag == "a":
                    for attr_name, attr_val in attrs:
                        if attr_name == "href" and attr_val:
                            self.links.append(attr_val)

        parser = _LinkParser()
        try:
            parser.feed(html)
        except Exception:
            pass

        absolute_links = []
        for href in parser.links:
            if href.startswith("#") or href.startswith("javascript:"):
                continue
            absolute = urljoin(page_url, href)
            # Strip fragments
            absolute = absolute.split("#")[0].rstrip("/")
            if absolute.startswith("http"):
                absolute_links.append(absolute)
        return list(set(absolute_links))

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Add https:// if the URL has no scheme."""
        url = url.strip()
        if url and not url.startswith(("http://", "https://")):
            url = "https://" + url
        return url

    async def list_documents(self) -> list[dict]:
        """Crawl seed URLs and return document descriptors."""
        seed_urls: list[str] = self._config.get("urls", [])
        crawl_depth: int = int(self._config.get("crawl_depth", 1))
        headers = self._build_headers()

        visited: set[str] = set()
        to_visit: list[tuple[str, str, int]] = []  # (url, origin_seed, depth_remaining)

        for seed in seed_urls:
            clean_seed = self._normalize_url(seed).rstrip("/")
            to_visit.append((clean_seed, clean_seed, crawl_depth))

        results: list[dict] = []

        async with httpx.AsyncClient(
            headers=headers, follow_redirects=True, timeout=30.0
        ) as client:
            while to_visit and len(visited) < _MAX_URLS:
                url, origin_seed, depth = to_visit.pop(0)

                if url in visited:
                    continue
                if not self._passes_patterns(url):
                    continue

                visited.add(url)

                try:
                    response = await client.get(url)
                    response.raise_for_status()
                except Exception as err:
                    logger.warning("WebConnector: failed to fetch %s: %s", url, err)
                    continue

                html = response.text

                # Extract clean text with trafilatura
                extracted = trafilatura.extract(
                    html,
                    include_links=False,
                    include_comments=False,
                    include_tables=True,
                )
                if not extracted or not extracted.strip():
                    logger.debug("WebConnector: no content extracted from %s", url)
                    # Still follow links if depth allows
                else:
                    content_hash = hashlib.md5(extracted.encode("utf-8")).hexdigest()

                    # Try to get a meaningful title
                    meta = trafilatura.extract_metadata(html)
                    title = (
                        (meta.title if meta and meta.title else None)
                        or url.split("/")[-1]
                        or url
                    )

                    results.append(
                        {
                            "external_id": url,
                            "title": title,
                            "url": url,
                            "modified_at": None,
                            "content_hash": content_hash,
                        }
                    )

                # Crawl deeper if depth allows
                if depth > 0:
                    for link in self._extract_links(html, url):
                        if link not in visited and self._same_domain(origin_seed, link):
                            to_visit.append((link, origin_seed, depth - 1))

        logger.info(
            "WebConnector: crawl complete — %d pages collected (limit=%d)",
            len(results),
            _MAX_URLS,
        )
        return results

    async def fetch_content(self, external_id: str) -> bytes:
        """Fetch and clean the web page at *external_id* (which is the URL).

        Returns UTF-8 encoded plain text extracted by trafilatura.
        """
        url = self._normalize_url(external_id)
        headers = self._build_headers()

        async with httpx.AsyncClient(
            headers=headers, follow_redirects=True, timeout=30.0
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        extracted = trafilatura.extract(
            html,
            include_links=False,
            include_comments=False,
            include_tables=True,
        )
        if not extracted:
            extracted = ""

        return extracted.encode("utf-8")
