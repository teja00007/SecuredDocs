"""MinIO storage service — replaces local filesystem for document storage.

Features
--------
- Transparent upload/download via pre-signed URLs
- Multipart upload for files > MULTIPART_THRESHOLD (default 50 MB)
- Falls back to local filesystem when MinIO is not configured
  (STORAGE_BACKEND=local, which is the default)

Config (.env)
-------------
    STORAGE_BACKEND=minio          # or "local"
    MINIO_ENDPOINT=localhost:9000
    MINIO_ACCESS_KEY=minioadmin
    MINIO_SECRET_KEY=minioadmin
    MINIO_BUCKET=nexus-documents
    MINIO_SECURE=false             # true for HTTPS
    MINIO_PRESIGN_EXPIRES=3600     # seconds
    LOCAL_STORAGE_DIR=./data/uploads
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_MULTIPART_THRESHOLD = 50 * 1024 * 1024  # 50 MB


class StorageService:
    """Unified document storage that wraps MinIO or the local filesystem."""

    def __init__(
        self,
        backend: str = "local",
        # MinIO settings
        endpoint: str = "localhost:9000",
        access_key: str = "minioadmin",
        secret_key: str = "minioadmin",
        bucket: str = "nexus-documents",
        secure: bool = False,
        presign_expires: int = 3600,
        # Local settings
        local_dir: str = "./data/uploads",
    ) -> None:
        self._backend = backend.lower()
        self._endpoint = endpoint
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._secure = secure
        self._presign_expires = presign_expires
        self._local_dir = Path(local_dir)
        self._client = None  # lazy-init MinIO client

    # ── Public API ────────────────────────────────────────────────────────────

    async def upload(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload *data* and return the storage path / object key."""
        if self._backend == "minio":
            return await asyncio.to_thread(
                self._minio_upload, object_name, data, content_type
            )
        return await self._local_upload(object_name, data)

    async def download(self, object_name: str) -> bytes:
        """Download and return raw bytes for *object_name*."""
        if self._backend == "minio":
            return await asyncio.to_thread(self._minio_download, object_name)
        return await self._local_download(object_name)

    async def delete(self, object_name: str) -> None:
        """Delete the object from storage."""
        if self._backend == "minio":
            await asyncio.to_thread(self._minio_delete, object_name)
        else:
            await self._local_delete(object_name)

    async def presigned_url(self, object_name: str, expires: int | None = None) -> str:
        """Return a pre-signed download URL.

        For local backend this returns a placeholder path (pre-signed URLs
        are only meaningful with object storage).
        """
        if self._backend == "minio":
            return await asyncio.to_thread(
                self._minio_presigned, object_name, expires or self._presign_expires
            )
        return f"local://{self._local_dir / object_name}"

    async def presigned_upload_url(
        self, object_name: str, expires: int | None = None
    ) -> str:
        """Return a pre-signed PUT URL for direct client upload (MinIO only)."""
        if self._backend == "minio":
            return await asyncio.to_thread(
                self._minio_presigned_put, object_name, expires or self._presign_expires
            )
        raise NotImplementedError("Pre-signed upload URLs require STORAGE_BACKEND=minio")

    async def multipart_upload(
        self,
        object_name: str,
        file_path: str | Path,
        content_type: str = "application/octet-stream",
        part_size: int = 10 * 1024 * 1024,  # 10 MB parts
    ) -> str:
        """Stream a large file to MinIO using multipart upload.

        Falls back to regular upload for local backend.
        """
        path = Path(file_path)
        if self._backend != "minio":
            data = path.read_bytes()
            return await self.upload(object_name, data, content_type)

        return await asyncio.to_thread(
            self._minio_multipart_upload, object_name, path, content_type, part_size
        )

    # ── MinIO internals ───────────────────────────────────────────────────────

    def _get_minio_client(self):
        if self._client is not None:
            return self._client
        try:
            from minio import Minio
        except ImportError:
            raise RuntimeError(
                "minio SDK not installed. Run: pip install minio"
            )
        self._client = Minio(
            self._endpoint,
            access_key=self._access_key,
            secret_key=self._secret_key,
            secure=self._secure,
        )
        self._ensure_bucket()
        return self._client

    def _ensure_bucket(self) -> None:
        client = self._client
        if not client.bucket_exists(self._bucket):
            client.make_bucket(self._bucket)
            logger.info("Created MinIO bucket: %s", self._bucket)

    def _minio_upload(
        self, object_name: str, data: bytes, content_type: str
    ) -> str:
        client = self._get_minio_client()
        size = len(data)
        if size >= _MULTIPART_THRESHOLD:
            # Use put_object with a BytesIO — minio SDK handles multipart internally
            client.put_object(
                self._bucket,
                object_name,
                io.BytesIO(data),
                length=size,
                content_type=content_type,
                part_size=10 * 1024 * 1024,
            )
        else:
            client.put_object(
                self._bucket,
                object_name,
                io.BytesIO(data),
                length=size,
                content_type=content_type,
            )
        return object_name

    def _minio_multipart_upload(
        self,
        object_name: str,
        path: Path,
        content_type: str,
        part_size: int,
    ) -> str:
        client = self._get_minio_client()
        size = path.stat().st_size
        with open(path, "rb") as f:
            client.put_object(
                self._bucket,
                object_name,
                f,
                length=size,
                content_type=content_type,
                part_size=part_size,
            )
        return object_name

    def _minio_download(self, object_name: str) -> bytes:
        client = self._get_minio_client()
        response = client.get_object(self._bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def _minio_delete(self, object_name: str) -> None:
        client = self._get_minio_client()
        client.remove_object(self._bucket, object_name)

    def _minio_presigned(self, object_name: str, expires_seconds: int) -> str:
        from datetime import timedelta
        client = self._get_minio_client()
        return client.presigned_get_object(
            self._bucket, object_name, expires=timedelta(seconds=expires_seconds)
        )

    def _minio_presigned_put(self, object_name: str, expires_seconds: int) -> str:
        from datetime import timedelta
        client = self._get_minio_client()
        return client.presigned_put_object(
            self._bucket, object_name, expires=timedelta(seconds=expires_seconds)
        )

    # ── Local filesystem internals ────────────────────────────────────────────

    async def _local_upload(self, object_name: str, data: bytes) -> str:
        dest = self._local_dir / object_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(dest.write_bytes, data)
        return object_name

    async def _local_download(self, object_name: str) -> bytes:
        path = self._local_dir / object_name
        return await asyncio.to_thread(path.read_bytes)

    async def _local_delete(self, object_name: str) -> None:
        path = self._local_dir / object_name
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))


# ── Dependency injection helper ───────────────────────────────────────────────

def get_storage_service() -> StorageService:
    """FastAPI dependency — returns a configured StorageService."""
    from src.config import get_settings
    s = get_settings()
    return StorageService(
        backend=s.STORAGE_BACKEND,
        endpoint=s.MINIO_ENDPOINT,
        access_key=s.MINIO_ACCESS_KEY,
        secret_key=s.MINIO_SECRET_KEY,
        bucket=s.MINIO_BUCKET,
        secure=s.MINIO_SECURE,
        presign_expires=s.MINIO_PRESIGN_EXPIRES,
        local_dir=s.LOCAL_STORAGE_DIR,
    )
