"""Collection, Document, DocumentFolder, DocumentTeamAccess, DocumentUserAccess, DocumentTag, DocumentVersion models."""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Boolean, UniqueConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base


class VisibilityEnum(str, enum.Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    TEAM = "team"
    CHANNEL = "channel"
    CONFIDENTIAL = "confidential"


class DocumentStatusEnum(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    EMBEDDING_FAILED = "embedding_failed"
    COMPLIANCE_BLOCKED = "compliance_blocked"
    FLAGGED = "flagged"


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    company_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id], lazy="selectin")
    documents: Mapped[list["Document"]] = relationship(back_populates="collection", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Collection {self.name}>"


class DocumentFolder(Base):
    """Hierarchical folder within a collection for organizing documents."""

    __tablename__ = "document_folders"
    __table_args__ = (
        UniqueConstraint(
            "collection_id", "parent_folder_id", "name", name="uq_folder_in_parent"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    collection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_folder_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("document_folders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Relationships — self-referential adjacency list for folder hierarchy
    children: Mapped[list["DocumentFolder"]] = relationship(
        "DocumentFolder",
        foreign_keys="[DocumentFolder.parent_folder_id]",
        back_populates="parent",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    parent: Mapped["DocumentFolder | None"] = relationship(
        "DocumentFolder",
        foreign_keys="[DocumentFolder.parent_folder_id]",
        back_populates="children",
        remote_side="DocumentFolder.id",
        lazy="selectin",
    )
    documents: Mapped[list["Document"]] = relationship(
        back_populates="folder", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<DocumentFolder {self.name} (collection={self.collection_id})>"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=True)
    visibility: Mapped[str] = mapped_column(
        Enum(VisibilityEnum, values_callable=lambda x: [e.value for e in x], validate_strings=True),
        nullable=False,
        default=VisibilityEnum.PUBLIC.value,
    )
    collection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("collections.id"), nullable=True, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chunking_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(DocumentStatusEnum, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=DocumentStatusEnum.PENDING.value,
        index=True,
    )
    folder_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    review_cycle_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id], lazy="selectin")
    collection: Mapped["Collection | None"] = relationship(back_populates="documents")
    folder: Mapped["DocumentFolder | None"] = relationship(
        back_populates="documents", lazy="selectin"
    )
    team_access: Mapped[list["DocumentTeamAccess"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )
    user_access: Mapped[list["DocumentUserAccess"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )
    document_tags: Mapped[list["DocumentTag"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )
    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", lazy="select",
        order_by="DocumentVersion.version_number"
    )

    @property
    def tags(self) -> list[str]:
        return [dt.tag for dt in self.document_tags]

    def __repr__(self) -> str:
        return f"<Document {self.filename}>"


class DocumentTeamAccess(Base):
    __tablename__ = "document_team_access"
    __table_args__ = (
        UniqueConstraint("document_id", "team_id", name="uq_doc_team"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="team_access")
    team = relationship("Team", back_populates="document_access", lazy="selectin")

    def __repr__(self) -> str:
        return f"<DocumentTeamAccess doc={self.document_id} team={self.team_id}>"


class DocumentUserAccess(Base):
    __tablename__ = "document_user_access"
    __table_args__ = (
        UniqueConstraint("document_id", "user_id", name="uq_doc_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Relationships
    document: Mapped["Document"] = relationship(back_populates="user_access")
    user = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return f"<DocumentUserAccess doc={self.document_id} user={self.user_id}>"


class DocumentTag(Base):
    """Tag labels attached to a document."""

    __tablename__ = "document_tags"
    __table_args__ = (
        UniqueConstraint("document_id", "tag", name="uq_doc_tag"),
    )

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    tag: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)

    document: Mapped["Document"] = relationship(back_populates="document_tags")

    def __repr__(self) -> str:
        return f"<DocumentTag doc={self.document_id} tag={self.tag}>"


class DocumentVersion(Base):
    """Archived version of a document file."""

    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="versions")

    def __repr__(self) -> str:
        return f"<DocumentVersion doc={self.document_id} v={self.version_number}>"
