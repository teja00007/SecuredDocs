"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import type { User } from "@/types";

// ── Types ──────────────────────────────────────────────────────────────────────
interface QueryStats {
  total_queries: number;
  avg_latency_ms: number;
  avg_chunks_retrieved: number;
  active_users: number;
  days: number;
}
interface DayCount    { day: string; count: number }
interface TopUser     { user_id: string; username: string; query_count: number; avg_latency_ms: number }
interface RecentQuery { id: string; username: string; query_text: string; chunks_retrieved: number; latency_ms: number; created_at: string }
interface ZeroQuery   { query_text: string; username: string; created_at: string }
interface Analytics {
  stats: QueryStats;
  stats_prev: QueryStats;
  queries_per_day: DayCount[];
  top_users: TopUser[];
  recent_queries: RecentQuery[];
  zero_chunk_queries: ZeroQuery[];
  unanswered: { total: number; unanswered: number; rate_pct: number };
  feedback: { helpful: number; unhelpful: number; satisfaction_pct: number | null };
  latency_percentiles: { p50_ms: number; p95_ms: number; p99_ms: number };
  document_stats: { total: number; ready: number; failed: number; processing: number; compliance_blocked: number };
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function calcTrend(curr: number, prev: number): { pct: number; up: boolean } | null {
  if (!prev) return null;
  const pct = Math.round(((curr - prev) / prev) * 100);
  return { pct: Math.abs(pct), up: curr > prev };
}

function TrendBadge({ curr, prev, goodWhenUp = true }: { curr: number; prev: number; goodWhenUp?: boolean }) {
  const t = calcTrend(curr, prev);
  if (!t) return null;
  const isGood = goodWhenUp ? t.up : !t.up;
  return (
    <span className={`text-[11px] font-medium ${isGood ? "text-emerald-600" : "text-red-500"}`}>
      {t.up ? "↑" : "↓"} {t.pct}%
    </span>
  );
}

function BarChart({ data }: { data: DayCount[] }) {
  const max = Math.max(...data.map(d => d.count), 1);
  return (
    <div className="flex h-32 items-end gap-px">
      {data.map(d => (
        <div key={d.day} className="group relative flex flex-1 flex-col items-center">
          <div className="w-full rounded-sm bg-gray-800 transition-colors group-hover:bg-black"
            style={{ height: `${(d.count / max) * 100}%`, minHeight: d.count > 0 ? 3 : 0 }} />
          <div className="pointer-events-none absolute bottom-full mb-1 hidden rounded bg-gray-900 px-2 py-1 text-[10px] text-white group-hover:block whitespace-nowrap z-10">
            {d.day.slice(5)}: {d.count}
          </div>
        </div>
      ))}
    </div>
  );
}

function StatCard({ label, value, sub, highlight, trend }: {
  label: string; value: string | number; sub?: string;
  highlight?: "good" | "warn" | "bad";
  trend?: React.ReactNode;
}) {
  const accent =
    highlight === "good" ? "border-l-4 border-l-black" :
    highlight === "warn" ? "border-l-4 border-l-gray-400" :
    highlight === "bad"  ? "border-l-4 border-l-gray-600" : "";
  return (
    <div className={`rounded-xl border border-gray-200 bg-white p-4 shadow-sm ${accent}`}>
      <p className="text-[11px] text-gray-400 font-medium uppercase tracking-wide">{label}</p>
      <div className="mt-1 flex items-end gap-2">
        <p className="text-2xl font-bold text-gray-900 leading-none">{value}</p>
        {trend}
      </div>
      {sub && <p className="mt-1 text-[11px] text-gray-400">{sub}</p>}
    </div>
  );
}

function FeedbackBar({ helpful, unhelpful }: { helpful: number; unhelpful: number }) {
  const total = helpful + unhelpful;
  if (!total) return <p className="py-6 text-center text-sm text-gray-400">No feedback yet.</p>;
  const pct = Math.round((helpful / total) * 100);
  return (
    <div className="space-y-3">
      <div className="flex justify-between text-sm">
        <span className="text-gray-600">👍 Helpful</span>
        <span className="font-semibold text-gray-900">{helpful} <span className="text-gray-400 font-normal">({pct}%)</span></span>
      </div>
      <div className="h-2 w-full rounded-full bg-gray-100 overflow-hidden">
        <div className="h-full rounded-full bg-gray-900 transition-all" style={{ width: `${pct}%` }} />
      </div>
      <div className="flex justify-between text-sm">
        <span className="text-gray-600">👎 Not helpful</span>
        <span className="font-semibold text-gray-900">{unhelpful} <span className="text-gray-400 font-normal">({100-pct}%)</span></span>
      </div>
    </div>
  );
}

function exportCSV(queries: RecentQuery[], days: number) {
  const header = ["Query", "User", "Chunks", "Latency (ms)", "Time"];
  const rows = queries.map(q => [
    `"${q.query_text.replace(/"/g, '""')}"`, q.username, q.chunks_retrieved, q.latency_ms,
    new Date(q.created_at).toLocaleString(),
  ]);
  const csv = [header, ...rows].map(r => r.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `nexus-queries-last-${days}d-${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Page ───────────────────────────────────────────────────────────────────────
export default function AnalyticsPage() {
  const router = useRouter();
  const [data, setData] = useState<Analytics | null>(null);
  const [days, setDays] = useState(14);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadAnalytics = useCallback(async (d: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.get<Analytics>(`/api/v1/admin/analytics?days=${d}`);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load analytics");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    api.get<User>("/api/v1/auth/me").then(u => {
      if (!u.roles.includes("admin")) { router.replace("/"); return; }
      loadAnalytics(14);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  const p = data?.stats_prev;
  const s = data?.stats;

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
            <span className="text-gray-300">/</span>
            <h1 className="font-semibold text-gray-900">Analytics</h1>
          </div>
          <button
            onClick={() => loadAnalytics(days)}
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
        {/* Period selector */}
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">Last</span>
          {[7, 14, 30, 90].map(d => (
            <button key={d} onClick={() => { setDays(d); loadAnalytics(d); }}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                days === d ? "bg-black text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"
              }`}>
              {d} days
            </button>
          ))}
          {p && s && <span className="ml-2 text-[11px] text-gray-400">vs previous {days} days</span>}
        </div>

        {error ? (
          <div className="rounded-xl border border-gray-200 bg-white p-10 text-center shadow-sm">
            <p className="text-sm text-red-500 mb-3">{error}</p>
            <button onClick={() => loadAnalytics(days)}
              className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white hover:bg-gray-800">Retry</button>
          </div>
        ) : loading && !data ? (
          <div className="flex justify-center py-24">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-900 border-t-transparent" />
          </div>
        ) : data ? (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard label="Total Queries" value={data.stats.total_queries} sub={`last ${days} days`}
                trend={p && <TrendBadge curr={s!.total_queries} prev={p.total_queries} goodWhenUp />} />
              <StatCard label="Active Users" value={data.stats.active_users} sub="unique"
                trend={p && <TrendBadge curr={s!.active_users} prev={p.active_users} goodWhenUp />} />
              <StatCard label="Avg Latency" value={`${data.stats.avg_latency_ms} ms`}
                trend={p && <TrendBadge curr={s!.avg_latency_ms} prev={p.avg_latency_ms} goodWhenUp={false} />} />
              <StatCard label="Avg Chunks / Query" value={data.stats.avg_chunks_retrieved}
                trend={p && <TrendBadge curr={s!.avg_chunks_retrieved} prev={p.avg_chunks_retrieved} goodWhenUp />} />
            </div>

            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard label="Unanswered Rate" value={`${data.unanswered.rate_pct}%`}
                sub={`${data.unanswered.unanswered} of ${data.unanswered.total}`}
                highlight={data.unanswered.rate_pct > 30 ? "bad" : data.unanswered.rate_pct > 10 ? "warn" : "good"} />
              <StatCard label="User Satisfaction"
                value={data.feedback.satisfaction_pct != null ? `${data.feedback.satisfaction_pct}%` : "—"}
                sub={data.feedback.helpful + data.feedback.unhelpful > 0
                  ? `${data.feedback.helpful + data.feedback.unhelpful} ratings` : "no ratings yet"}
                highlight={data.feedback.satisfaction_pct == null ? undefined :
                  data.feedback.satisfaction_pct >= 70 ? "good" :
                  data.feedback.satisfaction_pct >= 50 ? "warn" : "bad"} />
              <StatCard label="P50 Latency" value={`${data.latency_percentiles.p50_ms} ms`} sub="median" />
              <StatCard label="P95 / P99" value={`${data.latency_percentiles.p95_ms} ms`}
                sub={`P99: ${data.latency_percentiles.p99_ms} ms`} />
            </div>

            <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <h2 className="mb-4 text-sm font-semibold text-gray-700">Queries per day</h2>
              {data.queries_per_day.every(d => d.count === 0) ? (
                <p className="py-10 text-center text-sm text-gray-400">No queries in this period.</p>
              ) : (
                <>
                  <BarChart data={data.queries_per_day} />
                  <div className="mt-2 flex justify-between text-[11px] text-gray-400">
                    <span>{data.queries_per_day[0]?.day.slice(5)}</span>
                    <span>{data.queries_per_day[Math.floor(data.queries_per_day.length / 2)]?.day.slice(5)}</span>
                    <span>{data.queries_per_day[data.queries_per_day.length - 1]?.day.slice(5)}</span>
                  </div>
                </>
              )}
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
                <div className="border-b border-gray-100 px-5 py-3">
                  <h2 className="text-sm font-semibold text-gray-700">Top Users</h2>
                </div>
                {data.top_users.length === 0 ? (
                  <p className="p-5 text-sm text-gray-400">No data yet.</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 text-xs text-gray-500">
                      <tr>
                        <th className="px-4 py-2.5 text-left font-medium">User</th>
                        <th className="px-4 py-2.5 text-right font-medium">Queries</th>
                        <th className="px-4 py-2.5 text-right font-medium">Avg ms</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {data.top_users.map(u => (
                        <tr key={u.user_id} className="hover:bg-gray-50">
                          <td className="px-4 py-2.5 flex items-center gap-2">
                            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-900 text-[9px] font-bold text-white uppercase">
                              {u.username[0]}
                            </span>
                            <span className="font-medium text-gray-800">{u.username}</span>
                          </td>
                          <td className="px-4 py-2.5 text-right text-gray-700">{u.query_count}</td>
                          <td className="px-4 py-2.5 text-right text-gray-400">{u.avg_latency_ms}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
                <div className="border-b border-gray-100 px-5 py-3">
                  <h2 className="text-sm font-semibold text-gray-700">User Feedback</h2>
                </div>
                <div className="p-5">
                  <FeedbackBar helpful={data.feedback.helpful} unhelpful={data.feedback.unhelpful} />
                </div>
              </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-2">
              <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
                <div className="border-b border-gray-100 px-5 py-3">
                  <h2 className="text-sm font-semibold text-gray-700">Document Health</h2>
                </div>
                <div className="p-5 space-y-2">
                  {[
                    { label: "Total",                count: data.document_stats.total,                shade: "bg-gray-50" },
                    { label: "Ready",                count: data.document_stats.ready,                shade: "bg-gray-50" },
                    { label: "Processing / Pending", count: data.document_stats.processing,           shade: "bg-gray-50" },
                    { label: "Failed",               count: data.document_stats.failed,               shade: data.document_stats.failed > 0 ? "bg-gray-100" : "bg-gray-50" },
                    { label: "Compliance Blocked",   count: data.document_stats.compliance_blocked ?? 0, shade: (data.document_stats.compliance_blocked ?? 0) > 0 ? "bg-gray-100" : "bg-gray-50" },
                  ].map(p => (
                    <div key={p.label} className={`flex items-center justify-between rounded-lg px-3 py-2 ${p.shade}`}>
                      <span className="text-xs font-medium text-gray-700">{p.label}</span>
                      <span className="text-sm font-bold text-gray-900">{p.count}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
                <div className="border-b border-gray-100 px-5 py-3 flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-gray-700">Recent Queries</h2>
                  {data.recent_queries.length > 0 && (
                    <button onClick={() => exportCSV(data.recent_queries, days)}
                      className="flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1 text-[11px] text-gray-500 hover:bg-gray-50 transition-colors">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-3 h-3">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
                      </svg>
                      Export CSV
                    </button>
                  )}
                </div>
                {data.recent_queries.length === 0 ? (
                  <p className="p-5 text-sm text-gray-400">No queries yet.</p>
                ) : (
                  <div className="divide-y divide-gray-100 overflow-y-auto" style={{ maxHeight: 320 }}>
                    {data.recent_queries.map(q => (
                      <div key={q.id} className="px-4 py-3 hover:bg-gray-50 transition-colors">
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-xs font-medium text-gray-800 line-clamp-2 flex-1">{q.query_text}</p>
                          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                            q.chunks_retrieved === 0 ? "bg-gray-100 text-gray-500" : "bg-gray-900 text-white"
                          }`}>
                            {q.chunks_retrieved === 0 ? "no src" : `${q.chunks_retrieved} src`}
                          </span>
                        </div>
                        <div className="mt-1 flex items-center gap-2 text-[11px] text-gray-400">
                          <span>{q.username}</span><span>·</span>
                          <span>{q.latency_ms} ms</span><span>·</span>
                          <span>{new Date(q.created_at).toLocaleString()}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-gray-200 bg-white shadow-sm">
              <div className="border-b border-gray-100 px-5 py-3 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-sm font-semibold text-gray-700">Knowledge Gaps</h2>
                  <p className="mt-0.5 text-xs text-gray-400">Questions your knowledge base couldn&apos;t answer</p>
                </div>
                <span className="shrink-0 rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-600">
                  {data.unanswered.unanswered} unanswered
                </span>
              </div>
              {data.zero_chunk_queries.length === 0 ? (
                <div className="px-5 py-8 text-center">
                  <p className="text-2xl mb-2">✅</p>
                  <p className="text-sm font-medium text-gray-700">No knowledge gaps in this period</p>
                  <p className="text-xs text-gray-400 mt-1">All queries found relevant documents.</p>
                </div>
              ) : (
                <div className="divide-y divide-gray-100">
                  {data.zero_chunk_queries.map((q, i) => (
                    <div key={i} className="px-5 py-3 hover:bg-gray-50 transition-colors">
                      <p className="text-sm text-gray-800">{q.query_text}</p>
                      <p className="mt-1 text-[11px] text-gray-400">{q.username} · {new Date(q.created_at).toLocaleString()}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}
