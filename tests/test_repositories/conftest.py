"""Fixtures for repository tests."""
import pytest

from src.repositories.user_repository import UserRepository
from src.repositories.team_repository import TeamRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.collection_repository import CollectionRepository
from src.repositories.audit_repository import AuditRepository
from src.models.user import User
from src.models.team import Team, TeamMembership
from src.models.document import Collection, Document, DocumentTeamAccess, DocumentUserAccess, VisibilityEnum


@pytest.fixture
def doc_repo(db_session):
    return DocumentRepository(db_session)


@pytest.fixture
def team_repo(db_session):
    return TeamRepository(db_session)


@pytest.fixture
def audit_repo(db_session):
    return AuditRepository(db_session)


# ============================================================================
# SHARED USER / DOCUMENT FIXTURES
# ============================================================================

@pytest.fixture
async def user(db_session):
    """A test user for repository tests."""
    u = User(username="repo_user", email="repo@test.com", hashed_password="h")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.fixture
async def saved_doc(db_session, user):
    """A saved document owned by the test user."""
    col = Collection(name="Saved Doc Col", owner_id=user.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(filename="saved.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(doc)
    return doc


@pytest.fixture
async def user_docs(db_session, user):
    """Documents owned by the test user."""
    col = Collection(name="User Docs Col", owner_id=user.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(filename="user_doc.pdf", file_type="pdf", owner_id=user.id, collection_id=col.id)
    db_session.add(doc)
    await db_session.commit()
    return [doc]


@pytest.fixture
async def public_docs(db_session):
    """Public documents owned by a separate user."""
    other = User(username="pub_doc_owner", email="pub@test.com", hashed_password="h")
    db_session.add(other)
    await db_session.flush()
    col = Collection(name="Pub Col", owner_id=other.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(
        filename="public.pdf", file_type="pdf", owner_id=other.id,
        collection_id=col.id, visibility=VisibilityEnum.PUBLIC.value,
    )
    db_session.add(doc)
    await db_session.commit()
    return [doc]


@pytest.fixture
async def user_team_ids(db_session, user):
    """List of team IDs the test user belongs to."""
    team = Team(name="User Test Team", created_by=user.id)
    db_session.add(team)
    await db_session.flush()
    db_session.add(TeamMembership(team_id=team.id, user_id=user.id))
    await db_session.commit()
    return [team.id]


@pytest.fixture
async def team_docs(db_session, user, user_team_ids):
    """Team-visibility documents assigned to the user's team."""
    col = Collection(name="Team Docs Col", owner_id=user.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(
        filename="team.pdf", file_type="pdf", owner_id=user.id,
        collection_id=col.id, visibility=VisibilityEnum.TEAM.value,
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=user_team_ids[0]))
    await db_session.commit()
    return [doc]


@pytest.fixture
async def confidential_docs(db_session, user):
    """Confidential documents with the test user in the allowed list."""
    other = User(username="conf_doc_owner", email="conf@test.com", hashed_password="h")
    db_session.add(other)
    await db_session.flush()
    col = Collection(name="Conf Col", owner_id=other.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(
        filename="conf.pdf", file_type="pdf", owner_id=other.id,
        collection_id=col.id, visibility=VisibilityEnum.CONFIDENTIAL.value,
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentUserAccess(document_id=doc.id, user_id=user.id))
    await db_session.commit()
    return [doc]


@pytest.fixture
async def many_docs(db_session, user):
    """20 documents for pagination tests."""
    col = Collection(name="Many Docs Col", owner_id=user.id)
    db_session.add(col)
    await db_session.flush()
    docs = []
    for i in range(20):
        doc = Document(
            filename=f"many_{i}.pdf", file_type="pdf",
            owner_id=user.id, collection_id=col.id,
        )
        db_session.add(doc)
        docs.append(doc)
    await db_session.commit()
    return docs


@pytest.fixture
async def multi_collection_docs(db_session, user):
    """Documents spread across two different collections."""
    col1 = Collection(name="Multi Col 1", owner_id=user.id)
    col2 = Collection(name="Multi Col 2", owner_id=user.id)
    db_session.add_all([col1, col2])
    await db_session.flush()
    doc1 = Document(filename="mcol1.pdf", file_type="pdf", owner_id=user.id, collection_id=col1.id)
    doc2 = Document(filename="mcol2.pdf", file_type="pdf", owner_id=user.id, collection_id=col2.id)
    db_session.add_all([doc1, doc2])
    await db_session.commit()
    return {"col1_id": col1.id, "col2_id": col2.id, "docs": [doc1, doc2]}


@pytest.fixture
async def new_owner(db_session):
    """A second user to receive ownership transfer."""
    u = User(username="new_owner_user", email="new_owner@test.com", hashed_password="h")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


# ============================================================================
# TEAM REPOSITORY FIXTURES
# ============================================================================

@pytest.fixture
async def team(db_session):
    """A test team for team repository tests."""
    owner = User(username="team_owner_user", email="team_owner@test.com", hashed_password="h")
    db_session.add(owner)
    await db_session.flush()
    t = Team(name="Test Repo Team", created_by=owner.id)
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest.fixture
async def single_team_docs(db_session, team):
    """Team-visibility documents assigned only to this team."""
    owner = User(username="single_td_owner", email="stdo@test.com", hashed_password="h")
    db_session.add(owner)
    await db_session.flush()
    col = Collection(name="Single Team Col", owner_id=owner.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(
        filename="single_team.pdf", file_type="pdf", owner_id=owner.id,
        collection_id=col.id, visibility=VisibilityEnum.TEAM.value,
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
    await db_session.commit()
    return [doc]


@pytest.fixture
async def multi_team_docs(db_session, team):
    """Team-visibility documents assigned to two teams (not orphan candidates)."""
    owner = User(username="multi_td_owner", email="mtdo@test.com", hashed_password="h")
    db_session.add(owner)
    await db_session.flush()
    other_team = Team(name="Other Test Team", created_by=owner.id)
    db_session.add(other_team)
    await db_session.flush()
    col = Collection(name="Multi Team Col", owner_id=owner.id)
    db_session.add(col)
    await db_session.flush()
    doc = Document(
        filename="multi_team.pdf", file_type="pdf", owner_id=owner.id,
        collection_id=col.id, visibility=VisibilityEnum.TEAM.value,
    )
    db_session.add(doc)
    await db_session.flush()
    db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=team.id))
    db_session.add(DocumentTeamAccess(document_id=doc.id, team_id=other_team.id))
    await db_session.commit()
    return [doc]


@pytest.fixture
async def saved_team(db_session):
    """A persisted team for CRUD tests."""
    creator = User(username="saved_team_creator", email="stc@test.com", hashed_password="h")
    db_session.add(creator)
    await db_session.flush()
    t = Team(name="Saved Test Team", created_by=creator.id)
    db_session.add(t)
    await db_session.commit()
    await db_session.refresh(t)
    return t


@pytest.fixture
async def user_with_teams(db_session):
    """A user who is a member of two teams."""
    u = User(username="teams_member_user", email="tmu@test.com", hashed_password="h")
    db_session.add(u)
    await db_session.flush()
    t1 = Team(name="Alpha Team", created_by=u.id)
    t2 = Team(name="Beta Team", created_by=u.id)
    db_session.add_all([t1, t2])
    await db_session.flush()
    db_session.add(TeamMembership(team_id=t1.id, user_id=u.id))
    db_session.add(TeamMembership(team_id=t2.id, user_id=u.id))
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.fixture
async def new_user(db_session):
    """A fresh user for add-member tests."""
    u = User(username="fresh_test_user", email="fresh@test.com", hashed_password="h")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.fixture
async def member(db_session, saved_team):
    """A user who is already a member of saved_team."""
    u = User(username="saved_team_member", email="stm@test.com", hashed_password="h")
    db_session.add(u)
    await db_session.flush()
    db_session.add(TeamMembership(team_id=saved_team.id, user_id=u.id))
    await db_session.commit()
    await db_session.refresh(u)
    return u
