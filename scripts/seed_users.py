"""Seed two default users: admin and analyst.

Run once after first startup:
  python scripts/seed_users.py
"""

import asyncio
import sys
from pathlib import Path

# Make sure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import get_settings
from src.core.security import hash_password
from src.db.session import get_async_engine, get_session_factory, get_async_session
from src.models.user import User, Role
from sqlalchemy import select
import uuid


USERS = [
    {
        "username": "admin",
        "email": "admin@example.com",
        "password": "Admin1234!",
        "role": "admin",
    },
    {
        "username": "alice",
        "email": "alice@example.com",
        "password": "Alice1234!",
        "role": "analyst",
    },
]


async def seed() -> None:
    settings = get_settings()
    engine = get_async_engine(settings.DATABASE_URL)
    factory = get_session_factory(engine)

    async for session in get_async_session(factory):
        for u in USERS:
            # Skip if already exists
            result = await session.execute(select(User).where(User.username == u["username"]))
            if result.scalar_one_or_none():
                print(f"  [skip] {u['username']} already exists")
                continue

            role_result = await session.execute(select(Role).where(Role.name == u["role"]))
            role = role_result.scalar_one_or_none()

            user = User(
                id=str(uuid.uuid4()),
                username=u["username"],
                email=u["email"],
                hashed_password=hash_password(u["password"]),
                is_active=True,
            )
            if role:
                user.roles.append(role)

            session.add(user)
            print(f"  [created] {u['username']} ({u['role']}) — {u['email']} / {u['password']}")

        await session.commit()

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
