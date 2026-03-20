"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { User } from "@/types";

interface Company {
  id: string;
  name: string;
  slug: string;
  plan: string;
  billing_cycle: string;
  max_users: number;
  max_storage_gb: number;
  is_active: boolean;
  owner_email: string | null;
  user_count: number;
  created_at: string;
}

const PLAN_COLORS: Record<string, string> = {
  free:       "bg-slate-100 text-slate-600",
  starter:    "bg-blue-100 text-blue-700",
  team:       "bg-indigo-100 text-indigo-700",
  business:   "bg-violet-100 text-violet-700",
  enterprise: "bg-amber-100 text-amber-700",
};

const PLAN_OPTIONS = ["free", "starter", "team", "business", "enterprise"];

export default function CompaniesPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();

  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  // Create dialog
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newPlan, setNewPlan] = useState("starter");
  const [newEmail, setNewEmail] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    api.get<User>("/api/v1/auth/me").then((u) => {
      if (!u.is_super_admin) { router.replace("/admin"); return; }
      loadCompanies();
    });
  }, [router]);

  function loadCompanies() {
    setLoading(true);
    api.get<Company[]>("/api/v1/companies")
      .then(setCompanies)
      .catch(() => toastError("Failed to load companies"))
      .finally(() => setLoading(false));
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateError("");
    try {
      const created = await api.post<Company>("/api/v1/companies", {
        name: newName,
        plan: newPlan,
        owner_email: newEmail || undefined,
      });
      setCompanies(prev => [created, ...prev]);
      setShowCreate(false);
      setNewName(""); setNewPlan("starter"); setNewEmail("");
      success("Company created");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to create company";
      setCreateError(msg);
    } finally {
      setCreating(false);
    }
  }

  async function toggleActive(c: Company) {
    try {
      const updated = await api.patch<Company>(`/api/v1/companies/${c.id}`, {
        is_active: !c.is_active,
      });
      setCompanies(prev => prev.map(x => x.id === c.id ? updated : x));
      success(updated.is_active ? "Company activated" : "Company deactivated");
    } catch {
      toastError("Failed to update company");
    }
  }

  const filtered = companies.filter(c => {
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return (
      c.name.toLowerCase().includes(q) ||
      c.slug.toLowerCase().includes(q) ||
      (c.owner_email ?? "").toLowerCase().includes(q) ||
      c.plan.includes(q)
    );
  });

  const totalUsers = companies.reduce((s, c) => s + c.user_count, 0);
  const activeCount = companies.filter(c => c.is_active).length;

  return (
    <main className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-slate-200 bg-white px-5 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Link href="/admin" className="text-slate-400 hover:text-slate-600 text-sm">Admin</Link>
          <span className="text-slate-300">/</span>
          <h2 className="font-semibold text-slate-800">Companies</h2>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700"
        >
          + New Company
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* Stats */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: "Total Companies", value: companies.length, icon: "🏢" },
            { label: "Active", value: activeCount, icon: "✅" },
            { label: "Total Users", value: totalUsers, icon: "👤" },
            { label: "Inactive", value: companies.length - activeCount, icon: "⏸️" },
          ].map(s => (
            <div key={s.label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="text-2xl">{s.icon}</div>
              <div className="mt-2 text-2xl font-bold text-slate-800">{s.value}</div>
              <div className="text-xs text-slate-400">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Search */}
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
              className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none">
              <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
            </svg>
            <input
              type="search"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search companies…"
              className="w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 py-1.5 text-xs text-slate-700 outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
            />
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
            <table className="w-full min-w-[800px] text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-3 text-left">Company</th>
                  <th className="px-4 py-3 text-left">Plan</th>
                  <th className="px-4 py-3 text-left">Owner</th>
                  <th className="px-4 py-3 text-left">Users</th>
                  <th className="px-4 py-3 text-left">Limits</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Created</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-400 text-sm">
                      No companies found
                    </td>
                  </tr>
                ) : filtered.map(c => (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-800">{c.name}</div>
                      <div className="text-xs text-slate-400">{c.slug}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${PLAN_COLORS[c.plan] ?? "bg-slate-100 text-slate-600"}`}>
                        {c.plan}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-500 text-xs">{c.owner_email ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span className={`text-sm font-semibold ${c.user_count >= c.max_users ? "text-red-600" : "text-slate-700"}`}>
                        {c.user_count}
                      </span>
                      <span className="text-xs text-slate-400"> / {c.max_users === 9999 ? "∞" : c.max_users}</span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">
                      {c.max_storage_gb === 9999 ? "∞" : c.max_storage_gb} GB storage
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${c.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
                        {c.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-400">
                      {new Date(c.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => toggleActive(c)}
                        className={`text-xs hover:underline ${c.is_active ? "text-orange-500" : "text-green-600"}`}
                      >
                        {c.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create Company Dialog */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h3 className="font-semibold text-slate-800">New Company</h3>
              <button onClick={() => setShowCreate(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={handleCreate} className="space-y-4 px-5 py-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Company Name *</label>
                <input
                  type="text"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  required
                  placeholder="Acme Corp"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-100"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Plan</label>
                <select
                  value={newPlan}
                  onChange={e => setNewPlan(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-100"
                >
                  {PLAN_OPTIONS.map(p => (
                    <option key={p} value={p} className="capitalize">{p.charAt(0).toUpperCase() + p.slice(1)}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Owner Email</label>
                <input
                  type="email"
                  value={newEmail}
                  onChange={e => setNewEmail(e.target.value)}
                  placeholder="admin@acme.com"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-100"
                />
              </div>
              {createError && <p className="text-xs text-red-600">{createError}</p>}
              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating || !newName.trim()}
                  className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-40"
                >
                  {creating ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
