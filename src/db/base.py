"""SQLAlchemy declarative base for all ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models here so Alembic autogenerate and SQLAlchemy metadata
# discovery can find every table. Order matters: referenced models first.
# Do NOT remove these imports even if they appear unused.
def _register_models() -> None:  # noqa: F401
    from src.models import document  # noqa: F401 — Collection, DocumentFolder, Document, …
    from src.models import connector  # noqa: F401 — Connector, ConnectorDocument


_register_models()
