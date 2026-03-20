"""Embeddable RAG chat widget — token management + public query endpoint."""

import hashlib
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.deps import get_current_user, get_db, get_rag_service, require_permission
from src.core.rbac import UserContext
from src.models.embed import EmbedToken
from src.services.rag_service import RAGService

router = APIRouter(prefix="/embed", tags=["embed"])

_EMBED_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
}


# ── Schemas ───────────────────────────────────────────────────────────────────

class CreateEmbedTokenRequest(BaseModel):
    name: str
    collection_id: str | None = None
    allowed_origins: str = "*"
    expires_at: datetime | None = None


class EmbedTokenOut(BaseModel):
    id: str
    name: str
    token_prefix: str
    collection_id: str | None
    allowed_origins: str
    is_active: bool
    last_used_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EmbedTokenCreated(EmbedTokenOut):
    raw_token: str   # Only returned once at creation time


class EmbedQueryRequest(BaseModel):
    question: str
    session_id: str | None = None


class EmbedQueryResponse(BaseModel):
    answer: str
    sources: list[dict]


# ── Token management (admin/analyst only) ─────────────────────────────────────

@router.post("/tokens", response_model=EmbedTokenCreated)
async def create_embed_token(
    body: CreateEmbedTokenRequest,
    user: UserContext = Depends(require_permission("admin:write")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new embed token. Returns the raw token once — store it securely."""
    raw = "nxw_" + os.urandom(24).hex()
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    token_prefix = raw[:12]

    token = EmbedToken(
        name=body.name,
        token_hash=token_hash,
        token_prefix=token_prefix,
        created_by=user.user_id,
        collection_id=body.collection_id,
        allowed_origins=body.allowed_origins,
        expires_at=body.expires_at,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    out = EmbedTokenCreated(
        id=token.id,
        name=token.name,
        token_prefix=token.token_prefix,
        collection_id=token.collection_id,
        allowed_origins=token.allowed_origins,
        is_active=token.is_active,
        last_used_at=token.last_used_at,
        expires_at=token.expires_at,
        created_at=token.created_at,
        raw_token=raw,
    )
    return out


@router.get("/tokens", response_model=list[EmbedTokenOut])
async def list_embed_tokens(
    user: UserContext = Depends(require_permission("admin:read")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(EmbedToken).order_by(EmbedToken.created_at.desc()))
    return result.scalars().all()


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_embed_token(
    token_id: str,
    user: UserContext = Depends(require_permission("admin:write")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(EmbedToken).where(EmbedToken.id == token_id))
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found.")
    token.is_active = False
    await db.commit()


# ── Public query endpoint (authenticated via embed token) ─────────────────────

async def _resolve_embed_token(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> EmbedToken:
    """Validate Bearer embed token from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing embed token.")

    raw = authorization.removeprefix("Bearer ").strip()
    token_hash = hashlib.sha256(raw.encode()).hexdigest()

    result = await db.execute(
        select(EmbedToken).where(
            EmbedToken.token_hash == token_hash,
            EmbedToken.is_active == True,  # noqa: E712
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or revoked embed token.")

    now = datetime.now(timezone.utc)
    if token.expires_at and token.expires_at < now:
        raise HTTPException(status_code=401, detail="Embed token expired.")

    # CORS origin check
    origin = request.headers.get("origin", "")
    if token.allowed_origins != "*":
        allowed = [o.strip() for o in token.allowed_origins.split(",")]
        if origin not in allowed:
            raise HTTPException(status_code=403, detail="Origin not allowed.")

    # Update last_used_at
    token.last_used_at = now
    await db.commit()

    return token


@router.options("/query")
async def embed_query_preflight():
    """CORS preflight for the public embed query endpoint."""
    return Response(status_code=204, headers=_EMBED_CORS_HEADERS)


@router.post("/query", response_model=EmbedQueryResponse)
async def embed_query(
    body: EmbedQueryRequest,
    token: EmbedToken = Depends(_resolve_embed_token),
    rag_svc: RAGService = Depends(get_rag_service),
):
    """Public RAG query endpoint for embedded widgets.

    Authenticated via `Authorization: Bearer <embed_token>` header.
    No user login required — designed for anonymous public embeds.
    """
    if not body.question.strip():
        raise HTTPException(status_code=422, detail="Question must not be empty.")

    # Build a minimal UserContext for the RAG service
    from src.core.rbac import UserContext as UC
    anon_user = UC(
        user_id="embed-anon",
        username="embed",
        roles=["viewer"],
        team_ids=[],
        company_id=None,
        is_super_admin=False,
    )

    try:
        result = await rag_svc.query(
            query_text=body.question,
            user=anon_user,
            collection_id=token.collection_id,
            top_k=5,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Query failed: {exc}")

    return JSONResponse(
        content={"answer": result["answer"], "sources": result.get("sources", [])},
        headers=_EMBED_CORS_HEADERS,
    )


# ── Widget script endpoint ────────────────────────────────────────────────────

@router.get("/widget.js", include_in_schema=False)
async def serve_widget_js(request: Request):
    """Serve the embeddable Nexus RAG chat widget JavaScript."""
    backend_url = str(request.base_url).rstrip("/")
    js = _build_widget_js(backend_url)
    return Response(content=js, media_type="application/javascript", headers={"Access-Control-Allow-Origin": "*"})


def _build_widget_js(backend_url: str) -> str:
    return f"""
(function () {{
  "use strict";

  var NEXUS_BACKEND = "{backend_url}";

  function getConfig() {{
    var script = document.currentScript || (function() {{
      var scripts = document.getElementsByTagName("script");
      return scripts[scripts.length - 1];
    }})();
    return {{
      token: script.getAttribute("data-token") || "",
      title: script.getAttribute("data-title") || "Ask Nexus",
      position: script.getAttribute("data-position") || "bottom-right",
      primaryColor: script.getAttribute("data-color") || "#6366f1",
      placeholder: script.getAttribute("data-placeholder") || "Ask anything...",
    }};
  }}

  var cfg = getConfig();

  function _nxwInit() {{
  // ── Inject styles ──────────────────────────────────────────────────────────
  var style = document.createElement("style");
  style.textContent = [
    ".nxw-btn{{position:fixed;bottom:24px;right:24px;width:56px;height:56px;border-radius:50%;",
    "background:" + cfg.primaryColor + ";border:none;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25);",
    "display:flex;align-items:center;justify-content:center;z-index:9999;transition:transform .2s;}}",
    ".nxw-btn:hover{{transform:scale(1.08)}}",
    ".nxw-btn svg{{width:26px;height:26px;fill:#fff}}",
    ".nxw-panel{{position:fixed;bottom:92px;right:24px;width:380px;height:520px;",
    "background:#fff;border-radius:16px;box-shadow:0 8px 40px rgba(0,0,0,.18);",
    "display:flex;flex-direction:column;z-index:9999;overflow:hidden;",
    "transform:scale(0);transform-origin:bottom right;transition:transform .22s cubic-bezier(.34,1.56,.64,1);}}",
    ".nxw-panel.open{{transform:scale(1)}}",
    ".nxw-header{{background:" + cfg.primaryColor + ";color:#fff;padding:14px 16px;",
    "font-family:system-ui,sans-serif;font-weight:600;font-size:15px;",
    "display:flex;justify-content:space-between;align-items:center;}}",
    ".nxw-close{{background:none;border:none;color:#fff;cursor:pointer;font-size:20px;line-height:1;padding:0}}",
    ".nxw-messages{{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px;",
    "font-family:system-ui,sans-serif;font-size:14px;}}",
    ".nxw-msg{{padding:10px 12px;border-radius:12px;max-width:88%;line-height:1.5;word-break:break-word;}}",
    ".nxw-msg.user{{align-self:flex-end;background:" + cfg.primaryColor + ";color:#fff;border-bottom-right-radius:4px;}}",
    ".nxw-msg.assistant{{align-self:flex-start;background:#f1f5f9;color:#1e293b;border-bottom-left-radius:4px;}}",
    ".nxw-msg.error{{background:#fee2e2;color:#991b1b;}}",
    ".nxw-sources{{font-size:11px;opacity:.7;margin-top:4px;}}",
    ".nxw-input-row{{display:flex;padding:10px;gap:8px;border-top:1px solid #e2e8f0;}}",
    ".nxw-input{{flex:1;border:1px solid #cbd5e1;border-radius:8px;padding:8px 12px;",
    "font-size:14px;font-family:system-ui,sans-serif;outline:none;}}",
    ".nxw-input:focus{{border-color:" + cfg.primaryColor + "}}",
    ".nxw-send{{background:" + cfg.primaryColor + ";color:#fff;border:none;border-radius:8px;",
    "padding:8px 14px;cursor:pointer;font-size:14px;font-family:system-ui,sans-serif;}}",
    ".nxw-send:disabled{{opacity:.5;cursor:default}}",
    ".nxw-typing{{align-self:flex-start;color:#94a3b8;font-style:italic;font-size:13px;padding:4px 12px;}}",
  ].join("");
  document.head.appendChild(style);

  // ── Build DOM ─────────────────────────────────────────────────────────────
  var btn = document.createElement("button");
  btn.className = "nxw-btn";
  btn.setAttribute("aria-label", "Open chat");
  btn.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>';

  var panel = document.createElement("div");
  panel.className = "nxw-panel";
  panel.innerHTML = [
    '<div class="nxw-header">',
    '  <span>' + cfg.title + '</span>',
    '  <button class="nxw-close" aria-label="Close">&times;</button>',
    '</div>',
    '<div class="nxw-messages" id="nxw-msgs"></div>',
    '<div class="nxw-input-row">',
    '  <input class="nxw-input" id="nxw-input" placeholder="' + cfg.placeholder + '" />',
    '  <button class="nxw-send" id="nxw-send">Send</button>',
    '</div>',
  ].join("");

  document.body.appendChild(btn);
  document.body.appendChild(panel);

  var msgs = panel.querySelector("#nxw-msgs");
  var input = panel.querySelector("#nxw-input");
  var sendBtn = panel.querySelector("#nxw-send");
  var closeBtn = panel.querySelector(".nxw-close");

  // ── Toggle ────────────────────────────────────────────────────────────────
  btn.addEventListener("click", function() {{ panel.classList.toggle("open"); if (panel.classList.contains("open")) input.focus(); }});
  closeBtn.addEventListener("click", function() {{ panel.classList.remove("open"); }});

  // ── Helpers ───────────────────────────────────────────────────────────────
  function addMsg(role, text, sources) {{
    var div = document.createElement("div");
    div.className = "nxw-msg " + role;
    div.textContent = text;
    if (sources && sources.length) {{
      var s = document.createElement("div");
      s.className = "nxw-sources";
      s.textContent = "Sources: " + sources.slice(0, 3).map(function(x) {{ return x.filename || x.document_id; }}).join(", ");
      div.appendChild(s);
    }}
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }}

  function addTyping() {{
    var div = document.createElement("div");
    div.className = "nxw-typing";
    div.textContent = "Thinking…";
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }}

  // ── Send query ────────────────────────────────────────────────────────────
  function send() {{
    var q = input.value.trim();
    if (!q || !cfg.token) return;
    input.value = "";
    sendBtn.disabled = true;

    addMsg("user", q);
    var typing = addTyping();

    fetch(NEXUS_BACKEND + "/api/v1/embed/query", {{
      method: "POST",
      headers: {{
        "Content-Type": "application/json",
        "Authorization": "Bearer " + cfg.token,
      }},
      body: JSON.stringify({{ question: q }}),
    }})
    .then(function(r) {{ return r.json(); }})
    .then(function(data) {{
      msgs.removeChild(typing);
      if (data.detail) {{
        addMsg("error", "Error: " + data.detail);
      }} else {{
        addMsg("assistant", data.answer, data.sources);
      }}
    }})
    .catch(function(err) {{
      msgs.removeChild(typing);
      addMsg("error", "Network error — please try again.");
    }})
    .finally(function() {{
      sendBtn.disabled = false;
      input.focus();
    }});
  }}

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", function(e) {{ if (e.key === "Enter" && !e.shiftKey) {{ e.preventDefault(); send(); }} }});

  // ── Welcome message ───────────────────────────────────────────────────────
  addMsg("assistant", "Hi! I'm Nexus. Ask me anything about your knowledge base.");
  }} // end _nxwInit

  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", _nxwInit);
  }} else {{
    _nxwInit();
  }}
}})();
"""
