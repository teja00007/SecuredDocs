"""
Shared Test Fixtures — conftest.py

Provides reusable fixtures for all test modules.
All fixtures use in-memory SQLite and embedded ChromaDB for isolation.
"""
import pytest
import os
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool, StaticPool

from src.db.base import Base
from src.models import (
    User, Role, Permission, Team, TeamMembership,
    Collection, Document, DocumentTeamAccess, DocumentUserAccess,
    user_roles, role_permissions,
)
from src.core.security import hash_password, create_access_token, create_refresh_token


# ============================================================================
# DATABASE FIXTURES
# ============================================================================

@pytest.fixture
async def db_engine():
    """Create in-memory SQLite async engine for testing.

    Uses StaticPool so all sessions share the same in-memory connection
    and can see tables created during setup.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Yield an async DB session, rollback after each test."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ============================================================================
# USER FIXTURES
# ============================================================================

@pytest.fixture
async def registered_user(db_session):
    """A registered user with default 'viewer' role."""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=hash_password("password123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def admin_user(db_session):
    """A user with 'admin' role."""
    user = User(
        username="admin",
        email="admin@example.com",
        hashed_password=hash_password("adminpass"),
    )
    role = Role(name="admin", description="Administrator")
    db_session.add(role)
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        user_roles.insert().values(user_id=user.id, role_id=role.id)
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def analyst_user(db_session):
    """A user with 'analyst' role."""
    user = User(
        username="analyst",
        email="analyst@example.com",
        hashed_password=hash_password("analystpass"),
    )
    role = Role(name="analyst", description="Analyst")
    db_session.add(role)
    db_session.add(user)
    await db_session.flush()
    await db_session.execute(
        user_roles.insert().values(user_id=user.id, role_id=role.id)
    )
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def inactive_user(db_session):
    """A registered but deactivated user."""
    user = User(
        username="inactive",
        email="inactive@example.com",
        hashed_password=hash_password("password123"),
        is_active=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ============================================================================
# TEAM FIXTURES
# ============================================================================

@pytest.fixture
async def sample_team(db_session, registered_user):
    """A team/DL created by registered_user with 2 members."""
    team = Team(
        name="Backend Team",
        description="Backend engineers",
        created_by=registered_user.id,
    )
    db_session.add(team)
    await db_session.flush()

    m1 = TeamMembership(team_id=team.id, user_id=registered_user.id)
    db_session.add(m1)

    user2 = User(
        username="teammate",
        email="teammate@example.com",
        hashed_password=hash_password("password123"),
    )
    db_session.add(user2)
    await db_session.flush()

    m2 = TeamMembership(team_id=team.id, user_id=user2.id)
    db_session.add(m2)
    await db_session.commit()
    await db_session.refresh(team)
    return team


# ============================================================================
# COLLECTION FIXTURES
# ============================================================================

@pytest.fixture
async def sample_collection(db_session, registered_user):
    """A collection owned by registered_user."""
    collection = Collection(
        name="Test Collection",
        description="A test collection",
        owner_id=registered_user.id,
    )
    db_session.add(collection)
    await db_session.commit()
    await db_session.refresh(collection)
    return collection


# ============================================================================
# COMPLIANCE FIXTURES (text fixtures)
# ============================================================================

@pytest.fixture
def clean_text():
    """Text with no compliance violations."""
    return "This is a regular business document about project planning and timelines."


@pytest.fixture
def text_with_ssn():
    """Text containing a Social Security Number."""
    return "Employee records: Name: John Doe, SSN: 123-45-6789, Department: Engineering"


@pytest.fixture
def text_with_ssn_and_credit_card():
    """Text with both SSN and credit card number."""
    return "SSN: 123-45-6789. Payment: 4111111111111111 exp 12/25"


@pytest.fixture
def text_with_email():
    """Text containing an email address (GDPR PII)."""
    return "Please contact john.doe@company.com for more information."


# ============================================================================
# API CLIENT FIXTURES
# ============================================================================

_TEST_SECRET = "test-secret-key-for-unit-tests-only-32chars"


@pytest.fixture
def client(db_session):
    """HTTP test client with in-memory DB injected."""
    from src.main import app
    from src.api.v1.deps import get_db

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def access_token(registered_user):
    return create_access_token(
        data={"sub": registered_user.id, "roles": ["viewer"], "team_ids": []},
        secret_key=_TEST_SECRET,
    )


@pytest.fixture
def refresh_token(registered_user):
    return create_refresh_token(
        user_id=registered_user.id,
        secret_key=_TEST_SECRET,
    )


@pytest.fixture
def expired_access_token(registered_user):
    return create_access_token(
        data={"sub": registered_user.id, "roles": ["viewer"], "team_ids": []},
        secret_key=_TEST_SECRET,
        expires_delta=timedelta(seconds=-1),
    )


@pytest.fixture
def expired_refresh_token(registered_user):
    return create_refresh_token(
        user_id=registered_user.id,
        secret_key=_TEST_SECRET,
        expires_delta=timedelta(seconds=-1),
    )


@pytest.fixture
def auth_headers(access_token):
    return {"Authorization": f"Bearer {access_token}"}


# ============================================================================
# INTEGRATION TEST FIXTURES
# ============================================================================

@pytest.fixture
def sample_pdf(tmp_path):
    """A minimal valid PDF file (available to root-level integration tests)."""
    pdf_path = tmp_path / "test.pdf"
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 12 Tf 100 700 Td (Hello World) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000360 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
441
%%EOF"""
    pdf_path.write_bytes(pdf_content)
    return str(pdf_path)


@pytest.fixture
def ingested_doc_id():
    """Placeholder ID for a pre-ingested document."""
    import uuid
    return str(uuid.uuid4())


@pytest.fixture
def stopped_vector_store():
    """Placeholder representing a stopped/unavailable vector store."""
    return None


@pytest.fixture
def stopped_db():
    """Placeholder representing a stopped/unavailable database."""
    return None


@pytest.fixture
def creator_headers(auth_headers):
    """Auth headers for the document creator (alias for auth_headers)."""
    return auth_headers


@pytest.fixture
def team_id():
    """Placeholder team ID for integration tests."""
    import uuid
    return str(uuid.uuid4())


@pytest.fixture
def admin_headers(admin_user):
    """Auth headers for the admin user."""
    token = create_access_token(
        data={"sub": admin_user.id, "roles": ["admin"], "team_ids": []},
        secret_key=_TEST_SECRET,
    )
    return {"Authorization": f"Bearer {token}"}
