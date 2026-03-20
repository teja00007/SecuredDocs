"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { User } from "@/types";

interface AdminUser {
  id: string;
  username: string;
  email: string;
  is_active: boolean;
  roles: string[];
  teams: string[];
  created_at: string;
}

interface AdminStats {
  user_count: number;
  document_count: number;
  collection_count: number;
  team_count: number;
}

interface Invite {
  id: string;
  email: string;
  invited_by?: string;
  expires_at: string;
  status: string;
  roles: string[];
}

interface Team {
  id: string;
  name: string;
}

type AdminTab = "users" | "invites";

const ALL_ROLES = ["admin", "analyst", "viewer"];

function relDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

export default function AdminPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();
  const [user, setUser] = useState<User | null>(null);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [userSearch, setUserSearch] = useState("");
  const [activeTab, setActiveTab] = useState<AdminTab>("users");

  // Create user dialog
  const [showCreate, setShowCreate] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRoles, setNewRoles] = useState<string[]>(["viewer"]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  // Inline role editing
  const [editingRoles, setEditingRoles] = useState<string | null>(null);
  const [pendingRoles, setPendingRoles] = useState<string[]>([]);

  // Invite user modal
  const [showInvite,    setShowInvite]    = useState(false);
  const [inviteEmail,   setInviteEmail]   = useState("");
  const [inviteRoles,   setInviteRoles]   = useState<string[]>(["viewer"]);
  const [inviteTeams,   setInviteTeams]   = useState<string[]>([]);
  const [inviting,      setInviting]      = useState(false);
  const [inviteError,   setInviteError]   = useState("");

  // Invites list
  const [invites,         setInvites]         = useState<Invite[]>([]);
  const [invitesLoading,  setInvitesLoading]  = useState(false);
  const [revokingInvite,  setRevokingInvite]  = useState<string | null>(null);

  // Teams list (for invite modal)
  const [teams, setTeams] = useState<Team[]>([]);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }

    api.get<User>("/api/v1/auth/me").then((u) => {
      if (!u.roles.includes("admin") && !u.is_super_admin) { router.replace("/"); return; }
      setUser(u);

      Promise.all([
        api.get<AdminUser[]>("/api/v1/admin/users"),
        api.get<{ id: string }[]>("/api/v1/documents").catch(() => []),
        api.get<{ id: string }[]>("/api/v1/collections").catch(() => []),
        api.get<Team[]>("/api/v1/teams").catch(() => []),
      ]).then(([us, docs, cols, ts]) => {
        setUsers(us);
        setTeams(ts);
        setStats({
          user_count: us.length,
          document_count: docs.length,
          collection_count: cols.length,
          team_count: ts.length,
        });
        setLoading(false);
      });
    });
  }, [router]);

  // Load invites when tab switches to "invites"
  useEffect(() => {
    if (activeTab !== "invites") return;
    setInvitesLoading(true);
    api.get<Invite[]>("/api/v1/invites")
      .then(setInvites)
      .catch(() => {})
      .finally(() => setInvitesLoading(false));
  }, [activeTab]);

  async function handleCreateUser(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setCreateError("");
    try {
      const created = await api.post<AdminUser>("/api/v1/admin/users", {
        username: newUsername,
        email: newEmail,
        password: newPassword,
        roles: newRoles,
      });
      setUsers((prev) => [...prev, created]);
      setStats((s) => s ? { ...s, user_count: s.user_count + 1 } : s);
      setShowCreate(false);
      setNewUsername(""); setNewEmail(""); setNewPassword(""); setNewRoles(["viewer"]);
      success("User created");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to create user";
      setCreateError(msg);
      toastError(msg);
    } finally {
      setCreating(false);
    }
  }

  async function saveRoles(userId: string) {
    try {
      const updated = await api.patch<AdminUser>(`/api/v1/admin/users/${userId}/roles`, {
        roles: pendingRoles,
      });
      setUsers((prev) => prev.map((u) => u.id === userId ? updated : u));
      setEditingRoles(null);
      success("Roles updated");
    } catch {
      toastError("Failed to update roles");
    }
  }

  async function toggleActive(u: AdminUser) {
    try {
      const updated = await api.patch<AdminUser>(
        `/api/v1/admin/users/${u.id}/activate?active=${!u.is_active}`, {}
      );
      setUsers((prev) => prev.map((x) => x.id === u.id ? updated : x));
      success(updated.is_active ? "User activated" : "User deactivated");
    } catch {
      toastError("Failed to update user status");
    }
  }

  async function handleDeleteUser(u: AdminUser) {
    if (!confirm(`Delete user "${u.username}"? This cannot be undone.`)) return;
    try {
      await api.delete(`/api/v1/admin/users/${u.id}`);
      setUsers((prev) => prev.filter((x) => x.id !== u.id));
      setStats((s) => s ? { ...s, user_count: s.user_count - 1 } : s);
      success("User deleted");
    } catch {
      toastError("Failed to delete user");
    }
  }

  function startEditRoles(u: AdminUser) {
    setEditingRoles(u.id);
    setPendingRoles([...u.roles]);
  }

  function togglePendingRole(role: string) {
    setPendingRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]
    );
  }

  async function handleSendInvite(e: FormEvent) {
    e.preventDefault();
    setInviteError("");
    setInviting(true);
    try {
      await api.post("/api/v1/invites", {
        email: inviteEmail,
        roles: inviteRoles,
        team_ids: inviteTeams,
      });
      success(`Invite sent to ${inviteEmail}`);
      setShowInvite(false);
      setInviteEmail(""); setInviteRoles(["viewer"]); setInviteTeams([]);
      // Refresh invites list if on that tab
      if (activeTab === "invites") {
        api.get<Invite[]>("/api/v1/invites").then(setInvites).catch(() => {});
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to send invite";
      setInviteError(msg);
    } finally {
      setInviting(false);
    }
  }

  async function handleRevokeInvite(id: string) {
    setRevokingInvite(id);
    try {
      await api.delete(`/api/v1/invites/${id}`);
      setInvites(prev => prev.filter(i => i.id !== id));
      success("Invite revoked");
    } catch {
      toastError("Failed to revoke invite");
    } finally {
      setRevokingInvite(null);
    }
  }

  function toggleInviteTeam(teamId: string) {
    setInviteTeams(prev =>
      prev.includes(teamId) ? prev.filter(t => t !== teamId) : [...prev, teamId]
    );
  }

  if (!user) return null;

  return (
    <main className="flex flex-1 flex-col overflow-hidden">
      <div className="border-b border-slate-200 bg-white px-5 py-3">
        <h2 className="font-semibold text-slate-800">Admin Panel</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-6">
        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            {[
              { label: "Users", value: stats.user_count, icon: "👤" },
              { label: "Documents", value: stats.document_count, icon: "📄" },
              { label: "Collections", value: stats.collection_count, icon: "🗂️" },
              { label: "Teams", value: stats.team_count, icon: "👥" },
            ].map((s) => (
              <div key={s.label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                <div className="text-2xl">{s.icon}</div>
                <div className="mt-2 text-2xl font-bold text-slate-800">{s.value}</div>
                <div className="text-xs text-slate-400">{s.label}</div>
              </div>
            ))}
            <Link href="/admin/compliance"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">🛡️</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Compliance Config</div>
              <div className="text-xs text-slate-400">HIPAA · PCI-DSS · GDPR · SOX</div>
            </Link>
            <Link href="/admin/analytics"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">📊</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Analytics</div>
              <div className="text-xs text-slate-400">Queries · Latency · Users</div>
            </Link>
            <Link href="/admin/connectors"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">🔌</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Data Connectors</div>
              <div className="text-xs text-slate-400">S3 · GCS · Azure · Drive · Confluence</div>
            </Link>
            <Link href="/admin/rag-settings"
              className="rounded-xl border border-indigo-200 bg-white p-4 shadow-sm hover:border-indigo-400 hover:bg-indigo-50 transition-colors">
              <div className="text-2xl">🧠</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">RAG Pipeline</div>
              <div className="text-xs text-slate-400">Retrieval · Re-ranking · Chunking</div>
            </Link>
            <Link href="/admin/settings"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">⚙️</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Settings</div>
              <div className="text-xs text-slate-400">LLM · SMTP · Upload limits</div>
            </Link>
            <Link href="/admin/branding"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">🎨</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Branding</div>
              <div className="text-xs text-slate-400">Logo · Colors · Org name</div>
            </Link>
            <Link href="/admin/storage"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">💾</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Storage</div>
              <div className="text-xs text-slate-400">Usage · Quota · By user & team</div>
            </Link>
            <Link href="/admin/webhooks"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">🔗</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Webhooks</div>
              <div className="text-xs text-slate-400">HTTP callbacks · Events</div>
            </Link>
            <Link href="/admin/reports"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">📋</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Reports</div>
              <div className="text-xs text-slate-400">User activity · Docs · Teams</div>
            </Link>
            <Link href="/admin/widget"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">🔲</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Embed Widget</div>
              <div className="text-xs text-slate-400">Chat widget · Tokens · Snippets</div>
            </Link>
<Link href="/admin/service-accounts"
              className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-blue-300 hover:bg-blue-50 transition-colors">
              <div className="text-2xl">🤖</div>
              <div className="mt-2 text-sm font-semibold text-slate-800">Service Accounts</div>
              <div className="text-xs text-slate-400">CI/CD · API keys · Roles</div>
            </Link>
            {user.is_super_admin && (
              <Link href="/admin/companies"
                className="rounded-xl border border-violet-200 bg-violet-50 p-4 shadow-sm hover:border-violet-400 hover:bg-violet-100 transition-colors">
                <div className="text-2xl">🏢</div>
                <div className="mt-2 text-sm font-semibold text-violet-800">Companies</div>
                <div className="text-xs text-violet-500">Tenants · Plans · Isolation</div>
              </Link>
            )}
          </div>
        )}

        {/* ── Tabs ── */}
        <div>
          <div className="flex items-center justify-between mb-3">
            {/* Tab buttons */}
            <div className="flex gap-0.5 rounded-lg border border-slate-200 bg-slate-100 p-0.5">
              {(["users", "invites"] as AdminTab[]).map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-1.5 rounded-md text-xs font-medium transition-colors capitalize ${
                    activeTab === tab
                      ? "bg-white text-slate-800 shadow-sm"
                      : "text-slate-500 hover:text-slate-700"
                  }`}
                >
                  {tab === "users" ? `Users (${users.length})` : "Invites"}
                </button>
              ))}
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2">
              {activeTab === "users" && (
                <>
                  <div className="relative">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                      className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none">
                      <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
                    </svg>
                    <input
                      type="search"
                      value={userSearch}
                      onChange={e => setUserSearch(e.target.value)}
                      placeholder="Search users…"
                      className="rounded-lg border border-slate-200 bg-white pl-9 pr-3 py-1.5 text-xs text-slate-700 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                    />
                  </div>
                  <button
                    onClick={() => setShowCreate(true)}
                    className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 shrink-0"
                  >
                    + Add User
                  </button>
                </>
              )}
              <button
                onClick={() => { setShowInvite(true); setInviteEmail(""); setInviteRoles(["viewer"]); setInviteTeams([]); setInviteError(""); }}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 shrink-0"
              >
                Invite User
              </button>
            </div>
          </div>

          {/* ── Users table ── */}
          {activeTab === "users" && (
            loading ? (
              <p className="text-sm text-slate-400">Loading…</p>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
                <table className="w-full min-w-[700px] text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-3 text-left">Username</th>
                      <th className="px-4 py-3 text-left">Email</th>
                      <th className="px-4 py-3 text-left">Roles</th>
                      <th className="px-4 py-3 text-left">Teams</th>
                      <th className="px-4 py-3 text-left">Status</th>
                      <th className="px-4 py-3 text-left">Joined</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {users.filter(u => {
                      if (!userSearch.trim()) return true;
                      const q = userSearch.toLowerCase();
                      return u.username.toLowerCase().includes(q) || u.email.toLowerCase().includes(q) || u.roles.some(r => r.includes(q));
                    }).map((u) => (
                      <tr key={u.id} className="hover:bg-slate-50">
                        <td className="px-4 py-3 font-medium text-slate-700">{u.username}</td>
                        <td className="px-4 py-3 text-slate-500 text-xs">{u.email}</td>
                        <td className="px-4 py-3">
                          {editingRoles === u.id ? (
                            <div className="flex items-center gap-2">
                              <div className="flex gap-1">
                                {ALL_ROLES.map((r) => (
                                  <label key={r} className="flex items-center gap-1 text-xs cursor-pointer">
                                    <input
                                      type="checkbox"
                                      checked={pendingRoles.includes(r)}
                                      onChange={() => togglePendingRole(r)}
                                      className="accent-blue-600"
                                    />
                                    {r}
                                  </label>
                                ))}
                              </div>
                              <button onClick={() => saveRoles(u.id)}
                                className="text-xs text-blue-600 hover:underline">Save</button>
                              <button onClick={() => setEditingRoles(null)}
                                className="text-xs text-slate-400 hover:underline">Cancel</button>
                            </div>
                          ) : (
                            <div className="flex flex-wrap items-center gap-1">
                              {u.roles.map((r) => (
                                <span key={r} className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">{r}</span>
                              ))}
                              {u.id !== user.id && (
                                <button onClick={() => startEditRoles(u)}
                                  className="text-xs text-slate-400 hover:text-blue-600 hover:underline ml-1">edit</button>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-500 text-xs">{u.teams.length}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${u.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
                            {u.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{new Date(u.created_at).toLocaleDateString()}</td>
                        <td className="px-4 py-3">
                          {u.id !== user.id && (
                            <div className="flex items-center gap-2">
                              <button
                                onClick={() => toggleActive(u)}
                                className={`text-xs hover:underline ${u.is_active ? "text-orange-500" : "text-green-600"}`}
                              >
                                {u.is_active ? "Deactivate" : "Activate"}
                              </button>
                              <button
                                onClick={() => handleDeleteUser(u)}
                                className="text-xs text-red-500 hover:underline"
                              >
                                Delete
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}

          {/* ── Invites table ── */}
          {activeTab === "invites" && (
            invitesLoading ? (
              <p className="text-sm text-slate-400">Loading…</p>
            ) : invites.length === 0 ? (
              <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
                <p className="text-sm text-slate-400">No pending invites</p>
                <button
                  onClick={() => { setShowInvite(true); setInviteEmail(""); setInviteRoles(["viewer"]); setInviteTeams([]); setInviteError(""); }}
                  className="mt-3 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
                >
                  Send your first invite
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
                <table className="w-full min-w-[600px] text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-3 text-left">Email</th>
                      <th className="px-4 py-3 text-left">Invited by</th>
                      <th className="px-4 py-3 text-left">Roles</th>
                      <th className="px-4 py-3 text-left">Expires</th>
                      <th className="px-4 py-3 text-left">Status</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {invites.map(invite => (
                      <tr key={invite.id} className="hover:bg-slate-50">
                        <td className="px-4 py-3 font-medium text-slate-700">{invite.email}</td>
                        <td className="px-4 py-3 text-slate-500 text-xs">{invite.invited_by ?? "—"}</td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1">
                            {invite.roles.map(r => (
                              <span key={r} className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 capitalize">{r}</span>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{relDate(invite.expires_at)}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                            invite.status === "pending"
                              ? "bg-amber-100 text-amber-700"
                              : invite.status === "accepted"
                                ? "bg-green-100 text-green-700"
                                : "bg-slate-100 text-slate-500"
                          }`}>
                            {invite.status}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          {invite.status === "pending" && (
                            <button
                              onClick={() => handleRevokeInvite(invite.id)}
                              disabled={revokingInvite === invite.id}
                              className="text-xs text-red-500 hover:underline disabled:opacity-50"
                            >
                              {revokingInvite === invite.id ? "Revoking…" : "Revoke"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          )}
        </div>
      </div>

      {/* ── Create user dialog ── */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h3 className="font-semibold">New User</h3>
              <button onClick={() => setShowCreate(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={handleCreateUser} className="space-y-4 px-5 py-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Username</label>
                <input type="text" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} required minLength={3}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Email</label>
                <input type="email" value={newEmail} onChange={(e) => setNewEmail(e.target.value)} required
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Password</label>
                <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required minLength={8}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Roles</label>
                <div className="flex gap-4">
                  {ALL_ROLES.map((r) => (
                    <label key={r} className="flex items-center gap-1.5 text-sm cursor-pointer">
                      <input type="checkbox" checked={newRoles.includes(r)}
                        onChange={() => setNewRoles((prev) => prev.includes(r) ? prev.filter((x) => x !== r) : [...prev, r])}
                        className="accent-blue-600" />
                      <span className="capitalize">{r}</span>
                    </label>
                  ))}
                </div>
              </div>
              {createError && <p className="text-sm text-red-600">{createError}</p>}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setShowCreate(false)}
                  className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">Cancel</button>
                <button type="submit" disabled={creating}
                  className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40">
                  {creating ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Invite user modal ── */}
      {showInvite && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h3 className="font-semibold text-slate-800">Invite User</h3>
              <button
                onClick={() => { setShowInvite(false); setInviteError(""); }}
                className="text-slate-400 hover:text-slate-600 transition-colors"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <form onSubmit={handleSendInvite} className="space-y-4 px-5 py-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Email address</label>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={e => setInviteEmail(e.target.value)}
                  required
                  autoFocus
                  placeholder="colleague@company.com"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-600">Roles</label>
                <div className="flex gap-4">
                  {ALL_ROLES.map(r => (
                    <label key={r} className="flex items-center gap-1.5 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        checked={inviteRoles.includes(r)}
                        onChange={() => setInviteRoles(prev => prev.includes(r) ? prev.filter(x => x !== r) : [...prev, r])}
                        className="accent-indigo-600"
                      />
                      <span className="capitalize">{r}</span>
                    </label>
                  ))}
                </div>
              </div>

              {teams.length > 0 && (
                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-600">Teams (optional)</label>
                  <div className="space-y-1.5 max-h-32 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2">
                    {teams.map(t => (
                      <label key={t.id} className="flex items-center gap-2 text-sm cursor-pointer hover:bg-white rounded px-1 py-0.5 transition-colors">
                        <input
                          type="checkbox"
                          checked={inviteTeams.includes(t.id)}
                          onChange={() => toggleInviteTeam(t.id)}
                          className="accent-indigo-600"
                        />
                        <span className="text-slate-700">{t.name}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {inviteError && (
                <p className="text-xs text-red-600 flex items-center gap-1">
                  <span>⚠</span> {inviteError}
                </p>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => { setShowInvite(false); setInviteError(""); }}
                  className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={inviting || !inviteEmail.trim() || inviteRoles.length === 0}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors"
                >
                  {inviting ? "Sending…" : "Send Invite"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
