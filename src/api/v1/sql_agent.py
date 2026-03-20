"""SQL Agent API — natural language to read-only SQL queries."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.api.v1.deps import get_current_user, get_db, require_permission
from src.core.rbac import UserContext
from src.db.session import AsyncSession
from src.config import get_settings
from src.llm import get_llm
from src.services.sql_agent import SQLAgent

router = APIRouter(prefix="/query/sql", tags=["sql-agent"])


class SQLQueryRequest(BaseModel):
    question: str


class SQLQueryResponse(BaseModel):
    sql: str | None
    columns: list[str]
    rows: list[list]
    error: str | None
    row_count: int


@router.post("", response_model=SQLQueryResponse)
async def sql_query(
    body: SQLQueryRequest,
    user: UserContext = Depends(require_permission("query:execute")),
    db: AsyncSession = Depends(get_db),
):
    """Translate a natural-language question into a SQL SELECT and return results.

    - Only SELECT queries are executed (enforced server-side).
    - Results capped at 500 rows.
    - Requires `query:execute` permission (analyst or admin).
    """
    if not body.question.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Question must not be empty.")

    settings = get_settings()
    llm = get_llm(settings)
    agent = SQLAgent(llm=llm)

    result = await agent.query(question=body.question, db=db)
    return SQLQueryResponse(**result)
