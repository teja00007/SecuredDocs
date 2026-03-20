"""Audit log data access layer."""

import math
from datetime import datetime, timezone, timedelta

from sqlalchemy import case, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.audit import QueryLog, IngestionLog, DocumentAuditLog, TeamAuditLog
from src.models.user import User
from src.models.conversation import ConversationMessage
from src.models.document import Collection, Document


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log_query(
        self,
        user_id: str,
        query_text: str,
        chunks_retrieved: int,
        response_length: int,
        latency_ms: int,
        # Eval-dashboard fields (all optional for backward compat)
        retrieval_score: float | None = None,
        chunk_count_retrieved: int | None = None,
        answer_has_sources: bool | None = None,
        answer_length: int | None = None,
        feedback_score: int | None = None,
        latency_retrieval_ms: float | None = None,
        latency_generation_ms: float | None = None,
        collection_id: str | None = None,
    ) -> None:
        entry = QueryLog(
            user_id=user_id,
            query_text=query_text,
            chunks_retrieved=chunks_retrieved,
            response_length=response_length,
            latency_ms=latency_ms,
            retrieval_score=retrieval_score,
            chunk_count_retrieved=chunk_count_retrieved,
            answer_has_sources=answer_has_sources,
            answer_length=answer_length,
            feedback_score=feedback_score,
            latency_retrieval_ms=latency_retrieval_ms,
            latency_generation_ms=latency_generation_ms,
            collection_id=collection_id,
        )
        self._session.add(entry)
        await self._session.flush()

    async def log_ingestion(
        self,
        document_id: str,
        user_id: str,
        status: str,
        error_message: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        entry = IngestionLog(
            document_id=document_id,
            user_id=user_id,
            status=status,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        self._session.add(entry)
        await self._session.flush()

    async def log_document_change(
        self,
        document_id: str,
        user_id: str,
        action: str,
        old_metadata: dict | None = None,
        new_metadata: dict | None = None,
    ) -> None:
        entry = DocumentAuditLog(
            document_id=document_id,
            user_id=user_id,
            action=action,
            old_metadata=old_metadata,
            new_metadata=new_metadata,
        )
        self._session.add(entry)
        await self._session.flush()

    async def get_query_stats(self, days: int = 30, offset_days: int = 0) -> dict:
        now = datetime.now(timezone.utc)
        until = now - timedelta(days=offset_days) if offset_days > 0 else now
        since = until - timedelta(days=days)
        result = await self._session.execute(
            select(
                func.count(QueryLog.id).label("total"),
                func.avg(QueryLog.latency_ms).label("avg_latency_ms"),
                func.avg(QueryLog.chunks_retrieved).label("avg_chunks"),
                func.count(func.distinct(QueryLog.user_id)).label("active_users"),
            ).where(QueryLog.created_at >= since, QueryLog.created_at < until)
        )
        row = result.one()
        return {
            "total_queries": row.total or 0,
            "avg_latency_ms": round(row.avg_latency_ms or 0),
            "avg_chunks_retrieved": round(row.avg_chunks or 0, 1),
            "active_users": row.active_users or 0,
            "days": days,
        }

    async def get_queries_per_day(self, days: int = 14) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self._session.execute(
            select(
                func.date(QueryLog.created_at).label("day"),
                func.count(QueryLog.id).label("count"),
            )
            .where(QueryLog.created_at >= since)
            .group_by(func.date(QueryLog.created_at))
            .order_by(func.date(QueryLog.created_at))
        )
        rows = result.all()
        # Fill in missing days with 0
        counts = {str(r.day): r.count for r in rows}
        result_days = []
        for i in range(days):
            d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).date()
            result_days.append({"day": str(d), "count": counts.get(str(d), 0)})
        return result_days

    async def get_top_users(self, limit: int = 10, days: int = 30) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self._session.execute(
            select(
                QueryLog.user_id,
                func.count(QueryLog.id).label("query_count"),
                func.avg(QueryLog.latency_ms).label("avg_latency_ms"),
            )
            .where(QueryLog.created_at >= since)
            .group_by(QueryLog.user_id)
            .order_by(func.count(QueryLog.id).desc())
            .limit(limit)
        )
        rows = result.all()
        # Fetch usernames
        user_ids = [r.user_id for r in rows]
        users_result = await self._session.execute(
            select(User.id, User.username).where(User.id.in_(user_ids))
        )
        username_map = {u.id: u.username for u in users_result.all()}
        return [
            {
                "user_id": r.user_id,
                "username": username_map.get(r.user_id, r.user_id[:8]),
                "query_count": r.query_count,
                "avg_latency_ms": round(r.avg_latency_ms or 0),
            }
            for r in rows
        ]

    async def get_recent_queries(self, limit: int = 20) -> list[dict]:
        result = await self._session.execute(
            select(QueryLog)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        )
        logs = result.scalars().all()
        return [
            {
                "id": log.id,
                "username": log.user.username if log.user else log.user_id[:8],
                "query_text": log.query_text[:120] + ("…" if len(log.query_text) > 120 else ""),
                "chunks_retrieved": log.chunks_retrieved,
                "latency_ms": log.latency_ms,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]

    async def get_unanswered_rate(self, days: int = 30) -> dict:
        """% of queries that retrieved 0 chunks (no document context found)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self._session.execute(
            select(
                func.count(QueryLog.id).label("total"),
                func.sum(
                    case((QueryLog.chunks_retrieved == 0, 1), else_=0)
                ).label("unanswered"),
            ).where(QueryLog.created_at >= since)
        )
        row = result.one()
        total = row.total or 0
        unanswered = int(row.unanswered or 0)
        rate = round((unanswered / total) * 100, 1) if total else 0.0
        return {"total": total, "unanswered": unanswered, "rate_pct": rate}

    async def get_feedback_stats(self, days: int = 30) -> dict:
        """Count of thumbs-up / thumbs-down from assistant messages in the window."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self._session.execute(
            select(
                ConversationMessage.feedback,
                func.count(ConversationMessage.id).label("cnt"),
            )
            .where(
                ConversationMessage.role == "assistant",
                ConversationMessage.feedback.isnot(None),
                ConversationMessage.created_at >= since,
            )
            .group_by(ConversationMessage.feedback)
        )
        rows = result.all()
        counts = {r.feedback: r.cnt for r in rows}
        helpful = counts.get(1, 0)
        unhelpful = counts.get(-1, 0)
        total = helpful + unhelpful
        satisfaction = round((helpful / total) * 100, 1) if total else None
        return {"helpful": helpful, "unhelpful": unhelpful, "satisfaction_pct": satisfaction}

    async def get_latency_percentiles(self, days: int = 30) -> dict:
        """Approximate P50 / P95 latency over the window (SQLite-compatible)."""
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self._session.execute(
            select(QueryLog.latency_ms)
            .where(QueryLog.created_at >= since)
            .order_by(QueryLog.latency_ms)
        )
        vals = [r[0] for r in result.all()]
        if not vals:
            return {"p50_ms": 0, "p95_ms": 0, "p99_ms": 0}

        def percentile(data: list[int], pct: float) -> int:
            idx = max(0, math.ceil(len(data) * pct / 100) - 1)
            return data[min(idx, len(data) - 1)]

        return {
            "p50_ms": percentile(vals, 50),
            "p95_ms": percentile(vals, 95),
            "p99_ms": percentile(vals, 99),
        }

    async def get_document_stats(self) -> dict:
        """Total documents, ready count, and failed count."""
        result = await self._session.execute(
            select(Document.status, func.count(Document.id).label("cnt"))
            .group_by(Document.status)
        )
        rows = result.all()
        counts = {r.status: r.cnt for r in rows}
        total = sum(counts.values())
        return {
            "total": total,
            "ready": counts.get("ready", 0),
            "failed": counts.get("failed", 0) + counts.get("embedding_failed", 0),
            "processing": counts.get("processing", 0) + counts.get("pending", 0),
            "compliance_blocked": counts.get("compliance_blocked", 0) + counts.get("flagged", 0),
        }

    async def get_zero_chunk_queries(self, days: int = 30, limit: int = 10) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self._session.execute(
            select(QueryLog)
            .where(QueryLog.created_at >= since, QueryLog.chunks_retrieved == 0)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        )
        logs = result.scalars().all()
        return [
            {
                "query_text": log.query_text[:120] + ("…" if len(log.query_text) > 120 else ""),
                "username": log.user.username if log.user else log.user_id[:8],
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]

    async def log_team_change(
        self,
        team_id: str,
        user_id: str,
        action: str,
        member_id: str | None = None,
    ) -> None:
        entry = TeamAuditLog(
            team_id=team_id,
            user_id=user_id,
            action=action,
            target_user_id=member_id,
        )
        self._session.add(entry)
        await self._session.flush()

    # ── Eval-dashboard queries ────────────────────────────────────────────────

    async def get_eval_overview(
        self, days: int = 30, collection_id: str | None = None
    ) -> dict:
        """Return aggregated eval metrics for the overview dashboard."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = select(
            func.count(QueryLog.id).label("total"),
            func.sum(
                case((QueryLog.chunks_retrieved > 0, 1), else_=0)
            ).label("answered"),
            func.avg(QueryLog.chunk_count_retrieved).label("avg_chunks"),
            func.avg(QueryLog.retrieval_score).label("avg_retrieval_score"),
            func.avg(QueryLog.latency_ms).label("avg_latency_ms"),
            func.sum(
                case((QueryLog.answer_has_sources == False, 1), else_=0)  # noqa: E712
            ).label("zero_source"),
            func.sum(
                case((QueryLog.feedback_score == 1, 1), else_=0)
            ).label("helpful"),
            func.sum(
                case((QueryLog.feedback_score == -1, 1), else_=0)
            ).label("unhelpful"),
        ).where(QueryLog.created_at >= since)

        if collection_id:
            stmt = stmt.where(QueryLog.collection_id == collection_id)

        row = (await self._session.execute(stmt)).one()

        total = row.total or 0
        answered = int(row.answered or 0)
        helpful = int(row.helpful or 0)
        unhelpful = int(row.unhelpful or 0)
        feedback_total = helpful + unhelpful
        satisfaction = round((helpful / feedback_total) * 100, 1) if feedback_total else None
        no_feedback = total - feedback_total

        # Queries-by-day breakdown
        day_stmt = (
            select(
                func.date(QueryLog.created_at).label("day"),
                func.count(QueryLog.id).label("count"),
                func.sum(
                    case((QueryLog.chunks_retrieved > 0, 1), else_=0)
                ).label("answered"),
            )
            .where(QueryLog.created_at >= since)
            .group_by(func.date(QueryLog.created_at))
            .order_by(func.date(QueryLog.created_at))
        )
        if collection_id:
            day_stmt = day_stmt.where(QueryLog.collection_id == collection_id)

        day_rows = (await self._session.execute(day_stmt)).all()
        counts_map = {str(r.day): (r.count, int(r.answered or 0)) for r in day_rows}
        queries_by_day = []
        for i in range(days):
            d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).date()
            cnt, ans = counts_map.get(str(d), (0, 0))
            queries_by_day.append({"date": str(d), "count": cnt, "answered": ans})

        answered_rate = round((answered / total) * 100, 1) if total else 0.0

        return {
            "period_days": days,
            "total_queries": total,
            "answered_rate_pct": answered_rate,
            "avg_chunks_per_query": round(float(row.avg_chunks or 0), 2),
            "avg_retrieval_score": round(float(row.avg_retrieval_score or 0), 4),
            "avg_latency_ms": round(float(row.avg_latency_ms or 0)),
            "feedback": {
                "helpful": helpful,
                "unhelpful": unhelpful,
                "satisfaction_pct": satisfaction,
                "no_feedback": no_feedback,
            },
            "zero_source_queries": int(row.zero_source or 0),
            "queries_by_day": queries_by_day,
        }

    async def get_low_quality_queries(
        self, days: int = 30, limit: int = 50
    ) -> list[dict]:
        """Return queries that likely have quality issues."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(QueryLog)
            .where(
                QueryLog.created_at >= since,
                or_(
                    QueryLog.chunks_retrieved == 0,
                    QueryLog.feedback_score == -1,
                    QueryLog.answer_length < 100,
                ),
            )
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
        )
        logs = (await self._session.execute(stmt)).scalars().all()
        return [
            {
                "query_text": log.query_text[:200],
                "answer_preview": "",  # answer text not stored in QueryLog
                "chunk_count": log.chunks_retrieved,
                "feedback": log.feedback_score,
                "latency_ms": log.latency_ms,
                "created_at": log.created_at.isoformat(),
                "user_id": log.user_id,
            }
            for log in logs
        ]

    async def get_per_collection_stats(self, days: int = 30) -> list[dict]:
        """Return per-collection quality breakdown."""
        since = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = (
            select(
                QueryLog.collection_id,
                func.count(QueryLog.id).label("query_count"),
                func.sum(
                    case((QueryLog.chunks_retrieved > 0, 1), else_=0)
                ).label("answered"),
                func.avg(QueryLog.retrieval_score).label("avg_retrieval_score"),
                func.avg(QueryLog.latency_ms).label("avg_latency_ms"),
            )
            .where(QueryLog.created_at >= since, QueryLog.collection_id.isnot(None))
            .group_by(QueryLog.collection_id)
            .order_by(func.count(QueryLog.id).desc())
        )
        rows = (await self._session.execute(stmt)).all()

        # Fetch collection names and document counts
        collection_ids = [r.collection_id for r in rows]
        name_map: dict[str, str] = {}
        doc_count_map: dict[str, int] = {}

        if collection_ids:
            col_result = await self._session.execute(
                select(Collection.id, Collection.name).where(Collection.id.in_(collection_ids))
            )
            for cid, cname in col_result.all():
                name_map[cid] = cname

            doc_result = await self._session.execute(
                select(Document.collection_id, func.count(Document.id).label("cnt"))
                .where(Document.collection_id.in_(collection_ids))
                .group_by(Document.collection_id)
            )
            for cid, cnt in doc_result.all():
                doc_count_map[cid] = cnt

        result = []
        for r in rows:
            total = r.query_count or 0
            answered = int(r.answered or 0)
            answered_rate = round((answered / total) * 100, 1) if total else 0.0
            result.append(
                {
                    "collection_id": r.collection_id,
                    "collection_name": name_map.get(r.collection_id, r.collection_id),
                    "query_count": total,
                    "answered_rate_pct": answered_rate,
                    "avg_retrieval_score": round(float(r.avg_retrieval_score or 0), 4),
                    "avg_latency_ms": round(float(r.avg_latency_ms or 0)),
                    "doc_count": doc_count_map.get(r.collection_id, 0),
                }
            )
        return result
