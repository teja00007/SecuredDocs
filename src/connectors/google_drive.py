"""Google Drive connector — syncs files from one or more Drive folders.

Config JSON schema:
{
    "service_account_json": "{...json string or dict...}",
    "folder_ids": ["folder_id_1", "folder_id_2"],
    "include_shared_drives": false,
    "file_types": [
        "application/pdf",
        "application/vnd.google-apps.document",
        "text/plain"
    ]
}
"""

import asyncio
import hashlib
import io
import json
import logging

from src.connectors.base import BaseConnector
from src.models.connector import Connector

logger = logging.getLogger(__name__)

# Maximum file size (in bytes) that will be downloaded — 50 MB
_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024

# Google native MIME types that must be exported rather than downloaded directly
_GOOGLE_NATIVE_MIME_TYPES = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.drawing",
}

# MIME-type → file extension mapping for non-Google files
_MIME_TO_EXT = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/html": ".html",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/rtf": ".rtf",
    "application/zip": ".zip",
}

# File fields requested from the Drive API
_FILE_FIELDS = (
    "id,name,mimeType,size,modifiedTime,webViewLink,md5Checksum,parents"
)


class GoogleDriveConnector(BaseConnector):
    """Connector that syncs files from Google Drive via the Drive API v3."""

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
        # Google-native docs are exported to PDF; default extension is PDF.
        return ".pdf"

    def _get_service_account_info(self) -> dict:
        """Parse and return the service-account credentials dict."""
        sa_json = self._config.get("service_account_json", {})
        if isinstance(sa_json, str):
            try:
                return json.loads(sa_json)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "GoogleDriveConnector: 'service_account_json' is not valid JSON."
                ) from exc
        if isinstance(sa_json, dict):
            return sa_json
        raise ValueError(
            "GoogleDriveConnector: 'service_account_json' must be a JSON string or dict."
        )

    def _build_service(self):
        """Instantiate and return a Drive API v3 service object."""
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/drive.readonly"]
        credentials = service_account.Credentials.from_service_account_info(
            self._get_service_account_info(),
            scopes=scopes,
        )
        service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return service

    def _ext_for_mime(self, mime_type: str) -> str:
        """Return a file extension for *mime_type*.

        Google-native types map to .pdf (they are exported as PDF).
        All other types use the _MIME_TO_EXT lookup, falling back to .bin.
        """
        if mime_type in _GOOGLE_NATIVE_MIME_TYPES:
            return ".pdf"
        return _MIME_TO_EXT.get(mime_type, ".bin")

    def _list_files_in_folder(self, service, folder_id: str) -> list[dict]:
        """Return all matching files inside *folder_id*, handling pagination."""
        file_types: list[str] = self._config.get("file_types", [])
        include_shared = self._config.get("include_shared_drives", False)

        # Build the MIME-type filter clause
        if file_types:
            mime_clauses = " or ".join(
                f"mimeType='{mt}'" for mt in file_types
            )
            type_filter = f" and ({mime_clauses})"
        else:
            type_filter = ""

        query = (
            f"'{folder_id}' in parents"
            f" and trashed = false"
            f"{type_filter}"
        )

        kwargs = {
            "q": query,
            "fields": f"nextPageToken, files({_FILE_FIELDS})",
            "pageSize": 100,
            "supportsAllDrives": include_shared,
            "includeItemsFromAllDrives": include_shared,
        }

        files: list[dict] = []
        page_token = None

        while True:
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.files().list(**kwargs).execute()
            batch = response.get("files", [])
            files.extend(batch)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return files

    def _list_all_my_drive_files(self, service) -> list[dict]:
        """Return all matching files from My Drive (no folder restriction)."""
        file_types: list[str] = self._config.get("file_types", [])
        include_shared = self._config.get("include_shared_drives", False)

        if file_types:
            mime_clauses = " or ".join(
                f"mimeType='{mt}'" for mt in file_types
            )
            query = f"trashed = false and ({mime_clauses})"
        else:
            query = "trashed = false"

        kwargs = {
            "q": query,
            "fields": f"nextPageToken, files({_FILE_FIELDS})",
            "pageSize": 100,
            "supportsAllDrives": include_shared,
            "includeItemsFromAllDrives": include_shared,
        }

        files: list[dict] = []
        page_token = None

        while True:
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.files().list(**kwargs).execute()
            batch = response.get("files", [])
            files.extend(batch)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return files

    async def list_documents(self) -> list[dict]:
        """Return document descriptors for all matching Drive files."""
        service = await asyncio.to_thread(self._build_service)
        folder_ids: list[str] = self._config.get("folder_ids", [])

        raw_files: list[dict] = []

        if folder_ids:
            for folder_id in folder_ids:
                logger.info(
                    "GoogleDriveConnector: listing files in folder '%s'", folder_id
                )
                try:
                    batch = await asyncio.to_thread(
                        self._list_files_in_folder, service, folder_id
                    )
                    raw_files.extend(batch)
                except Exception as err:
                    logger.error(
                        "GoogleDriveConnector: failed to list files in folder '%s': %s",
                        folder_id,
                        err,
                    )
                    continue
        else:
            logger.info("GoogleDriveConnector: no folder_ids specified — listing all My Drive files")
            try:
                raw_files = await asyncio.to_thread(
                    self._list_all_my_drive_files, service
                )
            except Exception as err:
                logger.error(
                    "GoogleDriveConnector: failed to list My Drive files: %s", err
                )

        # Deduplicate by file id (a file can appear in multiple folder queries)
        seen_ids: set[str] = set()
        results: list[dict] = []

        for file in raw_files:
            file_id = file.get("id", "")
            if not file_id or file_id in seen_ids:
                continue
            seen_ids.add(file_id)

            # Skip files exceeding the size limit (Google-native docs report no size)
            raw_size = file.get("size")
            if raw_size is not None:
                try:
                    if int(raw_size) > _MAX_FILE_SIZE_BYTES:
                        logger.info(
                            "GoogleDriveConnector: skipping '%s' (%s bytes) — exceeds 50 MB limit",
                            file.get("name", file_id),
                            raw_size,
                        )
                        continue
                except (ValueError, TypeError):
                    pass

            mime_type = file.get("mimeType", "")
            title = file.get("name", file_id)
            url = file.get("webViewLink")
            modified_at = file.get("modifiedTime")

            # Prefer the server-supplied MD5; fall back to hashing id+modifiedTime
            md5 = file.get("md5Checksum")
            if md5:
                content_hash = md5
            else:
                content_hash = hashlib.md5(
                    f"{file_id}:{modified_at}".encode()
                ).hexdigest()

            results.append(
                {
                    "external_id": file_id,
                    "title": title,
                    "url": url,
                    "modified_at": modified_at,
                    "content_hash": content_hash,
                    # Store mime_type so fetch_content can decide export vs download
                    "_mime_type": mime_type,
                    # Per-document extension (Google-native → .pdf, others → original ext)
                    "_file_extension": self._ext_for_mime(mime_type),
                }
            )

        logger.info(
            "GoogleDriveConnector: found %d files (folders queried: %s)",
            len(results),
            folder_ids or ["My Drive"],
        )
        return results

    async def fetch_content(self, external_id: str) -> bytes:
        """Download or export the Drive file identified by *external_id*.

        - Google-native documents (Docs, Sheets, Slides, Drawings) are exported
          as PDF via the Drive export endpoint.
        - All other files are downloaded directly using the media download endpoint.
        """
        service = await asyncio.to_thread(self._build_service)

        # Retrieve the file's metadata to determine its MIME type
        file_meta = await asyncio.to_thread(
            lambda: service.files()
            .get(fileId=external_id, fields="id,name,mimeType,size", supportsAllDrives=True)
            .execute()
        )

        mime_type = file_meta.get("mimeType", "")
        file_name = file_meta.get("name", external_id)

        if mime_type in _GOOGLE_NATIVE_MIME_TYPES:
            # Export Google-native document as PDF
            logger.info(
                "GoogleDriveConnector: exporting '%s' (%s) as PDF", file_name, mime_type
            )
            content_bytes = await asyncio.to_thread(
                self._export_as_pdf, service, external_id, file_name
            )
        else:
            # Direct binary download
            logger.info(
                "GoogleDriveConnector: downloading '%s' (%s)", file_name, mime_type
            )
            content_bytes = await asyncio.to_thread(
                self._download_file, service, external_id, file_name
            )

        return content_bytes

    def _export_as_pdf(self, service, file_id: str, file_name: str) -> bytes:
        """Export a Google-native document as PDF and return raw bytes."""
        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().export_media(
            fileId=file_id, mimeType="application/pdf"
        )
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def _download_file(self, service, file_id: str, file_name: str) -> bytes:
        """Download a non-Google-native file and return raw bytes."""
        from googleapiclient.http import MediaIoBaseDownload

        request = service.files().get_media(
            fileId=file_id, supportsAllDrives=True
        )
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()
