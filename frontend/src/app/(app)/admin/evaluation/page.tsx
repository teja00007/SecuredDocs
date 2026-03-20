"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Collection } from "@/types";

// ── Types ─────────────────────────────────────────────────────────────────────

interface EvalOverview {
  total_queries: number;
  answered_rate: number;
  avg_retrieval_score: number;
  avg_latency_ms: number;
  helpful: number;
  unhelpful: number;
  satisfaction_pct: number | null;
  period_days: number;
}

interface DailyCount {
  date: string;
  count: number;
}

interface LowQualityQuery {
  id: string;
  query: string;
  chunks_found: number;
  feedback: number | null;
  created_at: string;
}

interface CollectionStat {
  collection_id: string;
  collection_name: string;
  query_count: number;
  answered_rate: number;
  avg_score: number;
  doc_count: number;
}

interface TestQueryResult {
  answer: string;
  chunks: Array<{ text: string; score: number; filename: string; chunk_index: number }>;
  retrieval_ms: number;
  generation_ms: number;
  quality: "good" | "fair" | "poor";
  suggestions: string[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const QUALITY_BADGE: Record<"good" | "fair" | "poor", string> = {
  good: "bg-emerald-100 text-emerald-700 border border-emerald-200",
  fair: "bg-yellow-100 text-yellow-700 border border-yellow-200",
  poor: "bg-red-100 text-red-700 border border-red-200",
};

function scoreCls(score: number, hi: number, mid: number): string {
  if (score >= hi) return "text-emerald-600";
  if (score >= mid) return "text-yellow-600";
  return "text-red-500";
}

// ── Bar chart (div-based, no charting deps) ───────────────────────────────────

function BarChart({ data }: { data: DailyCount[] }) {
  const max = Math.max(...data.map(d => d.count), 1);
  return (
    <div className="flex h-36 items-end gap-px overflow-x-auto">
      {data.map(d => {
        const heightPct = max > 0 ? Math.max((d.count / max) * 100, d.count > 0 ? 3 : 0) : 0;
        const label = new Date(d.date).toLocaleDateString("en-US", { month: "short", day: "numeric" });
        return (
          <div
            key={d.date}
            className="group relative flex flex-1 min-w-[18px] flex-col items-center"
          >
            <div
              className="w-full rounded-t bg-gray-800 group-hover:bg-black transition-colors cursor-default"
              style={{ height: `${heightPct}%` }}
            />
            {/* Tooltip */}
            <div className="pointer-events-none absolute bottom-full mb-1 hidden group-hover:block z-10">
              <span className="rounded bg-gray-900 px-2 py-1 text-[10px] text-white whitespace-nowrap shadow-lg">
                {label}: {d.count}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Overview card ─────────────────────────────────────────────────────────────

function MetricCard({ label, value, sub, cls }: {
  label: string; value: string | number; sub?: string; cls?: string;
}) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-[11px] font-medium uppercase tracking-wide text-gray-400">{label}</p>
      <p className={`mt-2 text-3xl font-bold ${cls ?? "text-gray-900"}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-gray-400">{sub}</p>}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function EvaluationPage() {
  const router = useRouter();

  const [period, setPeriod] = useState(30);
  const [overview, setOverview] = useState<EvalOverview | null>(null);
  const [dailyCounts, setDailyCounts] = useState<DailyCount[]>([]);
  const [lowQuality, setLowQuality] = useState<LowQualityQuery[]>([]);
  const [collectionStats, setCollectionStats] = useState<CollectionStat[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);

  // Test query panel
  const [testQuery, setTestQuery] = useState("");
  const [testCollection, setTestCollection] = useState("");
  const [testRunning, setTestRunning] = useState(false);
  const [testResult, setTestResult] = useState<TestQueryResult | null>(null);
  const [testError, setTestError] = useState("");

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    loadAll(period);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function loadAll(days: number) {
    setLoading(true);
    try {
      const qs = `?days=${days}`;
      const [ov, daily, lq, cs, cols] = await Promise.all([
        api.get<EvalOverview>(`/api/v1/eval/overview${qs}`).catch(() => null),
        api.get<DailyCount[]>(`/api/v1/eval/daily-counts${qs}`).catch(() => [] as DailyCount[]),
        api.get<LowQualityQuery[]>("/api/v1/eval/low-quality").catch(() => [] as LowQualityQuery[]),
        api.get<CollectionStat[]>("/api/v1/eval/collections").catch(() => [] as CollectionStat[]),
        api.get<Collection[]>("/api/v1/collections").catch(() => [] as Collection[]),
      ]);
      setOverview(ov);
      setDailyCounts(daily);
      setLowQuality(lq);
      setCollectionStats(cs);
      setCollections(cols);
    } finally {
      setLoading(false);
    }
  }

  function changePeriod(days: number) {
    setPeriod(days);
    loadAll(days);
  }

  async function runTest(e: FormEvent) {
    e.preventDefault();
    if (!testQuery.trim()) return;
    setTestRunning(true);
    setTestError("");
    setTestResult(null);
    try {
      const result = await api.post<TestQueryResult>("/api/v1/eval/test-query", {
        query: testQuery.trim(),
        collection_id: testCollection || null,
      });
      setTestResult(result);
    } catch (err: unknown) {
      setTestError(err instanceof Error ? err.message : "Test query failed");
    } finally {
      setTestRunning(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
            <span className="text-gray-300">/</span>
            <div>
              <h1 className="font-semibold text-gray-900">RAG Evaluation</h1>
              <p className="text-xs text-gray-400 mt-0.5">Monitor retrieval quality, answer rates, and user satisfaction</p>
            </div>
          </div>
          <button
            onClick={() => loadAll(period)}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40 transition-colors"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
              className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`}>
              <path d="M23 4v6h-6M1 20v-6h6" /><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      <div className="mx-auto w-full max-w-6xl space-y-6 p-6">

        {/* ── Period selector ── */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">Period:</span>
          {[7, 14, 30, 90].map(d => (
            <button
              key={d}
              onClick={() => changePeriod(d)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                period === d
                  ? "bg-black text-white"
                  : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}
            >
              {d} days
            </button>
          ))}
          {loading && (
            <div className="ml-2 h-4 w-4 animate-spin rounded-full border-2 border-gray-900 border-t-transparent" />
          )}
        </div>

        {/* ── Overview cards ── */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <MetricCard
            label="Total Queries"
            value={overview?.total_queries ?? "—"}
            sub={`last ${period} days`}
          />
          <MetricCard
            label="Answered Rate"
            value={overview ? `${overview.answered_rate.toFixed(1)}%` : "—"}
            sub="of queries answered"
            cls={overview ? scoreCls(overview.answered_rate, 85, 70) : "text-gray-900"}
          />
          <MetricCard
            label="Avg Retrieval Score"
            value={overview ? overview.avg_retrieval_score.toFixed(2) : "—"}
            sub="semantic similarity"
            cls={overview ? scoreCls(overview.avg_retrieval_score, 0.7, 0.5) : "text-gray-900"}
          />
          <MetricCard
            label="Avg Latency"
            value={overview ? `${overview.avg_latency_ms} ms` : "—"}
            sub="end-to-end"
          />
        </div>

        {/* ── Satisfaction row ── */}
        <div className="grid grid-cols-3 gap-4">
          <MetricCard
            label="Helpful"
            value={overview?.helpful ?? "—"}
            sub="thumbs-up responses"
            cls="text-emerald-600"
          />
          <MetricCard
            label="Unhelpful"
            value={overview?.unhelpful ?? "—"}
            sub="thumbs-down responses"
            cls="text-red-500"
          />
          <MetricCard
            label="Satisfaction"
            value={
              overview?.satisfaction_pct != null
                ? `${overview.satisfaction_pct.toFixed(1)}%`
                : "—"
            }
            sub={
              overview
                ? `${(overview.helpful ?? 0) + (overview.unhelpful ?? 0)} total ratings`
                : undefined
            }
            cls={
              overview?.satisfaction_pct != null
                ? scoreCls(overview.satisfaction_pct, 80, 60)
                : "text-gray-900"
            }
          />
        </div>

        {/* ── Queries per day bar chart ── */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold text-gray-700">Queries Per Day</h3>
          {dailyCounts.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-400">No data for this period.</p>
          ) : (
            <>
              <BarChart data={dailyCounts} />
              <div className="mt-2 flex justify-between text-[10px] text-gray-400">
                <span>{new Date(dailyCounts[0].date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
                <span>{new Date(dailyCounts[Math.floor(dailyCounts.length / 2)].date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
                <span>{new Date(dailyCounts[dailyCounts.length - 1].date).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
              </div>
            </>
          )}
        </div>

        {/* ── Low-quality queries table ── */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
            <h3 className="text-sm font-semibold text-gray-700">Low-Quality Queries</h3>
            <span className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600">
              {lowQuality.length} flagged
            </span>
          </div>
          {lowQuality.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-400">No quality issues detected.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-4 py-3 text-left">Query</th>
                    <th className="px-4 py-3 text-left">Chunks</th>
                    <th className="px-4 py-3 text-left">Feedback</th>
                    <th className="px-4 py-3 text-left">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {lowQuality.map(q => (
                    <tr key={q.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-gray-800 max-w-[320px]">
                        <p className="truncate">{q.query}</p>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          q.chunks_found === 0
                            ? "bg-red-100 text-red-600"
                            : "bg-gray-100 text-gray-600"
                        }`}>
                          {q.chunks_found}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-lg">
                        {q.feedback === 1 ? "👍"
                          : q.feedback === -1 ? "👎"
                          : <span className="text-gray-400 text-sm">—</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400">
                        {new Date(q.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Per-collection stats table ── */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="border-b border-gray-100 px-5 py-4">
            <h3 className="text-sm font-semibold text-gray-700">Per-Collection Stats</h3>
          </div>
          {collectionStats.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-400">No collection data available.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-4 py-3 text-left">Collection</th>
                    <th className="px-4 py-3 text-right">Queries</th>
                    <th className="px-4 py-3 text-right">Answered Rate</th>
                    <th className="px-4 py-3 text-right">Avg Score</th>
                    <th className="px-4 py-3 text-right">Docs</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {collectionStats.map(row => (
                    <tr key={row.collection_id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 font-medium text-gray-800">{row.collection_name}</td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-500">{row.query_count}</td>
                      <td className="px-4 py-3 text-right">
                        <span className={`text-sm font-semibold tabular-nums ${scoreCls(row.answered_rate, 85, 70)}`}>
                          {row.answered_rate.toFixed(1)}%
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={`text-sm font-semibold tabular-nums ${scoreCls(row.avg_score, 0.7, 0.5)}`}>
                          {row.avg_score.toFixed(2)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-gray-500">{row.doc_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Test Query panel ── */}
        <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold text-gray-700">Test Query</h3>
          <form onSubmit={runTest} className="space-y-3">
            <div className="flex flex-col gap-3 sm:flex-row">
              <input
                type="text"
                value={testQuery}
                onChange={e => setTestQuery(e.target.value)}
                placeholder="Enter a test query…"
                className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
              />
              <select
                value={testCollection}
                onChange={e => setTestCollection(e.target.value)}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-gray-400"
              >
                <option value="">All collections</option>
                {collections.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <button
                type="submit"
                disabled={testRunning || !testQuery.trim()}
                className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40 transition-colors whitespace-nowrap"
              >
                {testRunning ? "Running…" : "Run Test"}
              </button>
            </div>
          </form>

          {testError && (
            <p className="mt-3 text-xs text-red-500 flex items-center gap-1">
              <span>⚠</span> {testError}
            </p>
          )}

          {testResult && (
            <div className="mt-5 space-y-5">
              {/* Answer + diagnosis badge */}
              <div>
                <div className="mb-2 flex items-center gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Answer</p>
                  <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${QUALITY_BADGE[testResult.quality]}`}>
                    {testResult.quality}
                  </span>
                </div>
                <p className="rounded-lg bg-gray-50 p-4 text-sm text-gray-800 leading-relaxed whitespace-pre-wrap border border-gray-100">
                  {testResult.answer}
                </p>
              </div>

              {/* Retrieved chunks */}
              {testResult.chunks.length > 0 && (
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                    Retrieved Chunks ({testResult.chunks.length})
                  </p>
                  <div className="space-y-2">
                    {testResult.chunks.map((chunk, i) => (
                      <div key={i} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
                        <div className="mb-1.5 flex items-center justify-between">
                          <span className="text-xs text-gray-500 truncate max-w-[200px]">{chunk.filename}</span>
                          <span className={`ml-2 shrink-0 text-xs font-semibold tabular-nums ${scoreCls(chunk.score, 0.7, 0.5)}`}>
                            {chunk.score.toFixed(3)}
                          </span>
                        </div>
                        <p className="text-xs text-gray-500 line-clamp-3 leading-relaxed">
                          {chunk.text}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Follow-up suggestions */}
              {testResult.suggestions && testResult.suggestions.length > 0 && (
                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">
                    Follow-up Suggestions
                  </p>
                  <ul className="space-y-1">
                    {testResult.suggestions.map((s, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                        <span className="mt-0.5 shrink-0 text-gray-400">›</span>
                        <span>{s}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Latency */}
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 text-center">
                  <p className="text-xs text-blue-600 font-medium">Retrieval</p>
                  <p className="text-xl font-bold text-gray-900 tabular-nums mt-1">{testResult.retrieval_ms} ms</p>
                </div>
                <div className="rounded-lg bg-gray-50 border border-gray-100 px-4 py-3 text-center">
                  <p className="text-xs text-purple-600 font-medium">Generation</p>
                  <p className="text-xl font-bold text-gray-900 tabular-nums mt-1">{testResult.generation_ms} ms</p>
                </div>
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
