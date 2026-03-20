"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

import { useToast } from "@/components/Toast";

type Status = "online" | "away" | "busy" | "offline";

interface User    { id: string; username: string; email: string; is_active: boolean; roles: string[]; created_at: string; display_name?: string | null; bio?: string | null }
interface Conv    { id: string; title: string; updated_at: string }
interface Doc     { id: string; filename: string; file_type: string; created_at: string }

// ── 2FA types ────────────────────────────────────────────────────────────────
interface TwoFASetupResponse {
  secret: string;
  otpauth_url: string;
  qr_data: string;
}

interface TwoFAStatusResponse {
  enabled: boolean;
}

// ── Session types ─────────────────────────────────────────────────────────────
interface Session {
  id: string;
  user_agent: string;
  ip_address: string;
  last_active: string;
  is_current: boolean;
}

const STATUS_CFG: Record<Status, { label: string; dot: string; chip: string }> = {
  online:  { label: "Online",           dot: "#22c55e", chip: "bg-green-50 text-green-700 border-green-200" },
  away:    { label: "Away",             dot: "#f59e0b", chip: "bg-amber-50 text-amber-700 border-amber-200" },
  busy:    { label: "Do not disturb",   dot: "#ef4444", chip: "bg-red-50 text-red-700 border-red-200" },
  offline: { label: "Appear offline",   dot: "#6b7280", chip: "bg-gray-50 text-gray-600 border-gray-200" },
};

function relTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function FileTypeBadge({ type }: { type: string }) {
  const ext = (type ?? "").split("/").pop()?.split(".").pop()?.toUpperCase() ?? "FILE";
  const colors: Record<string, string> = {
    PDF: "bg-red-50 text-red-600", DOCX: "bg-blue-50 text-blue-600", DOC: "bg-blue-50 text-blue-600",
    MD: "bg-slate-50 text-slate-600", TXT: "bg-slate-50 text-slate-600",
    CSV: "bg-green-50 text-green-600", XLSX: "bg-green-50 text-green-600",
  };
  return (
    <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold ${colors[ext] ?? "bg-gray-50 text-gray-500"}`}>
      {ext}
    </span>
  );
}

function friendlyBrowser(ua: string): string {
  if (!ua) return "Unknown device";
  if (ua.includes("Edg"))     return "Edge Browser";
  if (ua.includes("Chrome"))  return "Chrome Browser";
  if (ua.includes("Firefox")) return "Firefox";
  if (ua.includes("Safari"))  return "Safari";
  if (ua.includes("Opera"))   return "Opera";
  return ua.slice(0, 40);
}

export default function ProfilePage() {
  const router  = useRouter();
  const menuRef = useRef<HTMLDivElement>(null);
  const { success, error: toastError } = useToast();

  const [user,       setUser]       = useState<User | null>(null);
  const [status,     setStatus]     = useState<Status>("online");
  const [menuOpen,   setMenuOpen]   = useState(false);
  const [recentConvs, setRecentConvs] = useState<Conv[]>([]);
  const [recentDocs,  setRecentDocs]  = useState<Doc[]>([]);

  // Edit profile form
  const [editingProfile, setEditingProfile] = useState(false);
  const [displayNameDraft, setDisplayNameDraft] = useState("");
  const [bioDraft, setBioDraft] = useState("");
  const [profileSaving, setProfileSaving] = useState(false);

  // Change password form
  const [pwOpen,      setPwOpen]      = useState(false);
  const [currentPw,   setCurrentPw]   = useState("");
  const [newPw,       setNewPw]       = useState("");
  const [confirmPw,   setConfirmPw]   = useState("");
  const [pwLoading,   setPwLoading]   = useState(false);
  const [pwError,     setPwError]     = useState("");

  // ── 2FA state ───────────────────────────────────────────────────────────────
  const [tfaEnabled,      setTfaEnabled]      = useState<boolean | null>(null);
  const [tfaSetupData,    setTfaSetupData]    = useState<TwoFASetupResponse | null>(null);
  const [tfaVerifyCode,   setTfaVerifyCode]   = useState("");
  const [tfaVerifying,    setTfaVerifying]    = useState(false);
  const [tfaSetupLoading, setTfaSetupLoading] = useState(false);
  const [tfaBackupCodes,  setTfaBackupCodes]  = useState<string[]>([]);
  const [showBackupModal, setShowBackupModal] = useState(false);
  const [tfaError,        setTfaError]        = useState("");
  // Disable 2FA modal
  const [showDisable2FA,  setShowDisable2FA]  = useState(false);
  const [disableCode,     setDisableCode]     = useState("");
  const [disabling2FA,    setDisabling2FA]    = useState(false);
  const [disableError,    setDisableError]    = useState("");

  // ── Session state ────────────────────────────────────────────────────────────
  const [sessions,       setSessions]       = useState<Session[]>([]);
  const [sessionsOpen,   setSessionsOpen]   = useState(false);
  const [sessionsLoading,setSessionsLoading]= useState(false);
  const [revokingId,     setRevokingId]     = useState<string | null>(null);
  const [revokingAll,    setRevokingAll]    = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("nexus_status") as Status | null;
    if (saved && saved in STATUS_CFG) setStatus(saved);

    Promise.all([
      api.get<User>("/api/v1/auth/me"),
      api.get<Conv[]>("/api/v1/conversations"),
      api.get<Doc[]>("/api/v1/documents"),
      api.get<TwoFAStatusResponse>("/api/v1/auth/2fa/status").catch(() => null),
    ]).then(([u, convs, docs, tfa]) => {
      setUser(u);
      setRecentConvs(convs.slice(0, 8));
      setRecentDocs(docs.slice(0, 6));
      if (tfa) setTfaEnabled(tfa.enabled);
      else setTfaEnabled(false);
    }).catch(() => {});
  }, []);

  // Close status menu on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    if (menuOpen) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuOpen]);

  // Load sessions when section opens
  useEffect(() => {
    if (!sessionsOpen) return;
    setSessionsLoading(true);
    api.get<Session[]>("/api/v1/auth/sessions")
      .then(setSessions)
      .catch(() => {})
      .finally(() => setSessionsLoading(false));
  }, [sessionsOpen]);

  function saveStatus(s: Status) {
    setStatus(s);
    localStorage.setItem("nexus_status", s);
    setMenuOpen(false);
  }

  function startEditProfile() {
    setDisplayNameDraft(user?.display_name ?? "");
    setBioDraft(user?.bio ?? "");
    setEditingProfile(true);
  }

  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    setProfileSaving(true);
    try {
      const updated = await api.patch<User>("/api/v1/auth/profile", {
        display_name: displayNameDraft.trim() || null,
        bio: bioDraft.trim() || null,
      });
      setUser(prev => prev ? { ...prev, display_name: updated.display_name, bio: updated.bio } : prev);
      setEditingProfile(false);
      success("Profile updated");
    } catch {
      toastError("Failed to update profile");
    } finally {
      setProfileSaving(false);
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwError("");
    if (newPw !== confirmPw) { setPwError("Passwords do not match"); return; }
    if (newPw.length < 8) { setPwError("Password must be at least 8 characters"); return; }
    setPwLoading(true);
    try {
      await api.post("/api/v1/auth/change-password", { current_password: currentPw, new_password: newPw });
      success("Password changed successfully");
      setPwOpen(false);
      setCurrentPw(""); setNewPw(""); setConfirmPw("");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to change password";
      setPwError(msg.includes("incorrect") ? "Current password is incorrect" : msg);
      toastError("Could not change password");
    } finally {
      setPwLoading(false);
    }
  }

  // ── 2FA handlers ────────────────────────────────────────────────────────────
  async function handleSetup2FA() {
    setTfaSetupLoading(true);
    setTfaError("");
    try {
      const data = await api.post<TwoFASetupResponse>("/api/v1/auth/2fa/setup", {});
      setTfaSetupData(data);
      setTfaVerifyCode("");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to start 2FA setup";
      setTfaError(msg);
    } finally {
      setTfaSetupLoading(false);
    }
  }

  async function handleVerify2FA(e: React.FormEvent) {
    e.preventDefault();
    if (!tfaVerifyCode.trim()) return;
    setTfaVerifying(true);
    setTfaError("");
    try {
      const res = await api.post<{ backup_codes?: string[] }>("/api/v1/auth/2fa/verify-setup", { code: tfaVerifyCode });
      setTfaEnabled(true);
      setTfaSetupData(null);
      setTfaVerifyCode("");
      if (res.backup_codes && res.backup_codes.length > 0) {
        setTfaBackupCodes(res.backup_codes);
        setShowBackupModal(true);
      } else {
        success("Two-factor authentication enabled!");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Verification failed";
      setTfaError(msg.toLowerCase().includes("invalid") ? "Invalid code. Please try again." : msg);
    } finally {
      setTfaVerifying(false);
    }
  }

  async function handleDisable2FA(e: React.FormEvent) {
    e.preventDefault();
    if (!disableCode.trim()) return;
    setDisabling2FA(true);
    setDisableError("");
    try {
      await api.post("/api/v1/auth/2fa/disable", { code: disableCode });
      setTfaEnabled(false);
      setShowDisable2FA(false);
      setDisableCode("");
      success("Two-factor authentication disabled");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to disable 2FA";
      setDisableError(msg.toLowerCase().includes("invalid") ? "Invalid code. Please try again." : msg);
    } finally {
      setDisabling2FA(false);
    }
  }

  // ── Session handlers ─────────────────────────────────────────────────────────
  async function handleRevokeSession(id: string) {
    setRevokingId(id);
    try {
      await api.delete(`/api/v1/auth/sessions/${id}`);
      setSessions(prev => prev.filter(s => s.id !== id));
      success("Session revoked");
    } catch {
      toastError("Failed to revoke session");
    } finally {
      setRevokingId(null);
    }
  }

  async function handleRevokeAllOther() {
    setRevokingAll(true);
    try {
      await api.delete("/api/v1/auth/sessions");
      // Reload session list
      const updated = await api.get<Session[]>("/api/v1/auth/sessions");
      setSessions(updated);
      success("All other sessions logged out");
    } catch {
      toastError("Failed to log out other sessions");
    } finally {
      setRevokingAll(false);
    }
  }

  if (!user) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
      </div>
    );
  }

  const initials = user.username.split(".").map(p => p[0]?.toUpperCase() ?? "").join("").slice(0, 2) || user.username[0]?.toUpperCase() || "U";
  const memberSince = new Date(user.created_at).toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const cfg = STATUS_CFG[status];

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-slate-50">
      <div className="mx-auto w-full max-w-3xl px-6 py-8 space-y-6">

        {/* ── Profile card ──────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          {/* Banner */}
          <div className="h-24 bg-gradient-to-r from-indigo-600 via-indigo-500 to-violet-500" />

          <div className="px-6 pb-6">
            {/* Avatar row */}
            <div className="flex items-end justify-between -mt-10 mb-4">
              <div className="relative">
                <div className="flex h-20 w-20 items-center justify-center rounded-2xl bg-indigo-700 text-2xl font-bold text-white border-4 border-white shadow-lg select-none">
                  {initials}
                </div>
                <span
                  className="absolute -bottom-0.5 -right-0.5 h-4 w-4 rounded-full border-2 border-white"
                  style={{ backgroundColor: cfg.dot }}
                />
              </div>

              {/* Status picker */}
              <div ref={menuRef} className="relative">
                <button
                  onClick={() => setMenuOpen(v => !v)}
                  className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${cfg.chip}`}
                >
                  <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: cfg.dot }} />
                  {cfg.label}
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="w-3 h-3">
                    <path d="M6 9l6 6 6-6" />
                  </svg>
                </button>
                {menuOpen && (
                  <div className="absolute right-0 top-full mt-1 z-50 w-48 rounded-xl border border-gray-100 bg-white shadow-xl py-1.5">
                    {(Object.entries(STATUS_CFG) as [Status, typeof cfg][]).map(([key, c]) => (
                      <button
                        key={key}
                        onClick={() => saveStatus(key)}
                        className="flex w-full items-center gap-3 px-3 py-2 text-sm hover:bg-gray-50 transition-colors"
                      >
                        <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: c.dot }} />
                        <span className="flex-1 text-left text-gray-700">{c.label}</span>
                        {key === status && (
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="w-3.5 h-3.5 text-indigo-600">
                            <path d="M20 6L9 17l-5-5" />
                          </svg>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Name + meta */}
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <h1 className="text-xl font-semibold text-gray-900">
                  {user.display_name || user.username}
                </h1>
                {user.display_name && (
                  <p className="text-sm text-gray-400 mt-0.5">@{user.username}</p>
                )}
                <p className="text-sm text-gray-500 mt-0.5">{user.email}</p>
                <p className="text-xs text-gray-400 mt-1">Member since {memberSince}</p>
                {user.bio && (
                  <p className="mt-2 text-sm text-gray-600 leading-relaxed">{user.bio}</p>
                )}
              </div>
              {!editingProfile && (
                <button
                  onClick={startEditProfile}
                  className="shrink-0 rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50 transition-colors"
                >
                  Edit profile
                </button>
              )}
            </div>

            {/* Edit profile form */}
            {editingProfile && (
              <form onSubmit={handleSaveProfile} className="mt-4 space-y-3 rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">Display name</label>
                  <input
                    value={displayNameDraft}
                    onChange={e => setDisplayNameDraft(e.target.value)}
                    placeholder={user.username}
                    maxLength={255}
                    className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-600">Bio</label>
                  <textarea
                    value={bioDraft}
                    onChange={e => setBioDraft(e.target.value)}
                    placeholder="Tell your team a bit about yourself"
                    maxLength={500}
                    rows={3}
                    className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
                  />
                  <p className="mt-0.5 text-right text-[10px] text-gray-400">{bioDraft.length}/500</p>
                </div>
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setEditingProfile(false)}
                    className="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={profileSaving}
                    className="rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                  >
                    {profileSaving ? "Saving…" : "Save"}
                  </button>
                </div>
              </form>
            )}

            {/* Role badges */}
            <div className="flex flex-wrap gap-1.5 mt-3">
              {user.roles.map(r => (
                <span key={r} className="inline-flex items-center rounded-full bg-indigo-50 border border-indigo-100 px-2.5 py-0.5 text-xs font-medium text-indigo-700 capitalize">
                  {r}
                </span>
              ))}
            </div>
          </div>
        </div>

        {/* ── Logged-in-as card ─────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm px-5 py-4 flex items-center gap-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-slate-500">
              <rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" />
            </svg>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs text-gray-400">Logged in as</p>
            <p className="text-sm font-medium text-gray-800 truncate">{user.email}</p>
          </div>
          <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            user.is_active ? "bg-green-50 text-green-700 border border-green-200" : "bg-red-50 text-red-600 border border-red-200"
          }`}>
            {user.is_active ? "Active" : "Inactive"}
          </span>
        </div>

        {/* ── Account settings ──────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <button
            onClick={() => { setPwOpen(v => !v); setPwError(""); }}
            className="flex w-full items-center justify-between px-5 py-4 text-left hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-slate-500">
                  <rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-800">Change Password</p>
                <p className="text-xs text-gray-400">Update your account password</p>
              </div>
            </div>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
              className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${pwOpen ? "rotate-180" : ""}`}>
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>

          {pwOpen && (
            <form onSubmit={handleChangePassword} className="border-t border-gray-100 px-5 py-4 space-y-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Current password</label>
                <input
                  type="password"
                  value={currentPw}
                  onChange={e => setCurrentPw(e.target.value)}
                  required
                  autoComplete="current-password"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">New password</label>
                <input
                  type="password"
                  value={newPw}
                  onChange={e => setNewPw(e.target.value)}
                  required
                  minLength={8}
                  autoComplete="new-password"
                  placeholder="Min 8 characters"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Confirm new password</label>
                <input
                  type="password"
                  value={confirmPw}
                  onChange={e => setConfirmPw(e.target.value)}
                  required
                  autoComplete="new-password"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100"
                />
              </div>
              {pwError && (
                <p className="text-xs text-red-600 flex items-center gap-1">
                  <span>⚠</span> {pwError}
                </p>
              )}
              <div className="flex items-center justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => { setPwOpen(false); setCurrentPw(""); setNewPw(""); setConfirmPw(""); setPwError(""); }}
                  className="rounded-lg px-4 py-2 text-sm text-gray-500 hover:bg-gray-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={pwLoading || !currentPw || !newPw || !confirmPw}
                  className="rounded-xl bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                >
                  {pwLoading ? "Updating…" : "Update password"}
                </button>
              </div>
            </form>
          )}
        </div>

        {/* ── Two-Factor Authentication ──────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-5 py-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-slate-500">
                    <path d="M12 2L3 7v5c0 5.25 3.75 10.15 9 11.25C17.25 22.15 21 17.25 21 12V7l-9-5z" />
                  </svg>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-gray-800">Two-Factor Authentication</p>
                    {tfaEnabled === true && (
                      <span className="rounded-full bg-green-100 border border-green-200 px-2 py-0.5 text-[11px] font-semibold text-green-700">
                        Enabled
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400">
                    {tfaEnabled ? "Your account is protected with 2FA" : "Two-factor authentication adds an extra layer of security"}
                  </p>
                </div>
              </div>

              {tfaEnabled === null ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
              ) : tfaEnabled ? (
                <button
                  onClick={() => { setShowDisable2FA(true); setDisableCode(""); setDisableError(""); }}
                  className="shrink-0 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 transition-colors"
                >
                  Disable 2FA
                </button>
              ) : (
                !tfaSetupData && (
                  <button
                    onClick={handleSetup2FA}
                    disabled={tfaSetupLoading}
                    className="shrink-0 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                  >
                    {tfaSetupLoading ? "Loading…" : "Enable 2FA"}
                  </button>
                )
              )}
            </div>

            {/* Setup flow */}
            {!tfaEnabled && tfaSetupData && (
              <div className="mt-4 space-y-4 rounded-xl border border-indigo-100 bg-indigo-50/40 p-4">
                <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Step 1 — Scan QR code</p>
                <div className="flex flex-col items-center gap-3">
                  <div className="rounded-xl border border-gray-200 bg-white p-2 shadow-sm">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={`https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(tfaSetupData.qr_data || tfaSetupData.otpauth_url)}`}
                      alt="2FA QR Code"
                      width={200}
                      height={200}
                      className="rounded-lg"
                    />
                  </div>
                  <div className="w-full rounded-lg border border-dashed border-gray-300 bg-white px-3 py-2 text-center">
                    <p className="text-[11px] text-gray-400 mb-1">Can&apos;t scan? Enter this code manually:</p>
                    <p className="font-mono text-sm font-semibold tracking-widest text-gray-800 break-all select-all">
                      {tfaSetupData.secret}
                    </p>
                  </div>
                </div>

                <p className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Step 2 — Verify code</p>
                <form onSubmit={handleVerify2FA} className="flex items-center gap-2">
                  <input
                    type="text"
                    inputMode="numeric"
                    value={tfaVerifyCode}
                    onChange={e => setTfaVerifyCode(e.target.value.replace(/\D/g, ""))}
                    required
                    maxLength={6}
                    placeholder="000000"
                    autoComplete="one-time-code"
                    className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-center font-mono text-lg tracking-widest text-slate-800 outline-none transition focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-300 placeholder:font-sans placeholder:text-sm placeholder:tracking-normal"
                  />
                  <button
                    type="submit"
                    disabled={tfaVerifying || tfaVerifyCode.length !== 6}
                    className="rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {tfaVerifying ? "Verifying…" : "Enable 2FA"}
                  </button>
                </form>

                {tfaError && (
                  <p className="text-xs text-red-600 flex items-center gap-1">
                    <span>⚠</span> {tfaError}
                  </p>
                )}

                <button
                  type="button"
                  onClick={() => { setTfaSetupData(null); setTfaVerifyCode(""); setTfaError(""); }}
                  className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </div>

        {/* ── Active Sessions ────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <button
            onClick={() => setSessionsOpen(v => !v)}
            className="flex w-full items-center justify-between px-5 py-4 text-left hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-slate-100">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-slate-500">
                  <rect x="2" y="3" width="20" height="14" rx="2" />
                  <path d="M8 21h8M12 17v4" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-800">Active Sessions</p>
                <p className="text-xs text-gray-400">Manage your logged-in devices</p>
              </div>
            </div>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
              className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${sessionsOpen ? "rotate-180" : ""}`}>
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>

          {sessionsOpen && (
            <div className="border-t border-gray-100 px-5 py-4 space-y-3">
              {sessionsLoading ? (
                <div className="flex items-center justify-center py-6">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
                </div>
              ) : sessions.length === 0 ? (
                <p className="py-4 text-center text-sm text-gray-400">No active sessions found</p>
              ) : (
                <>
                  <div className="space-y-2">
                    {sessions.map(session => (
                      <div
                        key={session.id}
                        className={`flex items-center gap-3 rounded-xl px-3 py-3 ${session.is_current ? "bg-indigo-50 border border-indigo-100" : "bg-gray-50 border border-gray-100"}`}
                      >
                        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white border border-gray-200">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-gray-500">
                            <rect x="2" y="3" width="20" height="14" rx="2" />
                            <path d="M8 21h8M12 17v4" />
                          </svg>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium text-gray-800 truncate">
                              {friendlyBrowser(session.user_agent)}
                            </p>
                            {session.is_current && (
                              <span className="shrink-0 rounded-full bg-indigo-600 px-2 py-0.5 text-[10px] font-semibold text-white">
                                Current
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            <p className="text-xs text-gray-400 truncate">{session.ip_address}</p>
                            <span className="text-gray-300">·</span>
                            <p className="text-xs text-gray-400 shrink-0">{relTime(session.last_active)}</p>
                          </div>
                        </div>
                        {!session.is_current && (
                          <button
                            onClick={() => handleRevokeSession(session.id)}
                            disabled={revokingId === session.id}
                            className="shrink-0 rounded-lg border border-red-200 px-2.5 py-1 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
                          >
                            {revokingId === session.id ? "Revoking…" : "Revoke"}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>

                  {sessions.filter(s => !s.is_current).length > 0 && (
                    <div className="flex justify-end pt-1">
                      <button
                        onClick={handleRevokeAllOther}
                        disabled={revokingAll}
                        className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 transition-colors"
                      >
                        {revokingAll ? "Logging out…" : "Log out all other devices"}
                      </button>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* ── Recent activity ───────────────────────────────────────────── */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

          {/* Recent AI Chats */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-800">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-violet-500">
                  <path d="M8 10h8M8 14h5M5 3h14a2 2 0 012 2v11a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
                </svg>
                Recent AI Chats
              </h2>
              <button onClick={() => router.push("/")} className="text-xs text-indigo-600 hover:text-indigo-800 transition-colors">
                View all
              </button>
            </div>
            {recentConvs.length === 0 ? (
              <p className="py-6 text-center text-sm text-gray-400">No conversations yet</p>
            ) : (
              <ul className="space-y-0.5">
                {recentConvs.map(c => (
                  <li key={c.id}>
                    <button
                      onClick={() => router.push(`/?conv=${c.id}`)}
                      className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 hover:bg-gray-50 transition-colors text-left group"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" className="w-3.5 h-3.5 shrink-0 text-violet-300 group-hover:text-violet-500 transition-colors">
                        <path d="M8 10h8M8 14h5M5 3h14a2 2 0 012 2v11a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
                      </svg>
                      <span className="flex-1 min-w-0 truncate text-sm text-gray-700">{c.title}</span>
                      <span className="shrink-0 text-[11px] text-gray-400">{relTime(c.updated_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Recent Documents */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-800">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-blue-500">
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                  <path d="M14 2v6h6M8 13h8M8 17h5" />
                </svg>
                Recent Documents
              </h2>
              <button onClick={() => router.push("/documents")} className="text-xs text-indigo-600 hover:text-indigo-800 transition-colors">
                View all
              </button>
            </div>
            {recentDocs.length === 0 ? (
              <p className="py-6 text-center text-sm text-gray-400">No documents yet</p>
            ) : (
              <ul className="space-y-0.5">
                {recentDocs.map(d => (
                  <li key={d.id}>
                    <button
                      onClick={() => router.push("/documents")}
                      className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 hover:bg-gray-50 transition-colors text-left group"
                    >
                      <FileTypeBadge type={d.file_type} />
                      <span className="flex-1 min-w-0 truncate text-sm text-gray-700">{d.filename}</span>
                      <span className="shrink-0 text-[11px] text-gray-400">{relTime(d.created_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

      </div>

      {/* ── Backup Codes Modal ─────────────────────────────────────────────── */}
      {showBackupModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="font-semibold text-gray-900">Save your backup codes</h3>
            </div>
            <div className="px-5 py-4 space-y-3">
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5">
                <p className="text-xs font-semibold text-amber-700">Save these codes somewhere safe!</p>
                <p className="text-xs text-amber-600 mt-0.5">They won&apos;t be shown again. Each code can only be used once.</p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-gray-50 p-3">
                <ul className="space-y-1.5">
                  {tfaBackupCodes.map((code, i) => (
                    <li key={i} className="font-mono text-sm text-gray-800 text-center tracking-widest select-all">
                      {code}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="border-t border-gray-100 px-5 py-4 flex justify-end">
              <button
                onClick={() => { setShowBackupModal(false); setTfaBackupCodes([]); success("Two-factor authentication enabled!"); }}
                className="rounded-xl bg-indigo-600 px-5 py-2 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
              >
                Done — I&apos;ve saved these
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Disable 2FA Modal ─────────────────────────────────────────────── */}
      {showDisable2FA && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
              <h3 className="font-semibold text-gray-900">Disable 2FA</h3>
              <button
                onClick={() => { setShowDisable2FA(false); setDisableCode(""); setDisableError(""); }}
                className="text-gray-400 hover:text-gray-600 transition-colors"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <form onSubmit={handleDisable2FA} className="px-5 py-4 space-y-3">
              <p className="text-sm text-gray-600">
                Enter your current authenticator code to confirm you want to disable two-factor authentication.
              </p>
              <div>
                <label className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  Authenticator Code
                </label>
                <input
                  type="text"
                  inputMode="numeric"
                  value={disableCode}
                  onChange={e => setDisableCode(e.target.value.replace(/\D/g, ""))}
                  required
                  maxLength={6}
                  autoFocus
                  autoComplete="one-time-code"
                  placeholder="000000"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-center font-mono text-lg tracking-widest text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-300 placeholder:font-sans placeholder:text-sm placeholder:tracking-normal"
                />
              </div>
              {disableError && (
                <p className="text-xs text-red-600 flex items-center gap-1">
                  <span>⚠</span> {disableError}
                </p>
              )}
              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => { setShowDisable2FA(false); setDisableCode(""); setDisableError(""); }}
                  className="rounded-lg px-4 py-2 text-sm text-gray-500 hover:bg-gray-100 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={disabling2FA || disableCode.length !== 6}
                  className="rounded-xl bg-red-600 px-5 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                >
                  {disabling2FA ? "Disabling…" : "Disable 2FA"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
