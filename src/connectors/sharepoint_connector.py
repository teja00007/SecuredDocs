"""SharePoint connector — syncs files from a SharePoint site via Microsoft Graph API.

Config JSON schema:
{
    "site_url": "https://mycompany.sharepoint.com/sites/Docs",
    "client_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "client_secret": "..."
}

Prerequisites:
- Register an Azure AD app with Sites.Read.All and Files.Read.All application permissions.
- Grant admin consent for the permissions.
- Use the tenant ID from the Azure portal (extracted from the SharePoint URL domain).
"""

import asyncio
import json
import logging
import os
import re

import httpx

from src.connectors.base import BaseConnector
from src.models.connector import Connector

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class SharePointConnector(BaseConnector):
    """Connector that syncs files from a SharePoint site via Microsoft Graph API."""

    def __init__(self, connector: Connector, db_session) -> None:
        super().__init__(connector, db_session)
        raw_config = connector.config if isinstance(connector.config, dict) else {}
        if isinstance(connector.config, str):
            try:
                raw_config = json.loads(connector.config)
            except json.JSONDecodeError:
                raw_config = {}
        self._config = raw_config
        self._token: str | None = None

    @property
    def file_extension(self) -> str:
        return ".bin"

    def _extract_tenant(self) -> str:
        """Extract tenant domain from site_url (e.g. mycompany.sharepoint.com → mycompany)."""
        site_url = self._config.get("site_url", "")
        match = re.search(r"https?://([^.]+)\.sharepoint\.com", site_url)
        if match:
            return match.group(1) + ".onmicrosoft.com"
        raise ValueError(f"Cannot extract tenant from site_url: {site_url!r}")

    async def _get_token(self) -> str:
        if self._token:
            return self._token
        tenant = self._extract_tenant()
        client_id = self._config["client_id"]
        client_secret = self._config["client_secret"]
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            })
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
        return self._token

    async def _get_site_id(self, token: str) -> str:
        """Resolve the SharePoint site URL to a Graph site ID."""
        site_url = self._config.get("site_url", "")
        # Extract hostname and path
        match = re.match(r"https?://([^/]+)(/.+)?", site_url)
        if not match:
            raise ValueError(f"Invalid site_url: {site_url!r}")
        hostname = match.group(1)
        path = (match.group(2) or "").rstrip("/")
        graph_url = f"{_GRAPH_BASE}/sites/{hostname}:{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(graph_url, headers={"Authorization": f"Bearer {token}"})
            resp.raise_for_status()
            return resp.json()["id"]

    async def _list_drive_items(self, token: str, site_id: str) -> list[dict]:
        """Recursively list all files in the default document library."""
        items: list[dict] = []
        headers = {"Authorization": f"Bearer {token}"}

        async def _fetch_folder(url: str) -> None:
            async with httpx.AsyncClient(timeout=30) as client:
                while url:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    for item in data.get("value", []):
                        if "folder" in item:
                            child_url = f"{_GRAPH_BASE}/sites/{site_id}/drive/items/{item['id']}/children"
                            await _fetch_folder(child_url)
                        elif "file" in item:
                            items.append(item)
                    url = data.get("@odata.nextLink")

        root_url = f"{_GRAPH_BASE}/sites/{site_id}/drive/root/children"
        await _fetch_folder(root_url)
        return items

    async def list_documents(self) -> list[dict]:
        try:
            token = await self._get_token()
            site_id = await self._get_site_id(token)
            raw_items = await self._list_drive_items(token, site_id)
        except Exception as err:
            logger.error("SharePointConnector: failed to list files: %s", err)
            return []

        results: list[dict] = []
        for item in raw_items:
            size = item.get("size", 0)
            if size > _MAX_FILE_SIZE_BYTES:
                logger.info("SharePointConnector: skipping '%s' (%d bytes) — exceeds 50 MB limit", item.get("name"), size)
                continue

            file_id = item["id"]
            name = item.get("name", file_id)
            web_url = item.get("webUrl")
            modified_at = item.get("lastModifiedDateTime")
            etag = item.get("eTag", "").strip('"')
            content_hash = etag or f"{file_id}:{modified_at}"

            results.append({
                "external_id": file_id,
                "title": name,
                "url": web_url,
                "modified_at": modified_at,
                "content_hash": content_hash,
            })

        logger.info("SharePointConnector: found %d files", len(results))
        return results

    async def fetch_content(self, external_id: str) -> bytes:
        token = await self._get_token()
        site_id = await self._get_site_id(token)
        download_url_resp = f"{_GRAPH_BASE}/sites/{site_id}/drive/items/{external_id}"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            meta_resp = await client.get(download_url_resp, headers=headers)
            meta_resp.raise_for_status()
            download_url = meta_resp.json().get("@microsoft.graph.downloadUrl")
            if not download_url:
                raise ValueError(f"No download URL for item {external_id}")
            content_resp = await client.get(download_url)
            content_resp.raise_for_status()
            return content_resp.content
