"""Fixtures for API tests."""
import os
import pytest

from src.models import (
    User, Role, Team, TeamMembership, Collection, Document,
    DocumentTeamAccess, DocumentUserAccess, user_roles,
)
from src.core.security import hash_password, create_access_token


# Secret matches .env used by the app's get_settings()
_SECRET = "dev-secret-change-me-in-production-min-32-chars"


def _make_headers(user_id: str, roles: list[str], team_ids: list[str]) -> dict:
    token = create_access_token(
        data={"sub": user_id, "roles": roles, "team_ids": team_ids},
        secret_key=_SECRET,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# EXTRA USERS
# ---------------------------------------------------------------------------

@pytest.fixture
async def admin_user_fixture(db_session):
    user = User(username="admin2", email="admin2@example.com",
                hashed_password=hash_password("adminpass"))
    role = Role(name="admin", description="Administrator")
    db_session.add_all([user, role])
    await db_session.flush()
    await db_session.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def viewer_user(db_session):
    user = User(username="viewer1", email="viewer1@example.com",
                hashed_password=hash_password("pass1234"))
    role = Role(name="viewer", description="Viewer")
    db_session.add_all([user, role])
    await db_session.flush()
    await db_session.execute(user_roles.insert().values(user_id=user.id, role_id=role.id))
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def other_user(db_session):
    user = User(username="otheruser", email="other@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def non_member_user(db_session):
    user = User(username="nonmember", email="nonmember@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def allowed_user(db_session):
    user = User(username="alloweduser", email="allowed@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def extra_user_a(db_session):
    user = User(username="extraA", email="extraA@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def extra_user_b(db_session):
    user = User(username="extraB", email="extraB@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# HEADER FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_headers(admin_user_fixture):
    return _make_headers(admin_user_fixture.id, ["admin"], [])


@pytest.fixture
def viewer_headers(viewer_user):
    return _make_headers(viewer_user.id, ["viewer"], [])


@pytest.fixture
async def team_fixture(db_session, registered_user):
    """A team created by registered_user."""
    team = Team(name="API Test Team", description="For API tests",
                created_by=registered_user.id)
    db_session.add(team)
    await db_session.flush()
    db_session.add(TeamMembership(team_id=team.id, user_id=registered_user.id))
    await db_session.commit()
    await db_session.refresh(team)
    return team


@pytest.fixture
def creator_headers(registered_user, team_fixture):
    return _make_headers(registered_user.id, ["analyst"], [team_fixture.id])


@pytest.fixture
def owner_headers(registered_user):
    return _make_headers(registered_user.id, ["analyst"], [])


@pytest.fixture
def other_user_headers(other_user):
    return _make_headers(other_user.id, ["viewer"], [])


@pytest.fixture
def non_member_headers(non_member_user):
    return _make_headers(non_member_user.id, ["viewer"], [])


@pytest.fixture
async def team_member_user(db_session, team_fixture):
    user = User(username="member1", email="member1@example.com",
                hashed_password=hash_password("pass1234"))
    db_session.add(user)
    await db_session.flush()
    db_session.add(TeamMembership(team_id=team_fixture.id, user_id=user.id))
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def team_member_headers(team_member_user, team_fixture):
    return _make_headers(team_member_user.id, ["viewer"], [team_fixture.id])


@pytest.fixture
def allowed_user_headers(allowed_user):
    return _make_headers(allowed_user.id, ["viewer"], [])


@pytest.fixture
async def multi_team_user(db_session):
    user = User(username="multiteam", email="multiteam@example.com",
                hashed_password=hash_password("pass1234"))
    team_a = Team(name="Team Alpha", description="", created_by="system")
    team_b = Team(name="Team Beta", description="", created_by="system")
    db_session.add_all([user, team_a, team_b])
    await db_session.flush()
    db_session.add(TeamMembership(team_id=team_a.id, user_id=user.id))
    db_session.add(TeamMembership(team_id=team_b.id, user_id=user.id))
    await db_session.commit()
    await db_session.refresh(user)
    return user, team_a, team_b


@pytest.fixture
def multi_team_user_headers(multi_team_user):
    user, team_a, team_b = multi_team_user
    return _make_headers(user.id, ["viewer"], [team_a.id, team_b.id])


# ---------------------------------------------------------------------------
# TEAM ID / DATA FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def team_id(team_fixture):
    return team_fixture.id


@pytest.fixture
def user_ids(extra_user_a, extra_user_b):
    return [extra_user_a.id, extra_user_b.id]


@pytest.fixture
def team_ids(team_fixture):
    return [team_fixture.id]


@pytest.fixture
def new_user_id(extra_user_a):
    return extra_user_a.id


@pytest.fixture
def new_user_ids(extra_user_a, extra_user_b):
    return [extra_user_a.id, extra_user_b.id]


@pytest.fixture
def existing_member_id(team_member_user):
    return team_member_user.id


@pytest.fixture
def member_user_id(team_member_user):
    return team_member_user.id


@pytest.fixture
async def other_team_name(db_session, registered_user):
    team = Team(name="Other Team", description="", created_by=registered_user.id)
    db_session.add(team)
    await db_session.commit()
    return "Other Team"


@pytest.fixture
async def user_teams(db_session, registered_user, team_fixture):
    return [team_fixture]


@pytest.fixture
async def created_teams(db_session, registered_user):
    team = Team(name="Created By User", description="", created_by=registered_user.id)
    db_session.add(team)
    await db_session.commit()
    await db_session.refresh(team)
    return [team]


@pytest.fixture
async def other_teams(db_session, other_user):
    team = Team(name="Unrelated Team", description="", created_by=other_user.id)
    db_session.add(team)
    await db_session.commit()
    await db_session.refresh(team)
    return [team]


@pytest.fixture
async def all_teams(db_session, team_fixture, other_teams):
    return [team_fixture] + other_teams


# ---------------------------------------------------------------------------
# COLLECTION FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
async def own_collection_id(db_session, registered_user):
    col = Collection(name="My Collection", owner_id=registered_user.id)
    db_session.add(col)
    await db_session.commit()
    await db_session.refresh(col)
    return col.id


@pytest.fixture
async def collection_id(db_session, registered_user):
    col = Collection(name="Test Collection", owner_id=registered_user.id)
    db_session.add(col)
    await db_session.commit()
    await db_session.refresh(col)
    return col.id


@pytest.fixture
async def user_collections(db_session, registered_user):
    cols = [Collection(name=f"Col {i}", owner_id=registered_user.id) for i in range(2)]
    db_session.add_all(cols)
    await db_session.commit()
    return cols


@pytest.fixture
async def public_collections(db_session, other_user):
    cols = [Collection(name=f"Public Col {i}", owner_id=other_user.id) for i in range(2)]
    db_session.add_all(cols)
    await db_session.commit()
    return cols


@pytest.fixture
async def collection_with_docs(db_session, registered_user):
    col = Collection(name="Col With Docs", owner_id=registered_user.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(filename="doc.txt", file_type="text/plain", visibility="public",
                   status="ready", owner_id=registered_user.id, collection_id=col.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(col)
    return col.id


# ---------------------------------------------------------------------------
# DOCUMENT FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
async def own_doc_id(db_session, registered_user):
    doc = Document(filename="own.pdf", file_type="application/pdf",
                   visibility="public", status="ready", owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
async def any_doc_id(db_session, registered_user):
    doc = Document(filename="any.pdf", file_type="application/pdf",
                   visibility="public", status="ready", owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
async def public_doc_id(db_session, other_user):
    doc = Document(filename="public.pdf", file_type="application/pdf",
                   visibility="public", status="ready", owner_id=other_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
async def team_doc_id(db_session, other_user, team_fixture):
    doc = Document(filename="team.pdf", file_type="application/pdf",
                   visibility="team", status="ready", owner_id=other_user.id)
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team_fixture.id))
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
async def confidential_doc_id(db_session, other_user, registered_user):
    doc = Document(filename="conf.pdf", file_type="application/pdf",
                   visibility="confidential", status="ready", owner_id=other_user.id)
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentUserAccess(document_id=doc.id, user_id=registered_user.id))
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
async def doc_id(db_session, registered_user):
    doc = Document(filename="test.pdf", file_type="application/pdf",
                   visibility="public", status="ready", owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
async def user_docs(db_session, registered_user):
    docs = [Document(filename=f"mine_{i}.pdf", file_type="application/pdf",
                     visibility="public", status="ready", owner_id=registered_user.id)
            for i in range(3)]
    db_session.add_all(docs)
    await db_session.commit()
    return docs


@pytest.fixture
async def public_docs(db_session, other_user):
    docs = [Document(filename=f"pub_{i}.pdf", file_type="application/pdf",
                     visibility="public", status="ready", owner_id=other_user.id)
            for i in range(3)]
    db_session.add_all(docs)
    await db_session.commit()
    return docs


@pytest.fixture
async def team_docs(db_session, other_user, team_fixture):
    docs = [Document(filename=f"team_{i}.pdf", file_type="application/pdf",
                     visibility="team", status="ready", owner_id=other_user.id)
            for i in range(2)]
    db_session.add_all(docs)
    await db_session.flush()
    for doc in docs:
        db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team_fixture.id))
    await db_session.commit()
    return docs


@pytest.fixture
async def confidential_docs(db_session, other_user):
    docs = [Document(filename=f"conf_{i}.pdf", file_type="application/pdf",
                     visibility="confidential", status="ready", owner_id=other_user.id)
            for i in range(2)]
    db_session.add_all(docs)
    await db_session.commit()
    return docs


@pytest.fixture
async def many_docs(db_session, registered_user):
    docs = [Document(filename=f"many_{i}.pdf", file_type="application/pdf",
                     visibility="public", status="ready", owner_id=registered_user.id)
            for i in range(15)]
    db_session.add_all(docs)
    await db_session.commit()
    return docs


@pytest.fixture
async def seeded_docs(db_session, registered_user):
    docs = [Document(filename=f"seeded_{i}.pdf", file_type="application/pdf",
                     visibility="public", status="ready", owner_id=registered_user.id)
            for i in range(3)]
    db_session.add_all(docs)
    await db_session.commit()
    return docs


# RBAC doc fixtures (document objects, not just IDs)

@pytest.fixture
async def public_doc(db_session, other_user):
    doc = Document(filename="rbac_public.pdf", file_type="application/pdf",
                   visibility="public", status="ready", owner_id=other_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.fixture
async def team_doc(db_session, other_user, team_fixture):
    doc = Document(filename="rbac_team.pdf", file_type="application/pdf",
                   visibility="team", status="ready", owner_id=other_user.id)
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team_fixture.id))
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.fixture
async def confidential_doc(db_session, other_user, allowed_user):
    doc = Document(filename="rbac_conf.pdf", file_type="application/pdf",
                   visibility="confidential", status="ready", owner_id=other_user.id)
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentUserAccess(document_id=doc.id, user_id=allowed_user.id))
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# COMPLIANCE FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
async def scanned_doc_id(db_session, registered_user):
    doc = Document(filename="scanned.pdf", file_type="application/pdf",
                   visibility="public", status="ready", owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
async def flagged_doc_id(db_session, registered_user):
    doc = Document(filename="flagged.pdf", file_type="application/pdf",
                   visibility="public", status="flagged",
                   owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
async def blocked_doc_id(db_session, registered_user):
    doc = Document(filename="blocked.pdf", file_type="application/pdf",
                   visibility="public", status="compliance_blocked",
                   owner_id=registered_user.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc.id


@pytest.fixture
def custom_rule_id():
    return "CUSTOM_RULE_001"


# ---------------------------------------------------------------------------
# FILE FIXTURES
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_pdf(tmp_path):
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
