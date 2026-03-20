"""Document lifecycle service."""

from src.core.exceptions import DocumentNotFoundError, AuthorizationError, VectorStoreError
from src.core.interfaces import IVectorStore
from src.core.rbac import UserContext
from src.repositories.document_repository import DocumentRepository
from src.repositories.audit_repository import AuditRepository


class DocumentService:
    def __init__(
        self,
        document_repo: DocumentRepository,
        audit_repo: AuditRepository,
        vector_store: IVectorStore,
    ) -> None:
        self._doc_repo = document_repo
        self._audit_repo = audit_repo
        self._vector_store = vector_store

    async def change_visibility(
        self,
        document_id: str,
        new_visibility: str,
        team_ids: list[str] | None,
        user_ids: list[str] | None,
        user: UserContext,
    ) -> None:
        doc = await self._doc_repo.get_by_id(document_id)
        if not doc:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        if doc.owner_id != user.user_id and "admin" not in user.roles:
            raise AuthorizationError("Only owner or admin can change visibility")

        old_meta = {
            "visibility": doc.visibility,
            "team_access": [ta.team_id for ta in doc.team_access],
            "user_access": [ua.user_id for ua in doc.user_access],
        }

        # Update DB fields
        doc.visibility = new_visibility
        await self._doc_repo.update(doc)

        if team_ids is not None:
            await self._doc_repo.set_team_access(document_id, team_ids)
        if user_ids is not None:
            await self._doc_repo.set_user_access(document_id, user_ids)

        # Update vector store metadata atomically
        vs_meta = {
            "visibility": new_visibility,
            "allowed_teams": "|" + "|".join(team_ids or []) + "|" if team_ids else "",
            "allowed_users": "|" + "|".join(user_ids or []) + "|" if user_ids else "",
        }
        try:
            await self._vector_store.update_metadata(document_id, vs_meta)
        except VectorStoreError:
            # Rollback DB change
            doc.visibility = old_meta["visibility"]
            await self._doc_repo.update(doc)
            await self._doc_repo.set_team_access(document_id, old_meta["team_access"])
            await self._doc_repo.set_user_access(document_id, old_meta["user_access"])
            raise

        new_meta = {"visibility": new_visibility, "team_ids": team_ids, "user_ids": user_ids}
        await self._audit_repo.log_document_change(
            document_id=document_id,
            user_id=user.user_id,
            action="visibility_changed",
            old_metadata=old_meta,
            new_metadata=new_meta,
        )

    async def transfer_ownership(
        self,
        document_id: str,
        new_owner_id: str,
        user: UserContext,
    ) -> None:
        doc = await self._doc_repo.get_by_id(document_id)
        if not doc:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        if doc.owner_id != user.user_id and "admin" not in user.roles:
            raise AuthorizationError("Only owner or admin can transfer ownership")

        old_owner = doc.owner_id
        await self._doc_repo.transfer_ownership(document_id, new_owner_id)
        await self._vector_store.update_metadata(document_id, {"owner_id": new_owner_id})
        await self._audit_repo.log_document_change(
            document_id=document_id,
            user_id=user.user_id,
            action="ownership_transferred",
            old_metadata={"owner_id": old_owner},
            new_metadata={"owner_id": new_owner_id},
        )
