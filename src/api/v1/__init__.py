"""API v1 router aggregator."""

from fastapi import APIRouter

from src.api.v1.auth import router as auth_router
from src.api.v1.query import router as query_router
from src.api.v1.documents import router as documents_router
from src.api.v1.collections import router as collections_router
from src.api.v1.teams import router as teams_router
from src.api.v1.compliance import router as compliance_router
from src.api.v1.conversations import router as conversations_router
from src.api.v1.admin import router as admin_router
from src.api.v1.health import router as health_router
from src.api.v1.chat import router as chat_router
from src.api.v1.calendar import router as calendar_router
from src.api.v1.huddle import router as huddle_router
from src.api.v1.notifications import router as notifications_router
from src.api.v1.presence import router as presence_router
from src.api.v1.invites import router as invites_router
from src.api.v1.license import router as license_router
from src.api.v1.companies import router as companies_router
# Phase 2 routers
from src.api.v1.oauth import router as oauth_router
from src.api.v1.saml import router as saml_router
from src.api.v1.api_keys import router as api_keys_router
from src.api.v1.connectors import router as connectors_router
from src.api.v1.eval import router as eval_router
from src.api.v1.webhooks import router as webhooks_router
# Phase 3 routers
from src.api.v1.sql_agent import router as sql_agent_router
from src.api.v1.embed import router as embed_router
from src.api.v1.transcription import router as transcription_router
from src.api.v1.ingestion_ws import router as ingestion_ws_router
from src.api.v1.training import router as training_router

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(auth_router)
v1_router.include_router(presence_router)
v1_router.include_router(query_router)
v1_router.include_router(documents_router)
v1_router.include_router(collections_router)
v1_router.include_router(teams_router)
v1_router.include_router(compliance_router)
v1_router.include_router(conversations_router)
v1_router.include_router(admin_router)
v1_router.include_router(health_router)
v1_router.include_router(chat_router)
v1_router.include_router(calendar_router)
v1_router.include_router(huddle_router)
v1_router.include_router(notifications_router)
v1_router.include_router(invites_router)
# Phase 2
v1_router.include_router(oauth_router)
v1_router.include_router(saml_router)
v1_router.include_router(api_keys_router)
v1_router.include_router(connectors_router)
v1_router.include_router(eval_router)
v1_router.include_router(webhooks_router)
v1_router.include_router(license_router)
v1_router.include_router(companies_router)
# Phase 3
v1_router.include_router(sql_agent_router)
v1_router.include_router(embed_router)
v1_router.include_router(transcription_router)
v1_router.include_router(ingestion_ws_router)
v1_router.include_router(training_router)
