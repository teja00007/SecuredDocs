"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { User } from "@/types";

interface ServiceAccount {
  id: string;
  name: string;
  roles: string[];
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
}

interface CreateResponse extends ServiceAccount {
  plain_api_key: string;
}

const ALL_ROLES = ["admin", "analyst", "viewer"];

function relDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
  });
}

export default function ServiceAccountsPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();
  const [loading, setLoading] = useState(true);
  const [accounts, setAccounts] = useState<ServiceAccount[]>([]);

  // Create form
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newRoles, setNewRoles] = useState<string[]>(["viewer"]);
  const [newExpiry, setNewExpiry] = useState("");
  const [creating, setCreating] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  // Revoke
  const [revokingId, setRevokingId] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    api.get<User>("/api/v1/auth/me").then(u => {
      if (!u.roles.includes("admin") && !u.is_super_admin) { router.replace("/"); return; }
      loadAccounts();
    }).catch(() => router.replace("/login"));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function loadAccounts() {
    setLoading(true);
    try {
      const data = await api.get<ServiceAccount[]>("/api/v1/admin/service-accounts");
      setAccounts(data);
    } catch {
      toastError("Failed to load service accounts");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const created = await api.post<CreateResponse>("/api/v1/admin/service-accounts", {
        name: newName.trim(),
        roles: newRoles,
        expires_at: newExpiry || null,
      });
      setCreatedKey(created.plain_api_key);
      setAccounts(prev => [...prev, created]);
      setNewName(""); setNewRoles(["viewer"]); setNewExpiry("");
    } catch {
      toastError("Failed to create service account");
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(id: string, name: string) {
    if (!confirm(`Revoke service account "${name}"? This will immediately invalidate its API key.`)) return;
    setRevokingId(id);
    try {
      await api.delete(`/api/v1/admin/service-accounts/${id}`);
      setAccounts(prev => prev.filter(a => a.id !== id));
      success("Service account revoked");
    } catch {
      toastError("Failed to revoke service account");
    } finally {
      setRevokingId(null);
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
            <span className="text-gray-300">/</span>
            <div>
              <h1 className="font-semibold text-gray-900">Service Accounts</h1>
              <p className="text-xs text-gray-400 mt-0.5">Non-human identities for CI/CD pipelines and automation</p>
            </div>
          </div>
          <button
            onClick={() => { setShowCreate(true); setCreatedKey(null); }}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
          >
            + New Service Account
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-3xl space-y-4">

          {/* API key reveal banner */}
          {createdKey && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
              <p className="text-sm font-semibold text-amber-800 mb-2">
                Save this API key — it will not be shown again.
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-lg bg-white border border-amber-200 px-3 py-2 text-xs font-mono text-amber-900 break-all">
                  {createdKey}
                </code>
                <button
                  onClick={() => { navigator.clipboard.writeText(createdKey); success("Copied"); }}
                  className="shrink-0 rounded-lg border border-amber-300 bg-white px-3 py-2 text-xs font-medium text-amber-700 hover:bg-amber-50 transition-colors"
                >
                  Copy
                </button>
              </div>
              <button
                onClick={() => setCreatedKey(null)}
                className="mt-2 text-xs text-amber-600 hover:text-amber-800 transition-colors"
              >
                Dismiss
              </button>
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-16">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-300 border-t-gray-800" />
            </div>
          ) : accounts.length === 0 ? (
            <div className="rounded-xl border border-gray-200 bg-white p-12 text-center shadow-sm">
              <p className="text-4xl mb-3">🤖</p>
              <p className="text-sm font-medium text-gray-700">No service accounts yet</p>
              <p className="mt-1 text-xs text-gray-400">Create one for your CI/CD pipeline or automated ingestion scripts.</p>
              <button
                onClick={() => setShowCreate(true)}
                className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
              >
                Create first account
              </button>
            </div>
          ) : (
            <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead className="border-b border-gray-100 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500">
                  <tr>
                    <th className="px-4 py-3 text-left">Name</th>
                    <th className="px-4 py-3 text-left">Roles</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-left">Expires</th>
                    <th className="px-4 py-3 text-left">Created</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {accounts.map(a => (
                    <tr key={a.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium text-gray-800">{a.name}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {a.roles.map(r => (
                            <span key={r} className="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-700 capitalize">
                              {r}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                          a.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"
                        }`}>
                          {a.is_active ? "Active" : "Revoked"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400">
                        {a.expires_at ? relDate(a.expires_at) : "Never"}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400">{relDate(a.created_at)}</td>
                      <td className="px-4 py-3 text-right">
                        {a.is_active && (
                          <button
                            onClick={() => handleRevoke(a.id, a.name)}
                            disabled={revokingId === a.id}
                            className="text-xs text-red-500 hover:underline disabled:opacity-50"
                          >
                            {revokingId === a.id ? "Revoking…" : "Revoke"}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Create modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h3 className="font-semibold text-slate-800">New Service Account</h3>
              <button
                onClick={() => setShowCreate(false)}
                className="text-slate-400 hover:text-slate-600 transition-colors"
              >✕</button>
            </div>
            <form onSubmit={handleCreate} className="space-y-4 px-5 py-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Account name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  required
                  placeholder="e.g. github-actions-ingest"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600">Roles</label>
                <div className="flex gap-4">
                  {ALL_ROLES.map(r => (
                    <label key={r} className="flex items-center gap-1.5 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        checked={newRoles.includes(r)}
                        onChange={() => setNewRoles(prev =>
                          prev.includes(r) ? prev.filter(x => x !== r) : [...prev, r]
                        )}
                        className="accent-blue-600"
                      />
                      <span className="capitalize">{r}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Expiry (optional)</label>
                <input
                  type="date"
                  value={newExpiry}
                  onChange={e => setNewExpiry(e.target.value)}
                  min={new Date().toISOString().split("T")[0]}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowCreate(false)}
                  className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating || !newName.trim() || newRoles.length === 0}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40 transition-colors"
                >
                  {creating ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
