"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { Team, TeamDetail, User } from "@/types";

interface BasicUser { id: string; username: string; email: string }

function avatarColor(name: string): string {
  const colors = ["#6366f1","#8b5cf6","#ec4899","#f97316","#10b981","#0ea5e9","#14b8a6","#f59e0b"];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}

function TeamsPage() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const { success, error: toastError } = useToast();

  const [user,          setUser]          = useState<User | null>(null);
  const [teams,         setTeams]         = useState<Team[]>([]);
  const [selectedTeam,  setSelectedTeam]  = useState<TeamDetail | null>(null);
  const [deleting,      setDeleting]      = useState<string | null>(null);

  // Add member
  const [addSearch,     setAddSearch]     = useState("");
  const [allUsers,      setAllUsers]      = useState<BasicUser[]>([]);
  const [selectedIds,   setSelectedIds]   = useState<string[]>([]);
  const [addingMembers, setAddingMembers] = useState(false);

  // Create team dialog
  const [showCreate,  setShowCreate]  = useState(false);
  const [newName,     setNewName]     = useState("");
  const [newDesc,     setNewDesc]     = useState("");
  const [creating,    setCreating]    = useState(false);
  const [createErr,   setCreateErr]   = useState("");

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    Promise.all([
      api.get<User>("/api/v1/auth/me"),
      api.get<Team[]>("/api/v1/teams"),
    ]).then(([u, ts]) => { setUser(u); setTeams(ts); }).catch(() => {});
  }, [router]);

  useEffect(() => {
    const teamId = searchParams.get("team");
    if (teamId) loadTeam(teamId);
    if (searchParams.get("new") === "1") setShowCreate(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  async function loadTeam(id: string) {
    try {
      const [detail, users] = await Promise.all([
        api.get<TeamDetail>(`/api/v1/teams/${id}`),
        api.get<BasicUser[]>("/api/v1/admin/users/search?limit=200"),
      ]);
      setSelectedTeam(detail);
      const memberIds = new Set(detail.members.map(m => m.id));
      setAllUsers(users.filter(u => !memberIds.has(u.id)));
      setAddSearch("");
      setSelectedIds([]);
    } catch { /* ignore */ }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreating(true); setCreateErr("");
    try {
      const team = await api.post<Team>("/api/v1/teams", { name: newName, description: newDesc });
      setTeams(prev => [team, ...prev]);
      setShowCreate(false); setNewName(""); setNewDesc("");
      success("Team created");
    } catch (err) {
      setCreateErr(err instanceof Error ? err.message : "Failed");
    } finally { setCreating(false); }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this team?")) return;
    setDeleting(id);
    try {
      await api.delete(`/api/v1/teams/${id}`);
      setTeams(prev => prev.filter(t => t.id !== id));
      if (selectedTeam?.id === id) setSelectedTeam(null);
      success("Team deleted");
    } catch { toastError("Failed to delete"); } finally { setDeleting(null); }
  }

  async function handleLeave(teamId: string) {
    if (!user || !confirm("Leave this team?")) return;
    try {
      await api.delete(`/api/v1/teams/${teamId}/members/${user.id}`);
      setTeams(prev => prev.filter(t => t.id !== teamId));
      setSelectedTeam(null);
      success("Left the team");
    } catch { toastError("Failed to leave"); }
  }

  async function handleRemoveMember(userId: string) {
    if (!selectedTeam || !confirm("Remove this member?")) return;
    try {
      await api.delete(`/api/v1/teams/${selectedTeam.id}/members/${userId}`);
      setSelectedTeam(prev => prev ? { ...prev, members: prev.members.filter(m => m.id !== userId) } : prev);
      setTeams(prev => prev.map(t => t.id === selectedTeam.id ? { ...t, member_count: t.member_count - 1 } : t));
      setAllUsers(prev => {
        const removed = selectedTeam.members.find(m => m.id === userId);
        if (removed) return [...prev, { id: removed.id, username: removed.username, email: removed.email }];
        return prev;
      });
      success("Member removed");
    } catch { toastError("Failed to remove"); }
  }

  async function handleAddMembers() {
    if (!selectedTeam || selectedIds.length === 0) return;
    setAddingMembers(true);
    try {
      await api.post(`/api/v1/teams/${selectedTeam.id}/members`, { user_ids: selectedIds });
      const detail = await api.get<TeamDetail>(`/api/v1/teams/${selectedTeam.id}`);
      setSelectedTeam(detail);
      setTeams(prev => prev.map(t => t.id === selectedTeam.id ? { ...t, member_count: detail.members.length } : t));
      const memberIds = new Set(detail.members.map(m => m.id));
      setAllUsers(prev => prev.filter(u => !memberIds.has(u.id)));
      setSelectedIds([]); setAddSearch("");
      success(`${selectedIds.length} member${selectedIds.length !== 1 ? "s" : ""} added`);
    } catch { toastError("Failed to add members"); } finally { setAddingMembers(false); }
  }

  const canManage = !!user && !!selectedTeam &&
    (user.roles.includes("admin") || selectedTeam.created_by === user.id);

  const suggestions = addSearch.length > 0
    ? allUsers.filter(u =>
        u.username.toLowerCase().includes(addSearch.toLowerCase()) ||
        u.email.toLowerCase().includes(addSearch.toLowerCase())
      )
    : [];

  if (!user) return null;

  return (
    <>
    <div className="flex flex-1 flex-col overflow-hidden">
      {selectedTeam ? (
        <>
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3 shrink-0">
            <div className="min-w-0">
              <h3 className="font-semibold text-slate-800 truncate">{selectedTeam.name}</h3>
              {selectedTeam.description && (
                <p className="text-xs text-slate-400 truncate">{selectedTeam.description}</p>
              )}
            </div>
            <div className="flex items-center gap-2 shrink-0 ml-4">
              {canManage ? (
                <button onClick={() => handleDelete(selectedTeam.id)} disabled={deleting === selectedTeam.id}
                  className="rounded-lg px-3 py-1.5 text-xs text-red-500 hover:bg-red-50 disabled:opacity-40">
                  Delete team
                </button>
              ) : selectedTeam.members.some(m => m.id === user.id) && (
                <button onClick={() => handleLeave(selectedTeam.id)}
                  className="rounded-lg px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100">
                  Leave team
                </button>
              )}
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            {/* Add member — top, search-driven */}
            {canManage && (
              <div>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-400">Add member</p>
                <input
                  type="search"
                  placeholder="Search by name or email…"
                  value={addSearch}
                  onChange={e => setAddSearch(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
                {suggestions.length > 0 && (
                  <div className="mt-1 max-h-44 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-sm">
                    {suggestions.map(u => (
                      <label key={u.id} className="flex cursor-pointer items-center gap-3 px-3 py-2.5 hover:bg-slate-50">
                        <input type="checkbox" checked={selectedIds.includes(u.id)}
                          onChange={() => setSelectedIds(prev =>
                            prev.includes(u.id) ? prev.filter(x => x !== u.id) : [...prev, u.id]
                          )}
                          className="accent-indigo-600" />
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold uppercase text-white"
                          style={{ backgroundColor: avatarColor(u.username) }}>
                          {u.username[0]}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-800">{u.username}</p>
                          <p className="text-xs text-slate-400 truncate">{u.email}</p>
                        </div>
                      </label>
                    ))}
                  </div>
                )}
                {addSearch.length > 0 && suggestions.length === 0 && (
                  <p className="mt-2 text-xs text-slate-400 px-1">No users found.</p>
                )}
                {selectedIds.length > 0 && (
                  <button onClick={handleAddMembers} disabled={addingMembers}
                    className="mt-2 w-full rounded-lg bg-indigo-600 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
                    {addingMembers ? "Adding…" : `Add ${selectedIds.length} member${selectedIds.length !== 1 ? "s" : ""}`}
                  </button>
                )}
              </div>
            )}

            <div className="h-px bg-slate-100" />

            {/* Members list */}
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
                Members ({selectedTeam.members.length})
              </p>
              {selectedTeam.members.length === 0 ? (
                <p className="text-sm text-slate-400 py-4 text-center">No members yet.</p>
              ) : (
                <ul className="space-y-1.5">
                  {selectedTeam.members.map(m => (
                    <li key={m.id} className="flex items-center justify-between rounded-lg border border-slate-100 bg-white px-3 py-2.5">
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[11px] font-bold uppercase text-white"
                          style={{ backgroundColor: avatarColor(m.username) }}>
                          {m.username[0]}
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-800 truncate">{m.username}</p>
                          <p className="text-xs text-slate-400 truncate">{m.email}</p>
                        </div>
                      </div>
                      {canManage && m.id !== user.id && (
                        <button onClick={() => handleRemoveMember(m.id)}
                          className="ml-3 shrink-0 text-xs text-red-400 hover:text-red-600">
                          Remove
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="flex h-full flex-col items-center justify-center text-slate-400 p-8">
          <svg className="h-12 w-12 mb-3 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <p className="text-sm font-medium text-slate-500">Select a team from the sidebar</p>
          <button onClick={() => setShowCreate(true)}
            className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-medium text-white hover:bg-indigo-700">
            + New Team
          </button>
        </div>
      )}
    </div>

    {/* Create team dialog */}
    {showCreate && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
        <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
            <h3 className="font-semibold">New Team</h3>
            <button onClick={() => { setShowCreate(false); setNewName(""); setNewDesc(""); setCreateErr(""); }}
              className="text-slate-400 hover:text-slate-600 text-lg leading-none">✕</button>
          </div>
          <form onSubmit={handleCreate} className="space-y-4 px-5 py-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Team name</label>
              <input type="text" value={newName} onChange={e => setNewName(e.target.value)} required autoFocus
                placeholder="e.g. Backend Team"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">Description (optional)</label>
              <textarea value={newDesc} onChange={e => setNewDesc(e.target.value)} rows={2}
                className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
            </div>
            {createErr && <p className="text-sm text-red-600">{createErr}</p>}
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => { setShowCreate(false); setNewName(""); setNewDesc(""); setCreateErr(""); }}
                className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">Cancel</button>
              <button type="submit" disabled={creating}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
                {creating ? "Creating…" : "Create"}
              </button>
            </div>
          </form>
        </div>
      </div>
    )}
    </>
  );
}

export default function Page() {
  return <Suspense><TeamsPage /></Suspense>;
}
