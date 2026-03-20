"""Azure Blob Storage / Data Lake connector — syncs files from an Azure container.

Config JSON schema:
{
    "account_name": "mycompanystorage",
    "container": "documents",
    "sas_token": "sv=2020-08-04&ss=b&srt=co&sp=rl...",
    "prefix": "data/raw/"       (optional)
}
"""

import asyncio
import json
import logging
import os

from src.connectors.base import BaseConnector
from src.models.connector import Connector

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


class AzureConnector(BaseConnector):
    """Connector that syncs files from Azure Blob Storage / Data Lake Gen2."""

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
        return ".bin"

    def _build_container_client(self):
        from azure.storage.blob import ContainerClient
        account = self._config["account_name"]
        container = self._config["container"]
        sas_token = self._config["sas_token"].lstrip("?")
        url = f"https://{account}.blob.core.windows.net/{container}?{sas_token}"
        return ContainerClient.from_container_url(url)

    async def list_documents(self) -> list[dict]:
        prefix = self._config.get("prefix", "") or ""
        container_client = await asyncio.to_thread(self._build_container_client)

        def _list_all():
            blobs = []
            for blob in container_client.list_blobs(name_starts_with=prefix or None):
                blobs.append(blob)
            return blobs

        try:
            blobs = await asyncio.to_thread(_list_all)
        except Exception as err:
            logger.error("AzureConnector: failed to list blobs: %s", err)
            return []

        results: list[dict] = []
        account = self._config["account_name"]
        container = self._config["container"]

        for blob in blobs:
            name: str = blob["name"]
            if name.endswith("/"):
                continue

            size = blob.get("size", 0)
            if size and size > _MAX_FILE_SIZE_BYTES:
                logger.info("AzureConnector: skipping '%s' (%d bytes) — exceeds 50 MB limit", name, size)
                continue

            etag = (blob.get("etag") or "").strip('"')
            modified_at = blob.get("last_modified")
            content_hash = etag or f"{name}:{modified_at}"

            filename = os.path.basename(name) or name
            _, ext = os.path.splitext(filename)
            results.append({
                "external_id": name,
                "title": filename,
                "url": f"https://{account}.blob.core.windows.net/{container}/{name}",
                "modified_at": modified_at.isoformat() if modified_at else None,
                "content_hash": content_hash,
                "_file_extension": ext.lower() if ext else ".bin",
            })

        logger.info("AzureConnector: found %d blobs in container '%s'", len(results), container)
        return results

    async def fetch_content(self, external_id: str) -> bytes:
        container_client = await asyncio.to_thread(self._build_container_client)

        def _download():
            blob_client = container_client.get_blob_client(external_id)
            return blob_client.download_blob().readall()

        return await asyncio.to_thread(_download)
