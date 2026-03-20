"""Team lifecycle service."""

from src.core.exceptions import TeamNotFoundError, AuthorizationError
from src.core.interfaces import IVectorStore
from src.core.rbac import UserContext, can_manage_team
from src.repositories.team_repository import TeamRepository
from src.repositories.document_repository import DocumentRepository
from src.repositories.audit_repository import AuditRepository


class TeamService:
    def __init__(
        self,
        team_repo: TeamRepository,
        document_repo: DocumentRepository,
        audit_repo: AuditRepository,
        vector_store: IVectorStore,
    ) -> None:
        self._team_repo = team_repo
        self._doc_repo = document_repo
        self._audit_repo = audit_repo
        self._vector_store = vector_store

    async def delete_team(self, team_id: str, user: UserContext) -> None:
        team = await self._team_repo.get_by_id(team_id)
        if not team:
            raise TeamNotFoundError(f"Team {team_id} not found")

        if not can_manage_team(user, team.created_by):
            raise AuthorizationError("Only team creator or admin can delete a team")

        # Revert documents that were only in this team to confidential
        orphaned_docs = await self._team_repo.get_documents_only_in_team(team_id)
        for doc in orphaned_docs:
            doc.visibility = "confidential"
            await self._doc_repo.update(doc)
            await self._vector_store.update_metadata(
                doc.id, {"visibility": "confidential", "allowed_teams": ""}
            )
            await self._audit_repo.log_document_change(
                document_id=doc.id,
                user_id=user.user_id,
                action="visibility_changed",
                old_metadata={"visibility": "team"},
                new_metadata={"visibility": "confidential", "reason": "team_deleted"},
            )

        # Log team deletion
        await self._audit_repo.log_team_change(
            team_id=team_id,
            user_id=user.user_id,
            action="deleted",
        )

        await self._team_repo.delete(team_id)
