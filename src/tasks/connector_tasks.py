"""Celery tasks: sync individual connectors and periodically sync all active connectors."""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_CONNECTOR_UPLOAD_DIR = Path("data/connector_uploads")

SUPPORTED_CONNECTOR_TYPES = (
    "google_drive", "confluence", "web_url", "notion",
    "aws_s3", "azure_data_lake", "gcs", "sharepoint",
)


def _get_connector_class(connector_type: str):
    """Return the connector implementation class for *connector_type*."""
    if connector_type == "web_url":
        from src.connectors.web_connector import WebConnector
        return WebConnector
    if connector_type == "confluence":
        from src.connectors.confluence_connector import ConfluenceConnector
        return ConfluenceConnector
    if connector_type == "google_drive":
        from src.connectors.google_drive import GoogleDriveConnector
        return GoogleDriveConnector
    if connector_type == "aws_s3":
        from src.connectors.s3_connector import S3Connector
        return S3Connector
    if connector_type == "azure_data_lake":
        from src.connectors.azure_connector import AzureConnector
        return AzureConnector
    if connector_type == "gcs":
        from src.connectors.gcs_connector import GCSConnector
        return GCSConnector
    if connector_type == "sharepoint":
        from src.connectors.sharepoint_connector import SharePointConnector
        return SharePointConnector
    raise NotImplementedError(
        f"Connector type '{connector_type}' is not yet implemented. "
        f"Supported: {list(SUPPORTED_CONNECTOR_TYPES)}"
    )


def _run_sync(connector_id: str) -> None:
    """Build services and run the async sync pipeline in a new event loop."""
    from src.config import Settings
    from src.db.session import get_async_engine, get_session_factory

    settings = Settings()
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    async def _async_sync() -> None:
        from sqlalchemy import select

        from src.models.connector import Connector, ConnectorDocument
        from src.models.document import Document

        async with factory() as session:
            # 1. Load the connector record
            result = await session.execute(
                select(Connector).where(Connector.id == connector_id)
            )
            connector = result.scalar_one_or_none()
            if connector is None:
                logger.error("Connector %s not found — aborting sync", connector_id)
                return

            if connector.status == "paused":
                logger.info("Connector %s is paused — skipping sync", connector_id)
                return

            logger.info(
                "Starting sync for connector %s (%s)", connector.name, connector.type
            )

            try:
                # 2. Instantiate the appropriate connector class
                connector_cls = _get_connector_class(connector.type)
                impl = connector_cls(connector=connector, db_session=session)

                # 3. List all current documents from the remote source
                remote_docs = await impl.list_documents()
                logger.info(
                    "Connector %s found %d remote documents", connector.name, len(remote_docs)
                )

                synced_count = 0

                for doc_info in remote_docs:
                    external_id: str = doc_info["external_id"]
                    title: str = doc_info.get("title", external_id)
                    url: str | None = doc_info.get("url")
                    remote_hash: str | None = doc_info.get("content_hash")

                    # 4a. Look up existing ConnectorDocument record
                    cd_result = await session.execute(
                        select(ConnectorDocument).where(
                            ConnectorDocument.connector_id == connector_id,
                            ConnectorDocument.external_id == external_id,
                        )
                    )
                    connector_doc = cd_result.scalar_one_or_none()

                    # 4b. Skip if unchanged (hash matches)
                    if (
                        connector_doc is not None
                        and remote_hash is not None
                        and connector_doc.content_hash == remote_hash
                    ):
                        logger.debug(
                            "Connector %s: skipping unchanged doc '%s'",
                            connector.name,
                            external_id,
                        )
                        continue

                    # 4c. Fetch content and ingest
                    try:
                        raw_content: bytes = await impl.fetch_content(external_id)
                    except Exception as fetch_err:
                        logger.warning(
                            "Connector %s: failed to fetch '%s': %s",
                            connector.name,
                            external_id,
                            fetch_err,
                        )
                        continue

                    # Compute actual content hash from the fetched bytes
                    actual_hash = hashlib.md5(raw_content).hexdigest()

                    # Skip if content is identical to what we already have
                    if (
                        connector_doc is not None
                        and connector_doc.content_hash == actual_hash
                    ):
                        continue

                    # Use per-document extension when available (e.g. .docx, .jpg)
                    # falling back to the connector default (e.g. .pdf for Google-native exports)
                    file_ext = doc_info.get("_file_extension") or impl.file_extension

                    # Save content to disk
                    safe_name = (
                        title[:64].replace("/", "_").replace("\\", "_") + file_ext
                    )
                    doc_dir = _CONNECTOR_UPLOAD_DIR / connector_id
                    doc_dir.mkdir(parents=True, exist_ok=True)

                    # Use external_id hash as folder name to avoid path collisions
                    folder_name = hashlib.md5(external_id.encode()).hexdigest()
                    file_dir = doc_dir / folder_name
                    file_dir.mkdir(parents=True, exist_ok=True)
                    file_path = file_dir / safe_name
                    file_path.write_bytes(raw_content)

                    # Create or reuse a Document record
                    if connector_doc is not None and connector_doc.document_id:
                        document_id = connector_doc.document_id
                    else:
                        document_id = str(uuid.uuid4())
                        new_doc = Document(
                            id=document_id,
                            filename=safe_name,
                            file_type=file_ext,
                            file_size=len(raw_content),
                            visibility="public",
                            collection_id=connector.collection_id,
                            owner_id=connector.owner_id,
                            file_path=str(file_path),
                            status="pending",
                            current_version=1,
                        )
                        session.add(new_doc)
                        await session.flush()

                    # Build visibility metadata
                    visibility_metadata = {
                        "owner_id": connector.owner_id,
                        "filename": safe_name,
                        "visibility": "public",
                        "chunking_strategy": None,
                        "collection_id": connector.collection_id or "",
                        "allowed_teams": (
                            f"|{connector.team_id}|" if connector.team_id else ""
                        ),
                        "allowed_users": "",
                    }

                    # Dispatch ingestion task
                    from src.tasks.ingestion_tasks import ingest_document_task
                    ingest_document_task.delay(
                        document_id,
                        str(file_path),
                        impl.file_extension,
                        visibility_metadata,
                    )

                    # 4d. Upsert ConnectorDocument record
                    if connector_doc is None:
                        connector_doc = ConnectorDocument(
                            id=str(uuid.uuid4()),
                            connector_id=connector_id,
                            external_id=external_id,
                            external_url=url,
                            title=title,
                            document_id=document_id,
                            content_hash=actual_hash,
                        )
                        session.add(connector_doc)
                    else:
                        connector_doc.title = title
                        connector_doc.external_url = url
                        connector_doc.document_id = document_id
                        connector_doc.content_hash = actual_hash
                        connector_doc.last_synced_at = datetime.now(timezone.utc)

                    synced_count += 1

                # 5. Update connector metadata on success
                connector.last_synced_at = datetime.now(timezone.utc)
                connector.total_docs_synced = connector.total_docs_synced + synced_count
                connector.last_error = None
                connector.status = "active"

                await session.commit()
                logger.info(
                    "Connector %s sync complete — %d docs ingested/updated",
                    connector.name,
                    synced_count,
                )

            except Exception as exc:
                logger.error(
                    "Connector %s sync failed: %s", connector_id, exc, exc_info=True
                )
                await session.rollback()

                # Mark error on the connector using a fresh flush
                async with factory() as err_session:
                    err_result = await err_session.execute(
                        select(Connector).where(Connector.id == connector_id)
                    )
                    err_connector = err_result.scalar_one_or_none()
                    if err_connector:
                        err_connector.last_error = str(exc)
                        err_connector.status = "error"
                        await err_session.commit()
                raise

    asyncio.run(_async_sync())
    asyncio.run(engine.dispose())


@celery_app.task(
    bind=True,
    name="src.tasks.connector_tasks.sync_connector_task",
)
def sync_connector_task(self, connector_id: str) -> None:
    """Celery task: sync a single connector by ID."""
    logger.info("sync_connector_task started for connector %s", connector_id)
    try:
        _run_sync(connector_id)
        logger.info("sync_connector_task completed for connector %s", connector_id)
    except Exception as exc:
        logger.error(
            "sync_connector_task failed for connector %s: %s",
            connector_id,
            exc,
            exc_info=True,
        )
        raise


def _run_sync_all() -> None:
    """Query all active connectors and dispatch individual sync tasks."""
    from src.config import Settings
    from src.db.session import get_async_engine, get_session_factory

    settings = Settings()
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    async def _async_dispatch() -> None:
        from sqlalchemy import select
        from src.models.connector import Connector

        async with factory() as session:
            result = await session.execute(
                select(Connector).where(Connector.status == "active")
            )
            active_connectors = result.scalars().all()
            logger.info(
                "sync_all_connectors_task: dispatching %d connector syncs",
                len(active_connectors),
            )
            for connector in active_connectors:
                sync_connector_task.delay(connector.id)
                logger.debug("Dispatched sync for connector %s (%s)", connector.name, connector.id)

    asyncio.run(_async_dispatch())
    asyncio.run(engine.dispose())


@celery_app.task(name="src.tasks.connector_tasks.sync_all_connectors_task")
def sync_all_connectors_task() -> None:
    """Celery task: dispatch sync tasks for all active connectors.

    Called on the Celery beat schedule (every hour).
    """
    logger.info("sync_all_connectors_task triggered")
    try:
        _run_sync_all()
    except Exception as exc:
        logger.error("sync_all_connectors_task failed: %s", exc, exc_info=True)
        raise
