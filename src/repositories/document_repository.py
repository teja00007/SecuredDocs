"""Document data access layer."""

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.document import (
    Document, DocumentTeamAccess, DocumentUserAccess, VisibilityEnum
)
from src.models.team import Team
from src.models.user import User


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, document_id: str) -> Document | None:
        result = await self._session.execute(
            select(Document).where(Document.id == document_id)
        )
        return result.scalar_one_or_none()

    async def list_accessible(
        self,
        user_id: str,
        user_team_ids: list[str],
        skip: int = 0,
        limit: int = 20,
        collection_id: str | None = None,
    ) -> list[Document]:
        """Return documents the user can access based on visibility rules."""
        team_access_subq = (
            select(DocumentTeamAccess.document_id)
            .where(DocumentTeamAccess.team_id.in_(user_team_ids))
        ).scalar_subquery() if user_team_ids else select(DocumentTeamAccess.document_id).where(False).scalar_subquery()

        user_access_subq = (
            select(DocumentUserAccess.document_id)
            .where(DocumentUserAccess.user_id == user_id)
        ).scalar_subquery()

        visibility_filter = or_(
            Document.owner_id == user_id,
            Document.visibility == VisibilityEnum.PUBLIC.value,
            and_(
                Document.visibility == VisibilityEnum.TEAM.value,
                Document.id.in_(team_access_subq),
            ),
            and_(
                Document.visibility == VisibilityEnum.CONFIDENTIAL.value,
                Document.id.in_(user_access_subq),
            ),
        )

        stmt = select(Document).where(visibility_filter)
        if collection_id:
            stmt = stmt.where(Document.collection_id == collection_id)
        stmt = stmt.offset(skip).limit(limit)

        result = await self._session.execute(stmt)
        return list(result.scalars().unique().all())

    async def create(self, document: Document) -> Document:
        self._session.add(document)
        await self._session.flush()
        await self._session.refresh(document)
        return document

    async def update(self, document: Document) -> Document:
        self._session.add(document)
        await self._session.flush()
        await self._session.refresh(document)
        return document

    async def delete(self, document_id: str) -> None:
        doc = await self.get_by_id(document_id)
        if doc:
            await self._session.delete(doc)
            await self._session.flush()

    async def set_status(
        self, document_id: str, status: str, error_message: str | None = None
    ) -> None:
        doc = await self.get_by_id(document_id)
        if doc:
            doc.status = status
            await self._session.flush()

    async def set_chunk_count(self, document_id: str, count: int) -> None:
        doc = await self.get_by_id(document_id)
        if doc:
            doc.chunk_count = count
            await self._session.flush()

    async def set_team_access(self, document_id: str, team_ids: list[str]) -> None:
        await self._session.execute(
            DocumentTeamAccess.__table__.delete().where(
                DocumentTeamAccess.document_id == document_id
            )
        )
        for team_id in team_ids:
            self._session.add(DocumentTeamAccess(document_id=document_id, team_id=team_id))
        await self._session.flush()

    async def set_user_access(self, document_id: str, user_ids: list[str]) -> None:
        await self._session.execute(
            DocumentUserAccess.__table__.delete().where(
                DocumentUserAccess.document_id == document_id
            )
        )
        for user_id in user_ids:
            self._session.add(DocumentUserAccess(document_id=document_id, user_id=user_id))
        await self._session.flush()

    async def get_team_access(self, document_id: str) -> list[Team]:
        result = await self._session.execute(
            select(Team)
            .join(DocumentTeamAccess, DocumentTeamAccess.team_id == Team.id)
            .where(DocumentTeamAccess.document_id == document_id)
        )
        return list(result.scalars().all())

    async def get_user_access(self, document_id: str) -> list[User]:
        result = await self._session.execute(
            select(User)
            .join(DocumentUserAccess, DocumentUserAccess.user_id == User.id)
            .where(DocumentUserAccess.document_id == document_id)
        )
        return list(result.scalars().all())

    async def transfer_ownership(self, document_id: str, new_owner_id: str) -> None:
        doc = await self.get_by_id(document_id)
        if doc:
            doc.owner_id = new_owner_id
            await self._session.flush()

    async def get_by_filename_and_owner(self, filename: str, owner_id: str) -> Document | None:
        result = await self._session.execute(
            select(Document).where(
                and_(Document.filename == filename, Document.owner_id == owner_id)
            )
        )
        return result.scalar_one_or_none()
