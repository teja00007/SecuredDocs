"""AWS S3 connector — syncs files from an S3 bucket.

Config JSON schema:
{
    "bucket": "my-company-docs",
    "region": "us-east-1",
    "access_key_id": "AKIA...",
    "secret_access_key": "...",
    "prefix": "documents/"       (optional)
}
"""

import asyncio
import hashlib
import json
import logging
import os

from src.connectors.base import BaseConnector
from src.models.connector import Connector

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

_EXT_MAP = {
    ".pdf": ".pdf", ".txt": ".txt", ".md": ".md",
    ".docx": ".docx", ".xlsx": ".xlsx", ".pptx": ".pptx",
    ".doc": ".doc", ".xls": ".xls", ".ppt": ".ppt",
    ".html": ".html", ".htm": ".html", ".csv": ".csv",
    ".json": ".json", ".xml": ".xml", ".rtf": ".rtf",
}


class S3Connector(BaseConnector):
    """Connector that syncs files from an Amazon S3 bucket."""

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
        import boto3
        return boto3.client(
            "s3",
            region_name=self._config.get("region", "us-east-1"),
            aws_access_key_id=self._config["access_key_id"],
            aws_secret_access_key=self._config["secret_access_key"],
        )

    async def list_documents(self) -> list[dict]:
        bucket = self._config["bucket"]
        prefix = self._config.get("prefix", "") or ""
        client = await asyncio.to_thread(self._build_client)

        results: list[dict] = []

        def _list_all():
            paginator = client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
            items = []
            for page in pages:
                items.extend(page.get("Contents", []))
            return items

        try:
            objects = await asyncio.to_thread(_list_all)
        except Exception as err:
            logger.error("S3Connector: failed to list objects in '%s': %s", bucket, err)
            return []

        for obj in objects:
            key: str = obj["Key"]
            if key.endswith("/"):
                continue  # skip folder markers

            size = obj.get("Size", 0)
            if size > _MAX_FILE_SIZE_BYTES:
                logger.info("S3Connector: skipping '%s' (%d bytes) — exceeds 50 MB limit", key, size)
                continue

            etag = obj.get("ETag", "").strip('"')
            modified_at = obj.get("LastModified")
            content_hash = etag or hashlib.md5(f"{key}:{modified_at}".encode()).hexdigest()

            filename = os.path.basename(key) or key
            _, ext = os.path.splitext(filename)
            results.append({
                "external_id": key,
                "title": filename,
                "url": f"s3://{bucket}/{key}",
                "modified_at": modified_at.isoformat() if modified_at else None,
                "content_hash": content_hash,
                "_file_extension": ext.lower() if ext else ".bin",
            })

        logger.info("S3Connector: found %d files in s3://%s/%s", len(results), bucket, prefix)
        return results

    async def fetch_content(self, external_id: str) -> bytes:
        bucket = self._config["bucket"]
        client = await asyncio.to_thread(self._build_client)

        def _download():
            resp = client.get_object(Bucket=bucket, Key=external_id)
            return resp["Body"].read()

        return await asyncio.to_thread(_download)
