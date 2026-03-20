"""Collection data access layer."""

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.document import Collection, Document


class CollectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, collection_id: str) -> Collection | None:
        result = await self._session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: str, skip: int = 0, limit: int = 50, company_id: str | None = None
    ) -> list[Collection]:
        stmt = (
            select(Collection)
            .where(
                (Collection.owner_id == user_id) | (Collection.is_public == True)  # noqa: E712
            )
        )
        if company_id:
            stmt = stmt.where(Collection.company_id == company_id)
        stmt = stmt.offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, collection: Collection) -> Collection:
        self._session.add(collection)
        await self._session.flush()
        await self._session.refresh(collection)
        return collection

    async def delete(self, collection_id: str) -> None:
        collection = await self.get_by_id(collection_id)
        if collection:
            await self._session.delete(collection)
            await self._session.flush()

    async def get_document_count(self, collection_id: str) -> int:
        result = await self._session.execute(
            select(func.count(Document.id)).where(Document.collection_id == collection_id)
        )
        return result.scalar_one() or 0
