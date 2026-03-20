"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import type { User } from "@/types";

// ── Types ──────────────────────────────────────────────────────────────────────
interface ActivityRow {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  roles: string[];
  created_at: string;
  last_login: string | null;
  doc_count: number;
  team_count: number;
}

interface ActivityReport {
  total: number;
  items: ActivityRow[];
}

// ── Helpers ────────────────────────────────────────────────────────────────────
function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function exportCSV(rows: ActivityRow[]) {
  const header = ["Username", "Email", "Roles", "Teams", "Docs Uploaded", "Joined", "Status"];
  const dataRows = rows.map((r) => [
    r.username,
    r.email,
    r.roles.join("|"),
    r.team_count,
    r.doc_count,
    fmtDate(r.created_at),
    r.is_active ? "Active" : "Inactive",
  ]);
  const csv = [header, ...dataRows].map((row) => row.join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `nexus-user-activity-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const PAGE_SIZE = 50;

// ── Page ───────────────────────────────────────────────────────────────────────
export default function ReportsPage() {
  const router = useRouter();
  const [data, setData] = useState<ActivityReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  const loadReport = useCallback(async (pageIndex: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.get<ActivityReport>(
        `/api/v1/admin/reports/activity?limit=${PAGE_SIZE}&offset=${pageIndex * PAGE_SIZE}`
      );
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load report");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    api.get<User>("/api/v1/auth/me").then((u) => {
      if (!u.roles.includes("admin")) { router.replace("/"); return; }
      loadReport(0);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  function goToPage(newPage: number) {
    setPage(newPage);
    loadReport(newPage);
  }

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

  const filteredItems = (data?.items ?? []).filter((r) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      r.username.toLowerCase().includes(q) ||
      r.email.toLowerCase().includes(q) ||
      r.roles.some((role) => role.toLowerCase().includes(q))
    );
  });

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">
              &larr; Admin
            </Link>
            <span className="text-gray-300">/</span>
            <h1 className="font-semibold text-gray-900">User Activity Report</h1>
          </div>
          <div className="flex items-center gap-2">
            {data && data.items.length > 0 && (
              <button
                onClick={() => exportCSV(data.items)}
                className="flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 transition-colors"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-3.5 h-3.5">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
                </svg>
                Export CSV
              </button>
            )}
            <button
              onClick={() => loadReport(page)}
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
      </div>

      <div className="mx-auto w-full max-w-6xl space-y-5 p-6">
        {/* Summary bar */}
        {data && (
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <p className="text-sm text-gray-500">
              <span className="font-semibold text-gray-900">{data.total}</span> total users
              {search.trim() && filteredItems.length !== data.items.length && (
                <span className="ml-1 text-gray-400">
                  &mdash; showing {filteredItems.length} matching &quot;{search}&quot;
                </span>
              )}
            </p>

            {/* Search */}
            <div className="relative">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none">
                <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
              </svg>
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Filter by name, email, or role…"
                className="rounded-lg border border-gray-200 bg-white pl-9 pr-3 py-1.5 text-xs text-gray-700 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100 w-64"
              />
            </div>
          </div>
        )}

        {/* Error state */}
        {error ? (
          <div className="rounded-xl border border-gray-200 bg-white p-10 text-center shadow-sm">
            <p className="text-sm text-red-500 mb-3">{error}</p>
            <button
              onClick={() => loadReport(page)}
              className="rounded-lg bg-black px-4 py-2 text-sm font-medium text-white hover:bg-gray-800"
            >
              Retry
            </button>
          </div>
        ) : loading && !data ? (
          <div className="flex justify-center py-24">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-gray-900 border-t-transparent" />
          </div>
        ) : data ? (
          <>
            {/* Table */}
            <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm">
              <table className="w-full min-w-[750px] text-sm">
                <thead className="border-b border-gray-200 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-4 py-3 text-left">User</th>
                    <th className="px-4 py-3 text-left">Email</th>
                    <th className="px-4 py-3 text-left">Role</th>
                    <th className="px-4 py-3 text-right">Teams</th>
                    <th className="px-4 py-3 text-right">Docs Uploaded</th>
                    <th className="px-4 py-3 text-left">Joined</th>
                    <th className="px-4 py-3 text-left">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-4 py-10 text-center text-sm text-gray-400">
                        {search.trim() ? "No users match your search." : "No users found."}
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map((row) => (
                      <tr key={row.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-[10px] font-bold text-white uppercase">
                              {row.username[0]}
                            </span>
                            <span className="font-medium text-gray-800">{row.username}</span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-gray-500 text-xs">{row.email}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {row.roles.length === 0 ? (
                              <span className="text-xs text-gray-400">—</span>
                            ) : (
                              row.roles.map((r) => (
                                <span
                                  key={r}
                                  className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                                    r === "admin"
                                      ? "bg-gray-900 text-white"
                                      : r === "analyst"
                                      ? "bg-gray-200 text-gray-700"
                                      : "bg-gray-100 text-gray-600"
                                  }`}
                                >
                                  {r}
                                </span>
                              ))
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right text-gray-700 tabular-nums">
                          {row.team_count}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-700 tabular-nums">
                          {row.doc_count}
                        </td>
                        <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                          {fmtDate(row.created_at)}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                              row.is_active
                                ? "bg-green-100 text-green-700"
                                : "bg-red-100 text-red-500"
                            }`}
                          >
                            {row.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between gap-4">
                <p className="text-xs text-gray-400">
                  Page {page + 1} of {totalPages}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => goToPage(page - 1)}
                    disabled={page === 0 || loading}
                    className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    &larr; Previous
                  </button>
                  <button
                    onClick={() => goToPage(page + 1)}
                    disabled={page >= totalPages - 1 || loading}
                    className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                  >
                    Next &rarr;
                  </button>
                </div>
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}
