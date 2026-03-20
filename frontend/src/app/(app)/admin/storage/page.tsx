"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { User } from "@/types";

interface UserStorage {
  user_id: string;
  username: string;
  document_count: number;
  total_bytes: number;
}

interface TeamStorage {
  team_id: string;
  team_name: string;
  document_count: number;
  total_bytes: number;
}

interface StorageStats {
  total_documents: number;
  total_file_size_bytes: number;
  total_file_size_human: string;
  by_user: UserStorage[];
  by_team: TeamStorage[];
}

function humanBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function UsageBar({ bytes, max }: { bytes: number; max: number }) {
  const pct = max > 0 ? Math.min((bytes / max) * 100, 100) : 0;
  const color =
    pct > 80 ? "bg-red-400" : pct > 50 ? "bg-amber-400" : "bg-emerald-400";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 tabular-nums">{humanBytes(bytes)}</span>
    </div>
  );
}

export default function StoragePage() {
  const router = useRouter();
  const { error: toastError } = useToast();
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState<StorageStats | null>(null);
  const [view, setView] = useState<"user" | "team">("user");

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    api.get<User>("/api/v1/auth/me").then(u => {
      if (!u.roles.includes("admin")) { router.replace("/"); return; }
      api.get<StorageStats>("/api/v1/admin/storage")
        .then(setStats)
        .catch(() => toastError("Failed to load storage stats"))
        .finally(() => setLoading(false));
    }).catch(() => router.replace("/login"));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  if (loading) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden bg-gray-50">
        <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700">← Admin</Link>
            <span className="text-gray-300">/</span>
            <h1 className="font-semibold text-gray-900">Storage</h1>
          </div>
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-900 border-t-transparent" />
        </div>
      </div>
    );
  }

  const maxUserBytes = Math.max(...(stats?.by_user.map(u => u.total_bytes) ?? [1]));
  const maxTeamBytes = Math.max(...(stats?.by_team.map(t => t.total_bytes) ?? [1]));

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center gap-3">
          <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
          <span className="text-gray-300">/</span>
          <div>
            <h1 className="font-semibold text-gray-900">Storage Usage</h1>
            <p className="text-xs text-gray-400 mt-0.5">Breakdown of storage by user and team</p>
          </div>
        </div>
      </div>

      <div className="flex-1 p-6">
        <div className="mx-auto max-w-3xl space-y-6">

          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            {[
              { label: "Total Documents", value: stats?.total_documents.toLocaleString() ?? "—" },
              { label: "Total Storage Used", value: stats?.total_file_size_human ?? "—" },
              { label: "Avg per Document", value: stats && stats.total_documents > 0
                  ? humanBytes(Math.round((stats.total_file_size_bytes) / stats.total_documents))
                  : "—" },
            ].map(c => (
              <div key={c.label} className="rounded-xl border border-gray-200 bg-white px-5 py-4 shadow-sm">
                <p className="text-xs text-gray-400">{c.label}</p>
                <p className="mt-1 text-2xl font-bold text-gray-900">{c.value}</p>
              </div>
            ))}
          </div>

          {/* Tab toggle */}
          <div className="flex gap-0.5 rounded-lg border border-gray-200 bg-gray-100 p-0.5 w-fit">
            {(["user", "team"] as const).map(t => (
              <button
                key={t}
                onClick={() => setView(t)}
                className={`px-4 py-1.5 rounded-md text-xs font-medium transition-colors capitalize ${
                  view === t ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"
                }`}
              >
                By {t === "user" ? "User" : "Team"}
              </button>
            ))}
          </div>

          {/* By-user table */}
          {view === "user" && (
            <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
              <div className="border-b border-gray-100 px-5 py-4">
                <h3 className="text-sm font-semibold text-gray-700">Storage by User</h3>
              </div>
              {!stats?.by_user.length ? (
                <p className="px-5 py-8 text-center text-sm text-gray-400">No user storage data available</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="border-b border-gray-100 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500">
                    <tr>
                      <th className="px-5 py-3 text-left">User</th>
                      <th className="px-5 py-3 text-left">Documents</th>
                      <th className="px-5 py-3 text-left">Storage Used</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {[...stats.by_user]
                      .sort((a, b) => b.total_bytes - a.total_bytes)
                      .map(u => (
                        <tr key={u.user_id} className="hover:bg-gray-50">
                          <td className="px-5 py-3 font-medium text-gray-700">{u.username}</td>
                          <td className="px-5 py-3 text-gray-500">{u.document_count}</td>
                          <td className="px-5 py-3">
                            <UsageBar bytes={u.total_bytes} max={maxUserBytes} />
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

          {/* By-team table */}
          {view === "team" && (
            <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
              <div className="border-b border-gray-100 px-5 py-4">
                <h3 className="text-sm font-semibold text-gray-700">Storage by Team</h3>
              </div>
              {!stats?.by_team.length ? (
                <p className="px-5 py-8 text-center text-sm text-gray-400">No team storage data available</p>
              ) : (
                <table className="w-full text-sm">
                  <thead className="border-b border-gray-100 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500">
                    <tr>
                      <th className="px-5 py-3 text-left">Team</th>
                      <th className="px-5 py-3 text-left">Documents</th>
                      <th className="px-5 py-3 text-left">Storage Used</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {[...stats.by_team]
                      .sort((a, b) => b.total_bytes - a.total_bytes)
                      .map(t => (
                        <tr key={t.team_id} className="hover:bg-gray-50">
                          <td className="px-5 py-3 font-medium text-gray-700">{t.team_name}</td>
                          <td className="px-5 py-3 text-gray-500">{t.document_count}</td>
                          <td className="px-5 py-3">
                            <UsageBar bytes={t.total_bytes} max={maxTeamBytes} />
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
