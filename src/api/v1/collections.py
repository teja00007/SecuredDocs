"""Collection management endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_collection_repo, get_db, require_permission
from src.core.rbac import UserContext
from src.models.document import Collection
from src.repositories.collection_repository import CollectionRepository
from src.schemas.collection import CollectionCreateRequest, CollectionResponse

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post("", response_model=CollectionResponse, status_code=status.HTTP_201_CREATED)
async def create_collection(
    body: CollectionCreateRequest,
    user: UserContext = Depends(require_permission("collection:write")),
    collection_repo: CollectionRepository = Depends(get_collection_repo),
    db: AsyncSession = Depends(get_db),
):
    collection = Collection(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        owner_id=user.user_id,
        company_id=user.company_id,
        is_public=False,
    )
    created = await collection_repo.create(collection)
    await db.commit()

    doc_count = await collection_repo.get_document_count(created.id)
    return _col_to_response(created, doc_count)


@router.get("", response_model=list[CollectionResponse])
async def list_collections(
    skip: int = 0,
    limit: int = 50,
    user: UserContext = Depends(require_permission("collection:read")),
    collection_repo: CollectionRepository = Depends(get_collection_repo),
):
    collections = await collection_repo.list_for_user(
        user_id=user.user_id, skip=skip, limit=limit, company_id=user.company_id
    )
    result = []
    for col in collections:
        doc_count = await collection_repo.get_document_count(col.id)
        result.append(_col_to_response(col, doc_count))
    return result


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: str,
    user: UserContext = Depends(require_permission("collection:read")),
    collection_repo: CollectionRepository = Depends(get_collection_repo),
):
    col = await collection_repo.get_by_id(collection_id)
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    # Company isolation: non-super-admins can only see their own company's collections
    if not user.is_super_admin and col.company_id and col.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    if col.owner_id != user.user_id and not col.is_public and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    doc_count = await collection_repo.get_document_count(collection_id)
    return _col_to_response(col, doc_count)


@router.delete("/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: str,
    user: UserContext = Depends(get_current_user),
    collection_repo: CollectionRepository = Depends(get_collection_repo),
    db: AsyncSession = Depends(get_db),
):
    col = await collection_repo.get_by_id(collection_id)
    if not col:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    if not user.is_super_admin and col.company_id and col.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    if col.owner_id != user.user_id and "admin" not in user.roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owner or admin can delete")
    await collection_repo.delete(collection_id)
    await db.commit()


def _col_to_response(col: Collection, doc_count: int) -> CollectionResponse:
    return CollectionResponse(
        id=col.id,
        name=col.name,
        description=col.description,
        owner_id=col.owner_id,
        is_public=col.is_public,
        document_count=doc_count,
        created_at=col.created_at,
    )
