"""Tests for src/services/storage_service.py — local filesystem backend."""

import pytest
from pathlib import Path

from src.services.storage_service import StorageService


@pytest.fixture
def local_storage(tmp_path) -> StorageService:
    return StorageService(backend="local", local_dir=str(tmp_path / "storage"))


class TestLocalUpload:
    @pytest.mark.asyncio
    async def test_upload_creates_file(self, local_storage, tmp_path):
        key = await local_storage.upload("docs/test.txt", b"hello world")
        assert key == "docs/test.txt"
        stored = Path(tmp_path / "storage" / "docs" / "test.txt")
        assert stored.exists()
        assert stored.read_bytes() == b"hello world"

    @pytest.mark.asyncio
    async def test_download_returns_bytes(self, local_storage):
        await local_storage.upload("file.bin", b"\x00\x01\x02")
        data = await local_storage.download("file.bin")
        assert data == b"\x00\x01\x02"

    @pytest.mark.asyncio
    async def test_delete_removes_file(self, local_storage, tmp_path):
        await local_storage.upload("del.txt", b"bye")
        await local_storage.delete("del.txt")
        assert not (tmp_path / "storage" / "del.txt").exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(self, local_storage):
        # Should not raise
        await local_storage.delete("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_presigned_url_local(self, local_storage, tmp_path):
        url = await local_storage.presigned_url("report.pdf")
        assert "local://" in url
        assert "report.pdf" in url

    @pytest.mark.asyncio
    async def test_presigned_upload_url_raises_for_local(self, local_storage):
        with pytest.raises(NotImplementedError):
            await local_storage.presigned_upload_url("upload.pdf")

    @pytest.mark.asyncio
    async def test_multipart_upload_falls_back_to_regular(self, local_storage, tmp_path):
        src = tmp_path / "large.bin"
        src.write_bytes(b"A" * 1024)
        key = await local_storage.multipart_upload("large.bin", src)
        assert key == "large.bin"
        data = await local_storage.download("large.bin")
        assert data == b"A" * 1024

    @pytest.mark.asyncio
    async def test_upload_nested_dirs_created(self, local_storage, tmp_path):
        await local_storage.upload("a/b/c/deep.txt", b"deep")
        assert (tmp_path / "storage" / "a" / "b" / "c" / "deep.txt").exists()
