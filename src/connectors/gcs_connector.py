"""Google Cloud Storage connector — syncs files from a GCS bucket.

Config JSON schema:
{
    "bucket": "my-company-docs",
    "credentials_json": "{...service account JSON...}",
    "prefix": "documents/"       (optional)
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


class GCSConnector(BaseConnector):
    """Connector that syncs files from a Google Cloud Storage bucket."""

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

    def _build_client(self):
        from google.cloud import storage
        from google.oauth2 import service_account

        creds_raw = self._config.get("credentials_json", {})
        if isinstance(creds_raw, str):
            creds_raw = json.loads(creds_raw)

        credentials = service_account.Credentials.from_service_account_info(
            creds_raw,
            scopes=["https://www.googleapis.com/auth/devstorage.read_only"],
        )
        return storage.Client(credentials=credentials, project=creds_raw.get("project_id"))

    async def list_documents(self) -> list[dict]:
        bucket_name = self._config["bucket"]
        prefix = self._config.get("prefix", "") or ""
        client = await asyncio.to_thread(self._build_client)

        def _list_all():
            bucket = client.bucket(bucket_name)
            return list(client.list_blobs(bucket, prefix=prefix or None))

        try:
            blobs = await asyncio.to_thread(_list_all)
        except Exception as err:
            logger.error("GCSConnector: failed to list blobs in '%s': %s", bucket_name, err)
            return []

        results: list[dict] = []
        for blob in blobs:
            if blob.name.endswith("/"):
                continue

            size = blob.size or 0
            if size > _MAX_FILE_SIZE_BYTES:
                logger.info("GCSConnector: skipping '%s' (%d bytes) — exceeds 50 MB limit", blob.name, size)
                continue

            content_hash = blob.md5_hash or blob.etag or blob.name
            modified_at = blob.updated

            filename = os.path.basename(blob.name) or blob.name
            _, ext = os.path.splitext(filename)
            results.append({
                "external_id": blob.name,
                "title": filename,
                "url": f"gs://{bucket_name}/{blob.name}",
                "modified_at": modified_at.isoformat() if modified_at else None,
                "content_hash": content_hash,
                "_file_extension": ext.lower() if ext else ".bin",
            })

        logger.info("GCSConnector: found %d files in gs://%s/%s", len(results), bucket_name, prefix)
        return results

    async def fetch_content(self, external_id: str) -> bytes:
        bucket_name = self._config["bucket"]
        client = await asyncio.to_thread(self._build_client)

        def _download():
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(external_id)
            return blob.download_as_bytes()

        return await asyncio.to_thread(_download)
