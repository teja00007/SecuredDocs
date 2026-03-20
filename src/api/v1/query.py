"""Query endpoint — main RAG interface."""

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.v1.deps import get_rag_service, require_permission
from src.core.rbac import UserContext
from src.schemas.query import QueryRequest, QueryResponse, SourceResponse
from src.services.rag_service import RAGService

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    user: UserContext = Depends(require_permission("query:execute")),
    rag_svc: RAGService = Depends(get_rag_service),
):
    try:
        result = await rag_svc.query(
            query_text=body.query,
            user=user,
            collection_id=body.collection_id,
            top_k=body.top_k,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query failed: {e}",
        )

    sources = [SourceResponse(**s) for s in result["sources"]]
    return QueryResponse(answer=result["answer"], sources=sources)
