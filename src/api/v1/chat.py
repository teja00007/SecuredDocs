"""Real-time chat: channels, messages, WebSocket — with Slack-quality features."""

import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db
from src.core.rbac import UserContext
from src.core.security import decode_access_token
from src.config import get_settings
from src.models.chat import Channel, ChannelMember, ChatMessage, ChannelRead, MessageReaction
from src.services.chat_manager import manager
from src.services.presence_service import presence_service, VALID_STATUSES

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class ChannelOut(BaseModel):
    id: str
    name: str
    type: str
    team_id: str | None
    created_by: str | None
    created_at: datetime
    member_count: int
    last_message_at: datetime | None = None
    unread_count: int = 0
    # Populated for type=="dm" so the frontend never needs to cross-reference orgUsers
    dm_partner_id: str | None = None
    dm_partner_username: str | None = None

    model_config = {"from_attributes": True}


class ReactionOut(BaseModel):
    emoji: str
    count: int
    users: list[str]
    reacted_by_me: bool


class MessageOut(BaseModel):
    id: str
    channel_id: str
    sender_id: str
    sender_username: str
    content: str
    created_at: datetime
    # Threading
    parent_id: str | None = None
    thread_count: int = 0
    last_reply_at: datetime | None = None
    # Editing / deletion
    edited_at: datetime | None = None
    is_deleted: bool = False
    # Pinning
    is_pinned: bool = False
    pinned_by_id: str | None = None
    pinned_at: datetime | None = None
    # Reactions
    reactions: list[ReactionOut] = []

    model_config = {"from_attributes": True}


class MemberOut(BaseModel):
    user_id: str
    username: str
    email: str
    joined_at: datetime


class CreateChannelRequest(BaseModel):
    name: str
    type: str = "group"  # "group" | "public"
    team_id: str | None = None
    member_ids: list[str] = []


class CreateDMRequest(BaseModel):
    target_user_id: str
    target_username: str


class SendMessageRequest(BaseModel):
    content: str
    parent_id: str | None = None


class AddMembersRequest(BaseModel):
    user_ids: list[str]


class EditMessageRequest(BaseModel):
    content: str


class AddReactionRequest(BaseModel):
    emoji: str


class SetStatusRequest(BaseModel):
    status: str
    custom_status: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_reactions(reactions: list[MessageReaction], current_user_id: str) -> list[ReactionOut]:
    """Aggregate raw reaction rows into grouped ReactionOut objects."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in reactions:
        grouped[r.emoji].append(r.user_id)
    return [
        ReactionOut(
            emoji=emoji,
            count=len(users),
            users=users,
            reacted_by_me=current_user_id in users,
        )
        for emoji, users in grouped.items()
    ]


def _channel_out(
    ch: Channel,
    last_message_at: datetime | None = None,
    unread_count: int = 0,
    dm_partner_id: str | None = None,
    dm_partner_username: str | None = None,
) -> ChannelOut:
    return ChannelOut(
        id=ch.id,
        name=ch.name,
        type=ch.type,
        team_id=ch.team_id,
        created_by=ch.created_by,
        created_at=ch.created_at,
        member_count=len(ch.members),
        last_message_at=last_message_at,
        unread_count=unread_count,
        dm_partner_id=dm_partner_id,
        dm_partner_username=dm_partner_username,
    )


def _msg_out(m: ChatMessage, current_user_id: str = "") -> MessageOut:
    content = "This message was deleted" if m.is_deleted else m.content
    reactions = _build_reactions(m.reactions if m.reactions else [], current_user_id)
    return MessageOut(
        id=m.id,
        channel_id=m.channel_id,
        sender_id=m.sender_id,
        sender_username=m.sender_username,
        content=content,
        created_at=m.created_at,
        parent_id=m.parent_id,
        thread_count=m.thread_count,
        last_reply_at=m.last_reply_at,
        edited_at=m.edited_at,
        is_deleted=m.is_deleted,
        is_pinned=m.is_pinned,
        pinned_by_id=m.pinned_by_id,
        pinned_at=m.pinned_at,
        reactions=reactions,
    )


async def _assert_member(channel_id: str, user_id: str, db: AsyncSession) -> Channel:
    ch = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    if ch.type != "public":
        is_member = any(m.user_id == user_id for m in ch.members)
        if not is_member:
            raise HTTPException(status_code=403, detail="Not a member of this channel")
    return ch


async def _get_accessible_channel_ids(user_id: str, db: AsyncSession) -> list[str]:
    """Return all channel IDs the user can access (member + public)."""
    member_subq = (
        select(ChannelMember.channel_id).where(ChannelMember.user_id == user_id)
    ).scalar_subquery()
    result = await db.execute(
        select(Channel.id).where(
            or_(Channel.type == "public", Channel.id.in_(member_subq))
        )
    )
    return [row[0] for row in result.all()]


async def _process_mentions(
    content: str,
    channel_id: str,
    channel_name: str,
    message_id: str,
    sender_username: str,
    sender_id: str,
    db: AsyncSession,
) -> None:
    """Feature 4: Scan message for @mentions and create notifications."""
    mentions = re.findall(r'@(\w+)', content)
    if not mentions:
        return

    from src.models.user import User as DBUser
    from src.services.notification_service import create_and_push as _notif

    for username in set(mentions):
        if username == sender_username:
            continue
        user_row = (await db.execute(
            select(DBUser).where(DBUser.username == username)
        )).scalar_one_or_none()
        if not user_row:
            continue
        # Check if user is a channel member (or channel is public)
        ch_row = (await db.execute(
            select(Channel).where(Channel.id == channel_id)
        )).scalar_one_or_none()
        if ch_row and ch_row.type != "public":
            is_member = (await db.execute(
                select(ChannelMember).where(
                    and_(
                        ChannelMember.channel_id == channel_id,
                        ChannelMember.user_id == user_row.id,
                    )
                )
            )).scalar_one_or_none()
            if not is_member:
                continue
        await _notif(
            db,
            user_row.id,
            "mention",
            f"You were mentioned in #{channel_name}",
            content[:100],
            f"/chat?channel={channel_id}&message={message_id}",
        )


# ── REST endpoints ─────────────────────────────────────────────────────────────

@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return channels the user belongs to + all public channels."""
    member_subq = (
        select(ChannelMember.channel_id).where(ChannelMember.user_id == user.user_id)
    ).scalar_subquery()

    result = await db.execute(
        select(Channel).where(
            or_(Channel.type == "public", Channel.id.in_(member_subq))
        )
    )
    channels = list(result.scalars().unique().all())

    channel_ids = [c.id for c in channels]
    last_msg_map: dict[str, datetime] = {}
    unread_map: dict[str, int] = {}

    if channel_ids:
        # Last message timestamps
        lm_result = await db.execute(
            select(ChatMessage.channel_id, func.max(ChatMessage.created_at).label("last_at"))
            .where(ChatMessage.channel_id.in_(channel_ids))
            .group_by(ChatMessage.channel_id)
        )
        last_msg_map = {row.channel_id: row.last_at for row in lm_result.all()}

        reads_result = await db.execute(
            select(ChannelRead.channel_id, ChannelRead.last_read_at)
            .where(and_(
                ChannelRead.channel_id.in_(channel_ids),
                ChannelRead.user_id == user.user_id,
            ))
        )
        reads_map = {row.channel_id: row.last_read_at for row in reads_result.all()}

        from datetime import datetime, timezone as _tz
        now_utc = datetime.now(_tz.utc)
        never_read = [ch_id for ch_id in channel_ids if ch_id not in reads_map]
        if never_read:
            for ch_id in never_read:
                db.add(ChannelRead(channel_id=ch_id, user_id=user.user_id, last_read_at=now_utc))
                reads_map[ch_id] = now_utc
            await db.flush()

        unread_conditions = []
        for ch_id in channel_ids:
            last_read = reads_map.get(ch_id)
            if last_read is not None:
                unread_conditions.append(and_(
                    ChatMessage.channel_id == ch_id,
                    ChatMessage.created_at > last_read,
                ))

        if unread_conditions:
            unread_result = await db.execute(
                select(ChatMessage.channel_id, func.count(ChatMessage.id).label("unread"))
                .where(and_(
                    ChatMessage.sender_id != user.user_id,
                    or_(*unread_conditions),
                ))
                .group_by(ChatMessage.channel_id)
            )
            unread_map = {row.channel_id: row.unread for row in unread_result.all()}

    partner_username_map: dict[str, str] = {}
    dm_partner_ids = {
        m.user_id
        for c in channels if c.type == "dm"
        for m in c.members if m.user_id != user.user_id
    }
    if dm_partner_ids:
        from src.models.user import User as DBUser
        rows = await db.execute(select(DBUser.id, DBUser.username).where(DBUser.id.in_(dm_partner_ids)))
        partner_username_map = {row.id: row.username for row in rows.all()}

    await db.commit()

    result_out = []
    for c in channels:
        pid = pname = None
        if c.type == "dm":
            pid = next((m.user_id for m in c.members if m.user_id != user.user_id), None)
            pname = partner_username_map.get(pid, "") if pid else None
        result_out.append(_channel_out(c, last_msg_map.get(c.id), unread_map.get(c.id, 0), pid, pname))
    return result_out


@router.get("/channels/{channel_id}", response_model=ChannelOut)
async def get_channel(
    channel_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single channel the user has access to."""
    ch = await _assert_member(channel_id, user.user_id, db)
    pid = pname = None
    if ch.type == "dm":
        pid = next((m.user_id for m in ch.members if m.user_id != user.user_id), None)
        if pid:
            from src.models.user import User as DBUser
            row = (await db.execute(select(DBUser.id, DBUser.username).where(DBUser.id == pid))).one_or_none()
            pname = row.username if row else None
    await db.commit()
    return _channel_out(ch, dm_partner_id=pid, dm_partner_username=pname)


@router.post("/channels", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: CreateChannelRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ch = Channel(
        id=str(uuid.uuid4()),
        name=body.name,
        type=body.type,
        team_id=body.team_id,
        created_by=user.user_id,
    )
    db.add(ch)
    await db.flush()

    member_ids = list({user.user_id, *body.member_ids})
    for uid in member_ids:
        db.add(ChannelMember(channel_id=ch.id, user_id=uid))
    await db.flush()
    await db.refresh(ch)
    await db.commit()
    return _channel_out(ch)


@router.post("/channels/dm", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def create_or_get_dm(
    body: CreateDMRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return existing DM channel or create one."""
    my_dms = (
        select(ChannelMember.channel_id)
        .join(Channel, Channel.id == ChannelMember.channel_id)
        .where(and_(ChannelMember.user_id == user.user_id, Channel.type == "dm"))
    ).scalar_subquery()

    their_dms = (
        select(ChannelMember.channel_id)
        .where(ChannelMember.user_id == body.target_user_id)
    ).scalar_subquery()

    result = await db.execute(
        select(Channel).where(and_(Channel.id.in_(my_dms), Channel.id.in_(their_dms)))
    )
    existing = result.scalar_one_or_none()
    if existing:
        await db.commit()
        return _channel_out(existing, dm_partner_id=body.target_user_id, dm_partner_username=body.target_username)

    ch = Channel(
        id=str(uuid.uuid4()),
        name=f"dm:{user.user_id}:{body.target_user_id}",
        type="dm",
        created_by=user.user_id,
    )
    db.add(ch)
    await db.flush()
    db.add(ChannelMember(channel_id=ch.id, user_id=user.user_id))
    db.add(ChannelMember(channel_id=ch.id, user_id=body.target_user_id))
    await db.flush()
    await db.refresh(ch)
    await db.commit()
    return _channel_out(ch, dm_partner_id=body.target_user_id, dm_partner_username=body.target_username)


@router.get("/channels/{channel_id}/members", response_model=list[MemberOut])
async def get_channel_members(
    channel_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ch = await _assert_member(channel_id, user.user_id, db)
    from src.models.user import User as DBUser
    members_out: list[MemberOut] = []
    for m in ch.members:
        db_user = (await db.execute(select(DBUser).where(DBUser.id == m.user_id))).scalar_one_or_none()
        if db_user:
            members_out.append(MemberOut(
                user_id=db_user.id,
                username=db_user.username,
                email=db_user.email,
                joined_at=m.joined_at,
            ))
    await db.commit()
    return members_out


@router.post("/channels/{channel_id}/members", status_code=status.HTTP_200_OK)
async def add_channel_members(
    channel_id: str,
    body: AddMembersRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ch = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    if ch.created_by != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only channel owner can add members")
    existing_ids = {m.user_id for m in ch.members}
    for uid in body.user_ids:
        if uid not in existing_ids:
            db.add(ChannelMember(channel_id=channel_id, user_id=uid))
    await db.commit()
    await db.refresh(ch)
    return _channel_out(ch)


@router.delete("/channels/{channel_id}/members/{target_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_channel_member(
    channel_id: str,
    target_user_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ch = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    if ch.created_by != user.user_id and "admin" not in user.roles and target_user_id != user.user_id:
        raise HTTPException(status_code=403, detail="Not authorized to remove members")
    member = (await db.execute(
        select(ChannelMember).where(
            and_(ChannelMember.channel_id == channel_id, ChannelMember.user_id == target_user_id)
        )
    )).scalar_one_or_none()
    if member:
        await db.delete(member)
        await db.commit()


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ch = (await db.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    if ch.created_by != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only the channel creator or an admin can delete this channel")
    await db.delete(ch)
    await db.commit()


# ── Feature 1 + 2: Messages with threading, edit, delete ──────────────────────

@router.get("/channels/{channel_id}/messages", response_model=list[MessageOut])
async def get_messages(
    channel_id: str,
    limit: int = Query(50, le=200),
    before: str | None = Query(None),
    thread_root_only: bool = Query(True),
    parent_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.user_id, db)

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.channel_id == channel_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
    )

    # Filter by thread scope
    if parent_id is not None:
        # Return replies to a specific message
        stmt = stmt.where(ChatMessage.parent_id == parent_id)
    elif thread_root_only:
        # Return only top-level messages
        stmt = stmt.where(ChatMessage.parent_id == None)  # noqa: E711

    if before:
        ref = (await db.execute(
            select(ChatMessage).where(ChatMessage.id == before)
        )).scalar_one_or_none()
        if ref:
            stmt = stmt.where(ChatMessage.created_at < ref.created_at)

    result = await db.execute(stmt)
    msgs = list(reversed(result.scalars().all()))
    await db.commit()
    return [_msg_out(m, user.user_id) for m in msgs]


@router.post("/channels/{channel_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def send_message(
    channel_id: str,
    body: SendMessageRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """REST fallback — WebSocket is preferred for real-time."""
    ch = await _assert_member(channel_id, user.user_id, db)

    from src.repositories.user_repository import UserRepository
    repo = UserRepository(db)
    db_user = await repo.get_by_id(user.user_id)
    username = db_user.username if db_user else user.user_id

    # Feature 1: validate parent_id if provided
    parent_msg: ChatMessage | None = None
    if body.parent_id:
        parent_msg = (await db.execute(
            select(ChatMessage).where(
                and_(ChatMessage.id == body.parent_id, ChatMessage.channel_id == channel_id)
            )
        )).scalar_one_or_none()
        if not parent_msg:
            raise HTTPException(status_code=404, detail="Parent message not found in this channel")

    msg = ChatMessage(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        sender_id=user.user_id,
        sender_username=username,
        content=body.content.strip(),
        parent_id=body.parent_id,
    )
    db.add(msg)
    await db.flush()

    # Update parent thread stats
    now = datetime.now(timezone.utc)
    if parent_msg:
        parent_msg.thread_count = (parent_msg.thread_count or 0) + 1
        parent_msg.last_reply_at = now

    await db.commit()
    await db.refresh(msg)

    broadcast_payload: dict = {
        "type": "message",
        "id": msg.id,
        "channel_id": channel_id,
        "sender_id": msg.sender_id,
        "sender_username": msg.sender_username,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
        "parent_id": msg.parent_id,
        "thread_count": msg.thread_count,
        "last_reply_at": msg.last_reply_at.isoformat() if msg.last_reply_at else None,
    }

    if parent_msg:
        # Also broadcast thread_reply so clients can update thread previews
        await manager.broadcast(channel_id, {
            "type": "thread_reply",
            "parent_id": parent_msg.id,
            "reply_count": parent_msg.thread_count,
            "last_reply_at": now.isoformat(),
        })

    await manager.broadcast(channel_id, broadcast_payload)

    # Feature 4: @mention notifications
    async for session2 in _get_session():
        await _process_mentions(
            msg.content, channel_id, ch.name, msg.id, username, user.user_id, session2
        )
        await session2.commit()

    # Feature 4: DM notification for recipient
    if ch.type == "dm":
        from src.services.notification_service import create_and_push as _notif
        online_ids = manager.online_user_ids(channel_id)
        async for session2 in _get_session():
            for member in ch.members:
                if member.user_id != user.user_id:
                    await _notif(
                        session2, member.user_id, "direct_message",
                        f"New message from {username}",
                        body.content.strip()[:120],
                        f"/chat?channel={channel_id}",
                    )
            await session2.commit()

    return _msg_out(msg, user.user_id)


# Feature 1: Get thread replies
@router.get("/channels/{channel_id}/messages/{message_id}/thread", response_model=dict)
async def get_thread(
    channel_id: str,
    message_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the root message plus all its replies ordered by created_at ASC."""
    await _assert_member(channel_id, user.user_id, db)

    root = (await db.execute(
        select(ChatMessage).where(
            and_(ChatMessage.id == message_id, ChatMessage.channel_id == channel_id)
        )
    )).scalar_one_or_none()
    if not root:
        raise HTTPException(status_code=404, detail="Message not found")

    replies_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.parent_id == message_id)
        .order_by(ChatMessage.created_at.asc())
    )
    replies = list(replies_result.scalars().all())
    await db.commit()

    return {
        "root": _msg_out(root, user.user_id),
        "replies": [_msg_out(r, user.user_id) for r in replies],
    }


# Feature 2: Edit message
@router.patch("/channels/{channel_id}/messages/{message_id}", response_model=MessageOut)
async def edit_message(
    channel_id: str,
    message_id: str,
    body: EditMessageRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.user_id, db)

    msg = (await db.execute(
        select(ChatMessage).where(
            and_(ChatMessage.id == message_id, ChatMessage.channel_id == channel_id)
        )
    )).scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only the message author or admin can edit this message")
    if msg.is_deleted:
        raise HTTPException(status_code=400, detail="Cannot edit a deleted message")

    now = datetime.now(timezone.utc)
    msg.content = body.content.strip()
    msg.edited_at = now
    await db.commit()
    await db.refresh(msg)

    await manager.broadcast(channel_id, {
        "type": "message_edited",
        "message_id": msg.id,
        "content": msg.content,
        "edited_at": now.isoformat(),
    })

    return _msg_out(msg, user.user_id)


# Feature 2: Delete message (soft)
@router.delete("/channels/{channel_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    channel_id: str,
    message_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.user_id, db)

    msg = (await db.execute(
        select(ChatMessage).where(
            and_(ChatMessage.id == message_id, ChatMessage.channel_id == channel_id)
        )
    )).scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only the message author or admin can delete this message")

    now = datetime.now(timezone.utc)
    msg.is_deleted = True
    msg.deleted_at = now
    # Keep original content for audit; it won't be returned to clients
    await db.commit()

    await manager.broadcast(channel_id, {
        "type": "message_deleted",
        "message_id": msg.id,
    })


# ── Feature 3: Reactions ───────────────────────────────────────────────────────

async def _get_reactions_full(message_id: str, db: AsyncSession) -> list[dict]:
    """Return [{emoji, count, users}] for a message — used in WS broadcasts."""
    result = await db.execute(
        select(MessageReaction.emoji, MessageReaction.user_id)
        .where(MessageReaction.message_id == message_id)
        .order_by(MessageReaction.emoji)
    )
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in result.all():
        grouped[row.emoji].append(row.user_id)
    return [{"emoji": e, "count": len(users), "users": users} for e, users in grouped.items()]


@router.post(
    "/channels/{channel_id}/messages/{message_id}/reactions",
    status_code=status.HTTP_200_OK,
)
async def add_reaction(
    channel_id: str,
    message_id: str,
    body: AddReactionRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.user_id, db)

    msg = (await db.execute(
        select(ChatMessage).where(
            and_(ChatMessage.id == message_id, ChatMessage.channel_id == channel_id)
        )
    )).scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    emoji = body.emoji.strip()[:32]
    existing = (await db.execute(
        select(MessageReaction).where(
            and_(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == user.user_id,
                MessageReaction.emoji == emoji,
            )
        )
    )).scalar_one_or_none()

    if not existing:
        db.add(MessageReaction(
            id=str(uuid.uuid4()),
            message_id=message_id,
            user_id=user.user_id,
            emoji=emoji,
        ))
        await db.flush()

    await db.commit()
    reactions = await _get_reactions_full(message_id, db)

    await manager.broadcast(channel_id, {
        "type": "reaction_added",
        "message_id": message_id,
        "emoji": emoji,
        "user_id": user.user_id,
        "reactions": reactions,
    })

    return {"ok": True, "reactions": reactions}


@router.delete(
    "/channels/{channel_id}/messages/{message_id}/reactions/{emoji}",
    status_code=status.HTTP_200_OK,
)
async def remove_reaction(
    channel_id: str,
    message_id: str,
    emoji: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.user_id, db)

    reaction = (await db.execute(
        select(MessageReaction).where(
            and_(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == user.user_id,
                MessageReaction.emoji == emoji,
            )
        )
    )).scalar_one_or_none()

    if reaction:
        await db.delete(reaction)
        await db.flush()

    await db.commit()
    reactions = await _get_reactions_full(message_id, db)

    await manager.broadcast(channel_id, {
        "type": "reaction_removed",
        "message_id": message_id,
        "emoji": emoji,
        "user_id": user.user_id,
        "reactions": reactions,
    })

    return {"ok": True, "reactions": reactions}


# ── Feature 6: Global Message Search ──────────────────────────────────────────

@router.get("/messages/search")
async def search_messages(
    q: str = Query(..., min_length=1),
    channel_id: str | None = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Feature 6: Full-text search across all messages the user can access."""
    accessible_ids = await _get_accessible_channel_ids(user.user_id, db)
    if not accessible_ids:
        await db.commit()
        return []

    search_term = q.strip()

    stmt = (
        select(ChatMessage)
        .where(
            and_(
                ChatMessage.is_deleted == False,  # noqa: E712
                ChatMessage.channel_id.in_(accessible_ids),
                ChatMessage.content.ilike(f"%{search_term}%"),
            )
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    if channel_id:
        stmt = stmt.where(ChatMessage.channel_id == channel_id)

    result = await db.execute(stmt)
    msgs = list(result.scalars().all())

    # Fetch channel names for response
    ch_ids = list({m.channel_id for m in msgs})
    ch_map: dict[str, str] = {}
    if ch_ids:
        ch_rows = await db.execute(select(Channel.id, Channel.name).where(Channel.id.in_(ch_ids)))
        ch_map = {row.id: row.name for row in ch_rows.all()}

    await db.commit()

    def _snippet(content: str, term: str) -> str:
        lower = content.lower()
        pos = lower.find(term.lower())
        if pos == -1:
            return content[:150]
        start = max(0, pos - 60)
        end = min(len(content), pos + len(term) + 90)
        excerpt = content[start:end]
        # Highlight with markdown bold
        highlighted = re.sub(re.escape(term), f"**{term}**", excerpt, flags=re.IGNORECASE)
        return ("..." if start > 0 else "") + highlighted + ("..." if end < len(content) else "")

    return [
        {
            "message_id": m.id,
            "channel_id": m.channel_id,
            "channel_name": ch_map.get(m.channel_id, ""),
            "sender_username": m.sender_username,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
            "snippet": _snippet(m.content, search_term),
        }
        for m in msgs
    ]


# ── Channel-scoped RAG ────────────────────────────────────────────────────────

class ChannelRagRequest(BaseModel):
    query: str


@router.post("/channels/{channel_id}/rag", response_model=dict)
async def channel_rag(
    channel_id: str,
    body: ChannelRagRequest,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Answer a query using documents visible to the user, scoped to a channel."""
    from src.api.v1.deps import get_rag_service as _rag_factory, get_settings as _settings_dep
    from src.services.rag_service import RAGService
    from src.services.retrieval_service import RetrievalService
    from src.services.generation_service import GenerationService
    from src.services.query_rewriter import QueryRewriter
    from src.services.embedding_service import OllamaEmbeddingService
    from src.repositories.audit_repository import AuditRepository
    from src.vectorstore import get_vector_store
    from src.llm import get_llm

    ch = await _assert_member(channel_id, user.user_id, db)

    query = body.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="Query must not be empty")

    settings = get_settings()

    emb_svc = OllamaEmbeddingService(
        base_url=settings.OLLAMA_BASE_URL,
        model=settings.EMBEDDING_MODEL,
        dimensions=settings.EMBEDDING_DIMENSIONS,
    )
    llm = get_llm(settings)
    vector_store = get_vector_store(settings)
    audit_repo = AuditRepository(db)

    retrieval = RetrievalService(
        embedding_service=emb_svc,
        vector_store=vector_store,
        hybrid_enabled=getattr(settings, "HYBRID_SEARCH_ENABLED", False),
        score_threshold=getattr(settings, "RETRIEVAL_SCORE_THRESHOLD", 0.0),
    )
    generation = GenerationService(llm=llm)
    rewriter = QueryRewriter(llm=llm) if settings.QUERY_REWRITING_ENABLED else None
    rag_svc = RAGService(
        retrieval_service=retrieval,
        generation_service=generation,
        audit_repo=audit_repo,
        query_rewriter=rewriter,
    )

    # Documents don't have a channel_id field, so we query all docs visible to
    # the user and inject channel context so the LLM frames its response correctly.
    channel_context = (
        f"[Channel context: The user is asking from channel '#{ch.name}'. "
        f"Prioritise information relevant to this channel's topic.]"
    )

    result = await rag_svc.query(
        query_text=query,
        user=user,
        top_k=5,
        chat_history=[
            {"role": "user", "content": channel_context},
            {"role": "assistant", "content": "Understood. I will answer based on the documents available in this channel context."},
        ],
    )

    await db.commit()

    return {
        "query": query,
        "answer": result.get("answer", ""),
        "sources": result.get("sources", []),
    }


# ── Chat Media Upload (images) ────────────────────────────────────────────────

_MEDIA_DIR = Path("data/uploads/chat_media")
_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/gif": ".gif", "image/webp": ".webp", "image/tiff": ".tiff",
}


@router.post("/media/upload")
async def upload_chat_media(
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
):
    """Upload an image for inline display in chat messages."""
    content_type = (file.content_type or "").lower()
    ext = _ALLOWED_IMAGE_TYPES.get(content_type)
    if not ext:
        # Try to infer from filename extension
        suffix = Path(file.filename or "").suffix.lower()
        if suffix in {".jpg", ".jpeg"}: ext = ".jpg"
        elif suffix in {".png"}: ext = ".png"
        elif suffix in {".gif"}: ext = ".gif"
        elif suffix in {".webp"}: ext = ".webp"
        elif suffix in {".tiff", ".tif"}: ext = ".tiff"
        else:
            raise HTTPException(status_code=422, detail=f"Unsupported image type. Allowed: jpg, png, gif, webp, tiff")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20 MB
        raise HTTPException(status_code=413, detail="Image too large (max 20 MB)")

    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}{ext}"
    (_MEDIA_DIR / filename).write_bytes(content)

    return {"url": f"/api/v1/chat/media/{filename}", "filename": file.filename or filename}


@router.get("/media/{filename}")
async def get_chat_media(
    filename: str,
    _: UserContext = Depends(get_current_user),
):
    """Serve an uploaded chat image."""
    # Sanitise — no path traversal
    safe_name = Path(filename).name
    path = _MEDIA_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Media not found")
    return FileResponse(str(path))


# ── Feature 7: Message Pinning ─────────────────────────────────────────────────

@router.get("/channels/{channel_id}/pinned", response_model=list[MessageOut])
async def get_pinned_messages(
    channel_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _assert_member(channel_id, user.user_id, db)

    result = await db.execute(
        select(ChatMessage)
        .where(
            and_(
                ChatMessage.channel_id == channel_id,
                ChatMessage.is_pinned == True,  # noqa: E712
            )
        )
        .order_by(ChatMessage.pinned_at.desc())
    )
    msgs = list(result.scalars().all())
    await db.commit()
    return [_msg_out(m, user.user_id) for m in msgs]


@router.post(
    "/channels/{channel_id}/messages/{message_id}/pin",
    status_code=status.HTTP_200_OK,
)
async def pin_message(
    channel_id: str,
    message_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ch = await _assert_member(channel_id, user.user_id, db)

    if ch.created_by != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only channel owner or admin can pin messages")

    # Check pin limit
    pin_count_result = await db.execute(
        select(func.count(ChatMessage.id)).where(
            and_(
                ChatMessage.channel_id == channel_id,
                ChatMessage.is_pinned == True,  # noqa: E712
            )
        )
    )
    pin_count = pin_count_result.scalar_one()
    if pin_count >= 10:
        raise HTTPException(status_code=409, detail="Maximum 10 pinned messages per channel")

    msg = (await db.execute(
        select(ChatMessage).where(
            and_(ChatMessage.id == message_id, ChatMessage.channel_id == channel_id)
        )
    )).scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    now = datetime.now(timezone.utc)
    msg.is_pinned = True
    msg.pinned_by_id = user.user_id
    msg.pinned_at = now
    await db.commit()
    await db.refresh(msg)

    await manager.broadcast(channel_id, {
        "type": "message_pinned",
        "message_id": msg.id,
        "pinned_by_id": user.user_id,
        "pinned_at": now.isoformat(),
    })

    return _msg_out(msg, user.user_id)


@router.delete(
    "/channels/{channel_id}/messages/{message_id}/pin",
    status_code=status.HTTP_200_OK,
)
async def unpin_message(
    channel_id: str,
    message_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ch = await _assert_member(channel_id, user.user_id, db)

    if ch.created_by != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=403, detail="Only channel owner or admin can unpin messages")

    msg = (await db.execute(
        select(ChatMessage).where(
            and_(ChatMessage.id == message_id, ChatMessage.channel_id == channel_id)
        )
    )).scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.is_pinned = False
    msg.pinned_by_id = None
    msg.pinned_at = None
    await db.commit()
    await db.refresh(msg)

    await manager.broadcast(channel_id, {
        "type": "message_unpinned",
        "message_id": msg.id,
    })

    return _msg_out(msg, user.user_id)


# ── Feature 5: Presence REST ───────────────────────────────────────────────────

@router.get("/users/presence")
async def get_presence(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Feature 5: Return presence for all org members."""
    from src.models.user import User as DBUser
    rows = await db.execute(select(DBUser.id, DBUser.username))
    all_users = rows.all()
    await db.commit()

    result = []
    for row in all_users:
        p = presence_service.get(row.id)
        last_seen = p.get("last_seen")
        result.append({
            "user_id": row.id,
            "username": row.username,
            "status": p.get("status", "offline"),
            "last_seen": last_seen.isoformat() if last_seen else None,
            "custom_status": p.get("custom_status"),
        })
    return result


@router.post("/channels/{channel_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_channel_read(
    channel_id: str,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all messages in a channel as read for the current user."""
    await _assert_member(channel_id, user.user_id, db)
    now = datetime.now(timezone.utc)
    existing = (await db.execute(
        select(ChannelRead).where(
            and_(ChannelRead.channel_id == channel_id, ChannelRead.user_id == user.user_id)
        )
    )).scalar_one_or_none()
    if existing:
        existing.last_read_at = now
    else:
        db.add(ChannelRead(channel_id=channel_id, user_id=user.user_id, last_read_at=now))
    await db.commit()


# ── Link preview ──────────────────────────────────────────────────────────────

_URL_RE = re.compile(
    r"^https?://"                          # must be http/https
    r"(?!(?:localhost|127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.))"  # block private IPs
    r"[\w\-]+(\.[\w\-]+)+"                 # at least one dot in hostname
    r"(/[^\s]*)?$",
    re.IGNORECASE,
)


class LinkPreviewOut(BaseModel):
    url: str
    title: str | None = None
    description: str | None = None
    image: str | None = None
    favicon: str | None = None
    site_name: str | None = None


@router.get("/link-preview", response_model=LinkPreviewOut)
async def link_preview(
    url: str = Query(..., description="URL to fetch preview for"),
    user: UserContext = Depends(get_current_user),
):
    """Fetch Open Graph / meta-tag preview for a URL.

    Blocked: localhost, private IP ranges (SSRF prevention).
    Results are not cached server-side; the frontend should dedupe calls.
    """
    if not _URL_RE.match(url):
        raise HTTPException(status_code=422, detail="Invalid or blocked URL.")

    import httpx
    from html.parser import HTMLParser

    class _MetaParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.og: dict[str, str] = {}
            self.title: str | None = None
            self._in_title = False
            self._done = False

        def handle_starttag(self, tag, attrs):
            if self._done:
                return
            attrs_dict = dict(attrs)
            if tag == "title":
                self._in_title = True
            elif tag == "meta":
                prop = attrs_dict.get("property", "") or attrs_dict.get("name", "")
                content = attrs_dict.get("content", "")
                if prop.startswith("og:") and content:
                    self.og[prop[3:]] = content
                elif prop == "description" and content and "description" not in self.og:
                    self.og["description"] = content
            elif tag == "body":
                self._done = True

        def handle_data(self, data):
            if self._in_title and not self.og.get("title"):
                self.title = data.strip()
                self._in_title = False

        def handle_endtag(self, tag):
            if tag == "title":
                self._in_title = False

    try:
        async with httpx.AsyncClient(
            timeout=6.0,
            follow_redirects=True,
            headers={"User-Agent": "NexusBot/1.0 (+https://nexus.ai)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "")
            if "html" not in ct:
                raise HTTPException(status_code=422, detail="URL does not return HTML.")
            # Parse only first 64 KB to avoid huge pages
            html = resp.text[:65536]
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=422, detail=f"URL fetch failed: {exc.response.status_code}")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"URL fetch error: {exc}")

    parser = _MetaParser()
    parser.feed(html)
    og = parser.og

    # Favicon: try /favicon.ico relative to origin
    from urllib.parse import urlparse
    parsed = urlparse(url)
    favicon = og.get("image") or f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

    return LinkPreviewOut(
        url=url,
        title=og.get("title") or parser.title,
        description=og.get("description"),
        image=og.get("image"),
        favicon=favicon,
        site_name=og.get("site_name") or parsed.netloc,
    )


# ── Helper for getting a fresh DB session inside WS handlers ──────────────────

def _get_session():
    """Yield a fresh async DB session for use inside WebSocket handlers."""
    from src.config import get_settings as _get_settings
    from src.db.session import get_async_engine, get_session_factory, get_async_session
    settings = _get_settings()
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)
    return get_async_session(factory)


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/{channel_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    channel_id: str,
    token: str = Query(...),
):
    """
    Connect with ?token=<access_token>.
    Send: {"content": "hello"} — regular message
          {"content": "hello", "parent_id": "..."} — thread reply
          {"type": "ping"} — heartbeat (server replies with {"type": "pong"})
    Receive: {"type": "message", ...}
             {"type": "thread_reply", ...}
             {"type": "online", "users": [...]}
             {"type": "pong"}
    """
    settings = get_settings()
    try:
        from src.core.exceptions import AuthenticationError
        payload = decode_access_token(token, settings.APP_SECRET_KEY, settings.JWT_ALGORITHM)
    except Exception:
        await websocket.close(code=4001)
        return

    user_id = payload["sub"]
    username = payload.get("username") or user_id

    # Verify channel access via a fresh DB session
    from src.db.session import get_async_engine, get_session_factory, get_async_session
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    channel_ok = False
    channel_name = ""
    dm_member_ids: list[str] = []
    async for session in get_async_session(factory):
        ch = (await session.execute(select(Channel).where(Channel.id == channel_id))).scalar_one_or_none()
        if ch:
            channel_name = ch.name
            if ch.type == "public":
                channel_ok = True
            else:
                channel_ok = any(m.user_id == user_id for m in ch.members)
            if ch.type == "dm":
                dm_member_ids = [m.user_id for m in ch.members if m.user_id != user_id]
        await session.commit()

    if not channel_ok:
        await websocket.close(code=4003)
        return

    await manager.connect(websocket, channel_id, user_id, username)

    # Feature 5: mark user online
    presence_service.set_online(user_id, username)
    await manager.broadcast_all({
        "type": "presence_update",
        "user_id": user_id,
        "status": "online",
        "custom_status": presence_service.get(user_id).get("custom_status"),
    })

    # Announce presence to channel
    await manager.broadcast(channel_id, {"type": "online", "users": manager.online_users(channel_id)})

    try:
        while True:
            data = await websocket.receive_json()

            # Feature 5: heartbeat ping/pong
            if data.get("type") == "ping":
                presence_service.record_ping(user_id)
                await websocket.send_json({"type": "pong"})
                continue

            content = (data.get("content") or "").strip()
            if not content:
                continue

            parent_id: str | None = data.get("parent_id")

            # Persist message
            msg_id = ""
            created = ""
            thread_count = 0
            last_reply_at_iso = None

            async for session in get_async_session(factory):
                # Validate parent_id if set
                parent_msg = None
                if parent_id:
                    parent_msg = (await session.execute(
                        select(ChatMessage).where(
                            and_(ChatMessage.id == parent_id, ChatMessage.channel_id == channel_id)
                        )
                    )).scalar_one_or_none()
                    if not parent_msg:
                        parent_id = None  # silently ignore invalid parent

                msg = ChatMessage(
                    id=str(uuid.uuid4()),
                    channel_id=channel_id,
                    sender_id=user_id,
                    sender_username=username,
                    content=content,
                    parent_id=parent_id,
                )
                session.add(msg)
                await session.flush()

                if parent_msg:
                    parent_msg.thread_count = (parent_msg.thread_count or 0) + 1
                    now = datetime.now(timezone.utc)
                    parent_msg.last_reply_at = now
                    last_reply_at_iso = now.isoformat()

                await session.commit()
                await session.refresh(msg)
                msg_id = msg.id
                created = msg.created_at.isoformat()
                thread_count = msg.thread_count

            # Broadcast thread_reply event so clients can update previews
            if parent_id and last_reply_at_iso:
                async for session in get_async_session(factory):
                    parent_msg2 = (await session.execute(
                        select(ChatMessage).where(ChatMessage.id == parent_id)
                    )).scalar_one_or_none()
                    if parent_msg2:
                        await manager.broadcast(channel_id, {
                            "type": "thread_reply",
                            "parent_id": parent_id,
                            "reply_count": parent_msg2.thread_count,
                            "last_reply_at": last_reply_at_iso,
                        })
                    await session.commit()

            await manager.broadcast(channel_id, {
                "type": "message",
                "id": msg_id,
                "channel_id": channel_id,
                "sender_id": user_id,
                "sender_username": username,
                "content": content,
                "created_at": created,
                "parent_id": parent_id,
                "thread_count": thread_count,
                "last_reply_at": last_reply_at_iso,
            })

            # Feature 4: @mention notifications
            async for session in get_async_session(factory):
                await _process_mentions(content, channel_id, channel_name, msg_id, username, user_id, session)
                await session.commit()

            # Feature 4: DM notifications for offline recipients
            if dm_member_ids:
                from src.services.notification_service import create_and_push as _notif
                online_ids = manager.online_user_ids(channel_id)
                async for session in get_async_session(factory):
                    for mid in dm_member_ids:
                        if mid not in online_ids:
                            await _notif(
                                session, mid, "direct_message",
                                f"New message from {username}",
                                content[:120],
                                f"/chat?channel={channel_id}",
                            )
                    await session.commit()

    except WebSocketDisconnect:
        manager.disconnect(websocket, channel_id)

        # Feature 5: mark offline only if no other sockets remain for this user
        if not manager.is_user_connected(user_id):
            presence_service.set_offline(user_id)
            await manager.broadcast_all({
                "type": "presence_update",
                "user_id": user_id,
                "status": "offline",
                "custom_status": presence_service.get(user_id).get("custom_status"),
            })

        await manager.broadcast(channel_id, {"type": "online", "users": manager.online_users(channel_id)})
