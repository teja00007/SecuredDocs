"""SMB / CIFS network share connector with delta ingestion.

Crawls a Windows network share (SMB/CIFS) and yields documents for ingestion.
Delta ingestion skips files whose content hash hasn't changed since the last
successful sync.

Install: pip install smbprotocol

Config — stored in the Connector row's `config` JSON field:
    {
        "server":    "192.168.1.100",
        "share":     "Documents",
        "username":  "domain\\user",
        "password":  "secret",
        "domain":    "CORP",            // optional
        "root_path": "/",               // starting path within the share
        "file_types": [".pdf", ".docx", ".txt"],  // empty = all
        "max_depth": 5
    }
"""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import PurePosixPath

from src.connectors.base import BaseConnector

logger = logging.getLogger(__name__)

_DEFAULT_TYPES = [".pdf", ".docx", ".doc", ".txt", ".md", ".xlsx", ".pptx"]


class SMBConnector(BaseConnector):
    """Crawl an SMB/CIFS share and yield document content for ingestion."""

    @property
    def file_extension(self) -> str:
        return ".bin"  # varies per file; actual extension preserved in metadata

    # ── BaseConnector interface ───────────────────────────────────────────────

    async def list_documents(self) -> list[dict]:
        """Return descriptors for all documents on the share."""
        cfg = self.connector.config or {}
        session = self._make_session(cfg)
        share_name = cfg.get("share", "Documents")
        root_path = cfg.get("root_path", "/").lstrip("/") or ""
        allowed_types = [t.lower() for t in cfg.get("file_types", _DEFAULT_TYPES)]
        max_depth = int(cfg.get("max_depth", 5))

        docs: list[dict] = []
        try:
            self._crawl(session, share_name, root_path, allowed_types, max_depth, 0, docs)
        finally:
            try:
                session.disconnect()
            except Exception:
                pass

        return docs

    async def fetch_content(self, external_id: str) -> bytes:
        """Fetch raw bytes for the file at path *external_id* on the share."""
        cfg = self.connector.config or {}
        session = self._make_session(cfg)
        share_name = cfg.get("share", "Documents")
        file_path = external_id.lstrip("/")

        try:
            import smbprotocol.open as smb_open
            from smbprotocol.open import Open, FilePipePrinterAccessMask, ShareAccess
            tree = self._connect_tree(session, share_name)
            fh = Open(tree, file_path)
            fh.create(
                desired_access=FilePipePrinterAccessMask.FILE_READ_DATA,
                share_access=ShareAccess.FILE_SHARE_READ,
            )
            try:
                buf = io.BytesIO()
                offset = 0
                chunk_size = 64 * 1024  # 64 KB
                while True:
                    chunk = fh.read(offset, chunk_size)
                    if not chunk:
                        break
                    buf.write(chunk)
                    offset += len(chunk)
                return buf.getvalue()
            finally:
                fh.close()
        except Exception as e:
            raise RuntimeError(f"SMB fetch failed for {external_id}: {e}")
        finally:
            try:
                session.disconnect()
            except Exception:
                pass

    # ── Internal ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_session(cfg: dict):
        try:
            from smbprotocol.connection import Connection
            from smbprotocol.session import Session
        except ImportError:
            raise RuntimeError(
                "smbprotocol not installed. Run: pip install smbprotocol"
            )
        server = cfg.get("server", "localhost")
        username = cfg.get("username", "")
        password = cfg.get("password", "")
        domain = cfg.get("domain", "")

        connection = Connection(uuid=__import__("uuid").uuid4(), server=server, port=445)
        connection.connect()
        session = Session(connection, username=f"{domain}\\{username}" if domain else username, password=password)
        session.connect()
        return session

    @staticmethod
    def _connect_tree(session, share_name: str):
        from smbprotocol.tree import TreeConnect
        server = session.connection.server_name
        tree = TreeConnect(session, f"\\\\{server}\\{share_name}")
        tree.connect()
        return tree

    def _crawl(
        self,
        session,
        share_name: str,
        path: str,
        allowed_types: list[str],
        max_depth: int,
        depth: int,
        out: list[dict],
    ) -> None:
        if depth > max_depth:
            return

        try:
            from smbprotocol.open import Open, DirectoryAccessMask, ShareAccess, CreateDisposition, CreateOptions
            from smbprotocol.query_info import QueryDirectoryFlags
        except ImportError:
            raise RuntimeError("smbprotocol not installed. Run: pip install smbprotocol")

        tree = self._connect_tree(session, share_name)
        dir_handle = Open(tree, path or "")
        dir_handle.create(
            desired_access=DirectoryAccessMask.FILE_LIST_DIRECTORY,
            share_access=ShareAccess.FILE_SHARE_READ,
            create_disposition=CreateDisposition.FILE_OPEN,
            create_options=CreateOptions.FILE_DIRECTORY_FILE,
        )

        try:
            entries = dir_handle.query_directory("*")
        except Exception as e:
            logger.debug("SMB crawl failed at %s: %s", path, e)
            return
        finally:
            try:
                dir_handle.close()
            except Exception:
                pass

        for entry in entries:
            name = entry["file_name"].get_value()
            if name in (".", ".."):
                continue
            full_path = f"{path}/{name}".lstrip("/")
            is_dir = bool(entry["file_attributes"].get_value() & 0x10)

            if is_dir:
                self._crawl(session, share_name, full_path, allowed_types, max_depth, depth + 1, out)
            else:
                ext = PurePosixPath(name).suffix.lower()
                if allowed_types and ext not in allowed_types:
                    continue

                modified_ts = entry.get("last_write_time", {}).get_value(0)
                # Generate a stable content hash from path + mtime (cheap; full hash on fetch)
                content_hash = hashlib.md5(f"{full_path}:{modified_ts}".encode()).hexdigest()

                out.append({
                    "external_id": full_path,
                    "title": name,
                    "url": f"smb://{session.connection.server_name}/{share_name}/{full_path}",
                    "modified_at": str(modified_ts),
                    "content_hash": content_hash,
                    "file_extension": ext,
                })
