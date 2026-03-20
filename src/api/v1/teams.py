"""Team (Distribution List) management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import (
    get_current_user, get_db, get_team_repo, get_team_service, require_permission,
)
from src.core.exceptions import TeamNotFoundError, AuthorizationError
from src.core.rbac import UserContext, can_manage_team
from src.models.team import Team, TeamMembership
from src.repositories.team_repository import TeamRepository
from src.schemas.auth import UserResponse
from src.schemas.team import (
    AddMembersRequest, TeamCreateRequest, TeamDetailResponse, TeamResponse,
)
from src.services.team_service import TeamService

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    body: TeamCreateRequest,
    user: UserContext = Depends(require_permission("dl:manage")),
    team_repo: TeamRepository = Depends(get_team_repo),
    db: AsyncSession = Depends(get_db),
):
    # Team names must be unique within the same company
    existing = await team_repo.get_by_name(body.name)
    if existing and existing.company_id == user.company_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team name already taken")

    team = Team(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        created_by=user.user_id,
        company_id=user.company_id,
    )
    created = await team_repo.create(team)

    if body.member_ids:
        for uid in body.member_ids:
            await team_repo.add_member(created.id, uid)

    await db.commit()
    members = await team_repo.get_members(created.id)
    return _team_to_response(created, len(members))


@router.get("", response_model=list[TeamResponse])
async def list_teams(
    user: UserContext = Depends(get_current_user),
    team_repo: TeamRepository = Depends(get_team_repo),
):
    teams = await team_repo.list_for_user(user.user_id, company_id=user.company_id)
    result = []
    for t in teams:
        members = await team_repo.get_members(t.id)
        result.append(_team_to_response(t, len(members)))
    return result


@router.get("/{team_id}", response_model=TeamDetailResponse)
async def get_team(
    team_id: str,
    user: UserContext = Depends(get_current_user),
    team_repo: TeamRepository = Depends(get_team_repo),
):
    team = await team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    members = await team_repo.get_members(team_id)
    member_responses = [
        UserResponse(
            id=m.id,
            username=m.username,
            email=m.email,
            is_active=m.is_active,
            roles=[r.name for r in m.roles],
            teams=[mb.team_id for mb in m.team_memberships],
            created_at=m.created_at,
        )
        for m in members
    ]

    return TeamDetailResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        created_by=team.created_by,
        members=member_responses,
        created_at=team.created_at,
    )


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: str,
    body: TeamCreateRequest,
    user: UserContext = Depends(get_current_user),
    team_repo: TeamRepository = Depends(get_team_repo),
    db: AsyncSession = Depends(get_db),
):
    team = await team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if not can_manage_team(user, team.created_by):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only creator or admin can edit")

    team.name = body.name
    if body.description is not None:
        team.description = body.description
    updated = await team_repo.update(team)
    await db.commit()

    members = await team_repo.get_members(updated.id)
    return _team_to_response(updated, len(members))


@router.post("/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
async def add_members(
    team_id: str,
    body: AddMembersRequest,
    user: UserContext = Depends(get_current_user),
    team_repo: TeamRepository = Depends(get_team_repo),
    db: AsyncSession = Depends(get_db),
):
    team = await team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if not can_manage_team(user, team.created_by):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only creator or admin can manage members")

    for uid in body.user_ids:
        await team_repo.add_member(team_id, uid)
    await db.commit()


@router.delete("/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    team_id: str,
    member_id: str,
    user: UserContext = Depends(get_current_user),
    team_repo: TeamRepository = Depends(get_team_repo),
    db: AsyncSession = Depends(get_db),
):
    team = await team_repo.get_by_id(team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    if not can_manage_team(user, team.created_by):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only creator or admin can manage members")

    await team_repo.remove_member(team_id, member_id)
    await db.commit()


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: str,
    user: UserContext = Depends(get_current_user),
    team_svc: TeamService = Depends(get_team_service),
    db: AsyncSession = Depends(get_db),
):
    try:
        await team_svc.delete_team(team_id, user)
        await db.commit()
    except TeamNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


def _team_to_response(team: Team, member_count: int) -> TeamResponse:
    return TeamResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        created_by=team.created_by,
        member_count=member_count,
        created_at=team.created_at,
    )
