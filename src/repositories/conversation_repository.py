"""Conversation data access layer."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.conversation import Conversation, ConversationMessage


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_for_user(self, user_id: str, limit: int = 50) -> list[Conversation]:
        result = await self._db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_id(self, conversation_id: str) -> Conversation | None:
        result = await self._db.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def create(self, conversation: Conversation) -> Conversation:
        self._db.add(conversation)
        await self._db.flush()
        await self._db.refresh(conversation)
        return conversation

    async def update_title(self, conversation_id: str, title: str) -> None:
        conv = await self.get_by_id(conversation_id)
        if conv:
            conv.title = title
            await self._db.flush()

    async def touch(self, conversation_id: str) -> None:
        """Update updated_at to now (called after each message)."""
        from datetime import datetime, timezone
        conv = await self.get_by_id(conversation_id)
        if conv:
            conv.updated_at = datetime.now(timezone.utc)
            await self._db.flush()

    async def delete(self, conversation_id: str) -> None:
        conv = await self.get_by_id(conversation_id)
        if conv:
            await self._db.delete(conv)
            await self._db.flush()

    async def add_message(self, message: ConversationMessage) -> ConversationMessage:
        self._db.add(message)
        await self._db.flush()
        return message

    async def get_message_by_id(self, message_id: str) -> ConversationMessage | None:
        result = await self._db.execute(
            select(ConversationMessage).where(ConversationMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    async def set_feedback(self, message_id: str, feedback: int | None) -> ConversationMessage | None:
        msg = await self.get_message_by_id(message_id)
        if msg:
            msg.feedback = feedback
            await self._db.flush()
        return msg

    async def get_messages(self, conversation_id: str) -> list[ConversationMessage]:
        result = await self._db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at)
        )
        return list(result.scalars().all())
