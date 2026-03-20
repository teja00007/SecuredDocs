"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { User } from "@/types";

interface RAGSettings {
  // Retrieval
  hybrid_search_enabled: boolean;
  retrieval_top_k: number;
  // Query rewriting
  query_rewriting_enabled: boolean;
  query_rewrite_mode: string;
  query_rewrite_count: number;
  // Re-ranking
  reranker_type: string;
  reranker_top_n: number;
  cohere_api_key_set: boolean;
  cohere_api_key_hint: string;
  // Contextual retrieval
  contextual_retrieval_enabled: boolean;
  // Chunking
  chunk_size: number;
  chunk_overlap: number;
  hierarchical_parent_size: number;
  hierarchical_child_size: number;
}

function Toggle({
  label, description, value, onChange, badge,
}: {
  label: string; description: string; value: boolean; onChange: (v: boolean) => void; badge?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-gray-800">{label}</p>
          {badge && (
            <span className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700">
              {badge}
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mt-0.5">{description}</p>
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${
          value ? "bg-indigo-600" : "bg-gray-200"
        }`}
      >
        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          value ? "translate-x-6" : "translate-x-1"
        }`} />
      </button>
    </div>
  );
}

function NumInput({
  label, hint, value, onChange, min = 1, max = 9999,
}: {
  label: string; hint?: string; value: number; onChange: (v: number) => void; min?: number; max?: number;
}) {
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium text-gray-700">{label}</label>
      <input
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={e => onChange(Math.max(min, Number(e.target.value)))}
        className="w-28 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
      />
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  );
}

const PIPELINE_STAGES = [
  {
    step: "1",
    label: "Query Rewriting",
    desc: "LLM rewrites/expands the query before search. HyDE generates a hypothetical answer to embed instead of the query.",
    color: "bg-violet-500",
  },
  {
    step: "2",
    label: "Hybrid Search",
    desc: "Vector similarity (dense) + BM25 keyword (sparse), fused with RRF. Retrieves top_k=20 candidates.",
    color: "bg-blue-500",
  },
  {
    step: "3",
    label: "Re-Ranking",
    desc: "Cross-encoder or Cohere Rerank re-scores the top 20 candidates for true relevance. Returns top N.",
    color: "bg-emerald-500",
  },
  {
    step: "4",
    label: "Parent-Child Expansion",
    desc: "Small child chunks matched in search are expanded to their larger parent context before sending to LLM.",
    color: "bg-amber-500",
  },
  {
    step: "5",
    label: "LLM Generation",
    desc: "Final answer generated from re-ranked, context-expanded chunks.",
    color: "bg-rose-500",
  },
];

export default function RAGSettingsPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [cohereKey, setCohereKey] = useState("");

  // State
  const [hybridSearch, setHybridSearch] = useState(false);
  const [topK, setTopK] = useState(20);
  const [queryRewrite, setQueryRewrite] = useState(false);
  const [rewriteMode, setRewriteMode] = useState("simple");
  const [rewriteCount, setRewriteCount] = useState(3);
  const [rerankerType, setRerankerType] = useState("rrf");
  const [rerankerTopN, setRerankerTopN] = useState(5);
  const [cohereKeySet, setCohereKeySet] = useState(false);
  const [cohereKeyHint, setCohereKeyHint] = useState("");
  const [contextualRetrieval, setContextualRetrieval] = useState(false);
  const [chunkSize, setChunkSize] = useState(512);
  const [chunkOverlap, setChunkOverlap] = useState(64);
  const [parentSize, setParentSize] = useState(1500);
  const [childSize, setChildSize] = useState(200);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    api.get<User>("/api/v1/auth/me").then(u => {
      if (!u.roles.includes("admin") && !u.is_super_admin) { router.replace("/"); return; }
      loadSettings();
    }).catch(() => router.replace("/login"));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function loadSettings() {
    try {
      const data = await api.get<RAGSettings>("/api/v1/admin/settings");
      setHybridSearch(data.hybrid_search_enabled ?? false);
      setTopK(data.retrieval_top_k ?? 20);
      setQueryRewrite(data.query_rewriting_enabled ?? false);
      setRewriteMode(data.query_rewrite_mode ?? "simple");
      setRewriteCount(data.query_rewrite_count ?? 3);
      setRerankerType(data.reranker_type ?? "rrf");
      setRerankerTopN(data.reranker_top_n ?? 5);
      setCohereKeySet(data.cohere_api_key_set ?? false);
      setCohereKeyHint(data.cohere_api_key_hint ?? "");
      setContextualRetrieval(data.contextual_retrieval_enabled ?? false);
      setChunkSize(data.chunk_size ?? 512);
      setChunkOverlap(data.chunk_overlap ?? 64);
      setParentSize(data.hierarchical_parent_size ?? 1500);
      setChildSize(data.hierarchical_child_size ?? 200);
    } catch {
      toastError("Failed to load RAG settings");
    } finally {
      setLoading(false);
    }
  }

  async function saveRetrievalSettings(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/api/v1/admin/settings", {
        hybrid_search_enabled: hybridSearch,
        retrieval_top_k: topK,
      });
      success("Retrieval settings saved");
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function saveQueryRewriting(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/api/v1/admin/settings", {
        query_rewriting_enabled: queryRewrite,
        query_rewrite_mode: rewriteMode,
        query_rewrite_count: rewriteCount,
      });
      success("Query rewriting settings saved");
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function saveReranker(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/api/v1/admin/settings", {
        reranker_type: rerankerType,
        reranker_top_n: rerankerTopN,
      });
      if (cohereKey.trim()) {
        await api.patch("/api/v1/admin/env", { cohere_api_key: cohereKey.trim() });
        setCohereKey("");
        setCohereKeySet(true);
      }
      success("Re-ranker settings saved");
      await loadSettings();
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function saveChunking(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/api/v1/admin/settings", {
        contextual_retrieval_enabled: contextualRetrieval,
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        hierarchical_parent_size: parentSize,
        hierarchical_child_size: childSize,
      });
      success("Chunking settings saved — new uploads will use updated strategy");
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden bg-gray-50">
        <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700">← Admin</Link>
            <span className="text-gray-300">/</span>
            <h1 className="font-semibold text-gray-900">RAG Pipeline</h1>
          </div>
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center gap-3">
          <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
          <span className="text-gray-300">/</span>
          <div>
            <h1 className="font-semibold text-gray-900">RAG Pipeline Settings</h1>
            <p className="text-xs text-gray-400 mt-0.5">Configure retrieval strategies, re-ranking, query rewriting, and chunking</p>
          </div>
        </div>
      </div>

      <div className="flex-1 p-6">
        <div className="mx-auto max-w-3xl space-y-6">

          {/* ── Pipeline Flow Diagram ── */}
          <div className="rounded-xl border border-gray-200 bg-white shadow-sm p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-4">Pipeline Flow</h3>
            <div className="flex items-center gap-2 flex-wrap">
              {PIPELINE_STAGES.map((stage, i) => (
                <div key={stage.step} className="flex items-center gap-2">
                  <div className="flex items-center gap-2 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                    <span className={`h-5 w-5 rounded-full ${stage.color} flex items-center justify-center text-white text-xs font-bold shrink-0`}>
                      {stage.step}
                    </span>
                    <div>
                      <p className="text-xs font-medium text-gray-700">{stage.label}</p>
                    </div>
                  </div>
                  {i < PIPELINE_STAGES.length - 1 && (
                    <span className="text-gray-300 font-bold">→</span>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-1 gap-1.5">
              {PIPELINE_STAGES.map(stage => (
                <div key={stage.step} className="flex items-start gap-2 text-xs text-gray-500">
                  <span className={`mt-0.5 h-3.5 w-3.5 rounded-full ${stage.color} shrink-0`} />
                  <span><strong className="text-gray-700">{stage.label}:</strong> {stage.desc}</span>
                </div>
              ))}
            </div>
          </div>

          {/* ── Retrieval Settings ── */}
          <form onSubmit={saveRetrievalSettings} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">Retrieval</h3>
              <p className="mt-0.5 text-xs text-gray-400">How many candidates to retrieve and whether to use keyword + vector search</p>
            </div>
            <div className="px-5 py-5 space-y-5">
              <Toggle
                label="Hybrid Search (Vector + BM25)"
                description="Combines dense vector similarity with BM25 keyword search, fused via Reciprocal Rank Fusion. Best quality — requires BM25 index."
                value={hybridSearch}
                onChange={setHybridSearch}
                badge="Recommended"
              />
              <NumInput
                label="Retrieval top_k (candidates before re-ranking)"
                hint="Retrieve this many candidates, then re-rank down to top_n. Higher = better recall, slower. Recommended: 20."
                value={topK}
                onChange={setTopK}
                min={5}
                max={100}
              />
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving}
                className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </form>

          {/* ── Query Rewriting ── */}
          <form onSubmit={saveQueryRewriting} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">Query Rewriting</h3>
              <p className="mt-0.5 text-xs text-gray-400">Use LLM to improve the query before retrieval. Adds a small LLM cost per query.</p>
            </div>
            <div className="px-5 py-5 space-y-5">
              <Toggle
                label="Enable Query Rewriting"
                description="When enabled, queries are rewritten by LLM before searching documents."
                value={queryRewrite}
                onChange={setQueryRewrite}
              />

              <div className={`space-y-5 transition-opacity ${queryRewrite ? "opacity-100" : "opacity-40 pointer-events-none"}`}>
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Rewrite Mode</label>
                  <div className="grid grid-cols-3 gap-2">
                    {[
                      { value: "simple", label: "Simple", desc: "Rephrase query for clarity" },
                      { value: "multi", label: "Multi-Query", desc: "Generate N query variants, merge results" },
                      { value: "hyde", label: "HyDE", desc: "Generate a hypothetical ideal answer, embed it" },
                    ].map(opt => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setRewriteMode(opt.value)}
                        className={`rounded-lg border px-3 py-3 text-left transition-colors ${
                          rewriteMode === opt.value
                            ? "border-indigo-500 bg-indigo-50"
                            : "border-gray-200 bg-white hover:border-gray-300"
                        }`}
                      >
                        <p className={`text-xs font-semibold ${rewriteMode === opt.value ? "text-indigo-700" : "text-gray-700"}`}>
                          {opt.label}
                        </p>
                        <p className="text-xs text-gray-500 mt-0.5">{opt.desc}</p>
                      </button>
                    ))}
                  </div>
                </div>

                {rewriteMode === "multi" && (
                  <NumInput
                    label="Number of query variants"
                    hint="How many query variants to generate and search with. Recommended: 3."
                    value={rewriteCount}
                    onChange={setRewriteCount}
                    min={2}
                    max={6}
                  />
                )}
              </div>
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving}
                className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </form>

          {/* ── Re-Ranking ── */}
          <form onSubmit={saveReranker} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">Re-Ranking</h3>
              <p className="mt-0.5 text-xs text-gray-400">Re-score retrieved candidates for true relevance. Biggest quality improvement.</p>
            </div>
            <div className="px-5 py-5 space-y-5">
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Re-Ranker Type</label>
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {[
                    { value: "none", label: "None", desc: "No re-ranking" },
                    { value: "rrf", label: "RRF", desc: "Reciprocal Rank Fusion (hybrid search only)" },
                    { value: "cohere", label: "Cohere", desc: "Cohere Rerank API (~$1/1K queries)" },
                    { value: "bge", label: "BGE Local", desc: "Self-hosted cross-encoder" },
                  ].map(opt => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setRerankerType(opt.value)}
                      className={`rounded-lg border px-3 py-3 text-left transition-colors ${
                        rerankerType === opt.value
                          ? "border-indigo-500 bg-indigo-50"
                          : "border-gray-200 bg-white hover:border-gray-300"
                      }`}
                    >
                      <p className={`text-xs font-semibold ${rerankerType === opt.value ? "text-indigo-700" : "text-gray-700"}`}>
                        {opt.label}
                      </p>
                      <p className="text-xs text-gray-500 mt-0.5">{opt.desc}</p>
                    </button>
                  ))}
                </div>
              </div>

              <NumInput
                label="Return top N after re-ranking"
                hint="Final number of chunks sent to LLM for answer generation. Recommended: 5."
                value={rerankerTopN}
                onChange={setRerankerTopN}
                min={1}
                max={20}
              />

              {rerankerType === "cohere" && (
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-gray-700">Cohere API Key</label>
                  <div className="flex items-center gap-3">
                    <div className={`flex items-center gap-1.5 rounded-lg border px-3 py-2 text-xs ${
                      cohereKeySet ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-gray-200 bg-gray-50 text-gray-500"
                    }`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${cohereKeySet ? "bg-emerald-500" : "bg-gray-400"}`} />
                      {cohereKeySet ? `Set (${cohereKeyHint})` : "Not configured"}
                    </div>
                  </div>
                  <div className="mt-2 relative">
                    <input
                      type="password"
                      value={cohereKey}
                      onChange={e => setCohereKey(e.target.value)}
                      placeholder={cohereKeySet ? "Enter new key to replace…" : "Enter Cohere API key…"}
                      className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono text-gray-900 placeholder-gray-400 outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                    />
                  </div>
                  <p className="mt-1 text-xs text-gray-400">Get your key at cohere.com/rerank</p>
                </div>
              )}

              {rerankerType === "bge" && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3">
                  <p className="text-xs font-medium text-amber-700">BGE Local requires a running TEI (Text Embeddings Inference) server</p>
                  <p className="text-xs text-amber-600 mt-0.5">
                    Set <code className="font-mono bg-amber-100 px-1 rounded">RERANKER_URL</code> in your .env to point to your BGE endpoint.
                  </p>
                </div>
              )}
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving}
                className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </form>

          {/* ── Chunking & Ingestion ── */}
          <form onSubmit={saveChunking} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">Chunking & Ingestion</h3>
              <p className="mt-0.5 text-xs text-gray-400">
                Settings apply to new document uploads. Re-ingest existing documents to apply changes.
              </p>
            </div>
            <div className="px-5 py-5 space-y-5">

              <div className="grid grid-cols-2 gap-4">
                <NumInput
                  label="Chunk size (tokens)"
                  hint="Standard chunks for flat strategy. Recommended: 512."
                  value={chunkSize}
                  onChange={setChunkSize}
                  min={64}
                  max={2048}
                />
                <NumInput
                  label="Chunk overlap (tokens)"
                  hint="Overlap between adjacent chunks. Recommended: 64."
                  value={chunkOverlap}
                  onChange={setChunkOverlap}
                  min={0}
                  max={512}
                />
              </div>

              <div className="rounded-lg border border-gray-100 bg-gray-50 p-4 space-y-4">
                <div>
                  <p className="text-xs font-semibold text-gray-700 mb-1">Hierarchical (Parent-Child) Chunking</p>
                  <p className="text-xs text-gray-500">
                    Small child chunks are used for precise search matching. The larger parent chunk is returned to the LLM for rich context.
                    Best for long-form documents.
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <NumInput
                    label="Parent chunk size (tokens)"
                    hint="Context returned to LLM. Recommended: 1500."
                    value={parentSize}
                    onChange={setParentSize}
                    min={256}
                    max={4096}
                  />
                  <NumInput
                    label="Child chunk size (tokens)"
                    hint="Used for embedding & search. Recommended: 200."
                    value={childSize}
                    onChange={setChildSize}
                    min={32}
                    max={512}
                  />
                </div>
              </div>

              <Toggle
                label="Contextual Retrieval"
                description="Before embedding each chunk, LLM prepends document-level context to improve chunk relevance. Anthropic reports 49% reduction in retrieval failures. Adds one LLM call per chunk at ingestion time."
                value={contextualRetrieval}
                onChange={setContextualRetrieval}
                badge="High impact"
              />

              {contextualRetrieval && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3">
                  <p className="text-xs font-medium text-amber-700">
                    Contextual Retrieval increases ingestion time and LLM cost proportional to document size. Recommended for high-value document corpora.
                  </p>
                </div>
              )}
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving}
                className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save Chunking Settings"}
              </button>
            </div>
          </form>

          {/* ── Technique Reference ── */}
          <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">Strategy Reference</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50">
                    <th className="px-5 py-3 text-left font-semibold text-gray-600">Technique</th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Quality Gain</th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Effort</th>
                    <th className="px-4 py-3 text-left font-semibold text-gray-600">Cost</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {[
                    { name: "Re-ranking (Cohere)", quality: "⭐⭐⭐⭐⭐", effort: "Low", cost: "~$1/1K queries" },
                    { name: "Metadata filtering", quality: "⭐⭐⭐⭐", effort: "Low", cost: "Free" },
                    { name: "Hybrid Search (RRF)", quality: "⭐⭐⭐⭐", effort: "Low", cost: "Free" },
                    { name: "Parent-Child chunking", quality: "⭐⭐⭐⭐", effort: "Medium", cost: "Free" },
                    { name: "Contextual Retrieval", quality: "⭐⭐⭐⭐", effort: "Medium", cost: "Small (ingestion only)" },
                    { name: "Multi-Query rewriting", quality: "⭐⭐⭐", effort: "Medium", cost: "Small per query" },
                    { name: "HyDE", quality: "⭐⭐⭐", effort: "Medium", cost: "Small per query" },
                  ].map(row => (
                    <tr key={row.name} className="hover:bg-gray-50 transition-colors">
                      <td className="px-5 py-3 font-medium text-gray-700">{row.name}</td>
                      <td className="px-4 py-3 text-gray-600">{row.quality}</td>
                      <td className="px-4 py-3 text-gray-600">{row.effort}</td>
                      <td className="px-4 py-3 text-gray-600">{row.cost}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
