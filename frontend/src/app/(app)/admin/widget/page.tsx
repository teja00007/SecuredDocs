"use client";

import { useEffect, useState, FormEvent } from "react";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";

interface EmbedToken {
  id: string;
  name: string;
  token_prefix: string;
  collection_id: string | null;
  allowed_origins: string;
  is_active: boolean;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

interface Collection {
  id: string;
  name: string;
}

function relDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function WidgetAdminPage() {
  const { success, error: toastError } = useToast();
  const [tokens, setTokens] = useState<EmbedToken[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newToken, setNewToken] = useState<string | null>(null);

  // Create form state
  const [name, setName] = useState("");
  const [collectionId, setCollectionId] = useState("");
  const [allowedOrigins, setAllowedOrigins] = useState("*");

  useEffect(() => {
    Promise.all([
      api.get<EmbedToken[]>("/api/v1/embed/tokens"),
      api.get<{ items: Collection[] }>("/api/v1/collections"),
    ])
      .then(([tokRes, colRes]) => {
        setTokens(tokRes);
        setCollections((colRes as unknown as { items: Collection[] }).items ?? (colRes as unknown as Collection[]));
      })
      .catch(() => toastError("Failed to load data."))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    try {
      const data = await api.post<EmbedToken & { raw_token: string }>("/api/v1/embed/tokens", {
        name: name.trim(),
        collection_id: collectionId || null,
        allowed_origins: allowedOrigins.trim() || "*",
      });
      setNewToken(data.raw_token);
      setTokens((prev) => [data, ...prev]);
      setName(""); setCollectionId(""); setAllowedOrigins("*");
      setShowCreate(false);
      success("Token created — copy it now, it won't be shown again.");
    } catch {
      toastError("Failed to create token.");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(id: string) {
    if (!confirm("Revoke this token? All embeds using it will stop working.")) return;
    try {
      await api.delete(`/api/v1/embed/tokens/${id}`);
      setTokens((prev) => prev.map((t) => (t.id === id ? { ...t, is_active: false } : t)));
      success("Token revoked.");
    } catch {
      toastError("Failed to revoke token.");
    }
  }

  const BACKEND_URL = typeof window !== "undefined" ? window.location.origin.replace(":3000", ":8000") : "";

  function snippet(token: EmbedToken) {
    return `<script
  src="${BACKEND_URL}/api/v1/embed/widget.js"
  data-token="${token.token_prefix}…"
  data-title="Ask Nexus"
  data-color="#6366f1"
></script>`;
  }

  if (loading) {
    return (
      <div className="flex-1 bg-slate-950 flex items-center justify-center">
        <div className="text-slate-400 text-sm">Loading…</div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 text-slate-100 p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">Embeddable Widget</h1>
            <p className="text-slate-400 mt-1 text-sm">
              Embed a Nexus RAG chat widget on any website with a single &lt;script&gt; tag.
            </p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-sm font-medium transition-colors"
          >
            + New Token
          </button>
        </div>

        {/* New raw token display */}
        {newToken && (
          <div className="mb-6 bg-emerald-950 border border-emerald-700 rounded-xl p-4">
            <p className="text-sm font-semibold text-emerald-400 mb-2">
              Token created — copy it now. It will not be shown again.
            </p>
            <div className="flex items-center gap-3">
              <code className="flex-1 bg-slate-900 px-3 py-2 rounded-lg text-xs font-mono text-emerald-300 break-all">
                {newToken}
              </code>
              <button
                onClick={() => { navigator.clipboard.writeText(newToken); success("Copied!"); }}
                className="shrink-0 px-3 py-2 bg-emerald-800 hover:bg-emerald-700 text-emerald-200 rounded-lg text-xs transition-colors"
              >
                Copy
              </button>
            </div>
            <button
              onClick={() => setNewToken(null)}
              className="mt-3 text-xs text-emerald-600 hover:text-emerald-400"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Create form modal */}
        {showCreate && (
          <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="bg-slate-900 border border-slate-700 rounded-2xl p-6 w-full max-w-md mx-4 shadow-2xl">
              <h2 className="text-lg font-bold text-white mb-4">Create Embed Token</h2>
              <form onSubmit={handleCreate} className="space-y-4">
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">Token Name</label>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="e.g. Marketing Website"
                    required
                    className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white
                               placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">
                    Collection (optional — leave blank for all)
                  </label>
                  <select
                    value={collectionId}
                    onChange={(e) => setCollectionId(e.target.value)}
                    className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white
                               focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="">All collections</option>
                    {collections.map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-slate-400 mb-1">
                    Allowed Origins (comma-separated, or * for any)
                  </label>
                  <input
                    value={allowedOrigins}
                    onChange={(e) => setAllowedOrigins(e.target.value)}
                    placeholder="https://example.com,https://app.example.com"
                    className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white
                               placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div className="flex gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => setShowCreate(false)}
                    className="flex-1 py-2 rounded-xl border border-slate-600 text-slate-300 text-sm hover:bg-slate-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={creating}
                    className="flex-1 py-2 rounded-xl bg-indigo-600 text-white text-sm font-medium
                               hover:bg-indigo-500 disabled:opacity-40 transition-colors"
                  >
                    {creating ? "Creating…" : "Create Token"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* How to embed */}
        <div className="mb-6 bg-slate-900 border border-slate-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-white mb-2">How to embed</h2>
          <p className="text-xs text-slate-400 mb-3">
            Add this snippet before the closing &lt;/body&gt; tag on your page. Replace the token with a real token from the list below.
          </p>
          <pre className="bg-slate-950 rounded-lg px-4 py-3 text-xs font-mono text-indigo-300 overflow-x-auto whitespace-pre">{`<script
  src="${BACKEND_URL}/api/v1/embed/widget.js"
  data-token="YOUR_EMBED_TOKEN"
  data-title="Ask Nexus"
  data-color="#6366f1"
  data-placeholder="Ask anything…"
></script>`}</pre>
          <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500">
            <div><code className="text-slate-400">data-token</code> — required: your embed token</div>
            <div><code className="text-slate-400">data-title</code> — widget header text</div>
            <div><code className="text-slate-400">data-color</code> — primary color (hex)</div>
            <div><code className="text-slate-400">data-placeholder</code> — input placeholder</div>
          </div>
        </div>

        {/* Token list */}
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-slate-300">Embed Tokens</h2>
          {tokens.length === 0 && (
            <div className="text-center py-12 text-slate-500 text-sm">
              No tokens yet. Create one to get started.
            </div>
          )}
          {tokens.map((token) => (
            <div
              key={token.id}
              className={`bg-slate-900 border rounded-xl p-4 flex items-start gap-4 ${
                token.is_active ? "border-slate-700" : "border-slate-800 opacity-50"
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-white text-sm">{token.name}</span>
                  {!token.is_active && (
                    <span className="text-xs bg-red-900/60 text-red-300 px-2 py-0.5 rounded-full">Revoked</span>
                  )}
                </div>
                <div className="text-xs text-slate-400 space-y-0.5">
                  <div>
                    Token: <code className="font-mono text-slate-300">{token.token_prefix}…</code>
                  </div>
                  {token.collection_id && <div>Collection: <code className="text-slate-300">{token.collection_id}</code></div>}
                  <div>Origins: <code className="text-slate-300">{token.allowed_origins}</code></div>
                  <div>Created: {relDate(token.created_at)}</div>
                  {token.last_used_at && <div>Last used: {relDate(token.last_used_at)}</div>}
                </div>
              </div>
              <div className="flex flex-col gap-2 shrink-0">
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(snippet(token));
                    success("Snippet copied to clipboard.");
                  }}
                  className="text-xs px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg transition-colors"
                >
                  Copy Snippet
                </button>
                {token.is_active && (
                  <button
                    onClick={() => handleRevoke(token.id)}
                    className="text-xs px-3 py-1.5 bg-red-950 hover:bg-red-900 text-red-400 rounded-lg transition-colors"
                  >
                    Revoke
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
