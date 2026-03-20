"use client";

import React from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import { logout } from "@/lib/auth";
import { usePresence } from "@/hooks/usePresence";
import MessageSearch from "@/components/MessageSearch";

// ── Types ──────────────────────────────────────────────────────────────────
interface User    { id: string; username: string; roles: string[]; display_name?: string | null }
interface Conv    { id: string; title: string; updated_at: string }
interface Channel { id: string; name: string; type: string; created_by: string | null; last_message_at: string | null; team_id?: string | null; member_count?: number; unread_count?: number; dm_partner_id?: string | null; dm_partner_username?: string | null }
interface Team    { id: string; name: string; member_count: number }
interface OrgUser { id: string; username: string; email: string }
interface CalEvent { id: string; title: string; start_time: string; end_time: string; attendees: { user_id: string; status: string }[] }
interface Props   { onClose?: () => void }

// ── Theme ──────────────────────────────────────────────────────────────────
const SB = "#ffffff";
const HV = "rgba(0,0,0,0.05)";
const AC = "rgba(0,0,0,0.09)";
const AT = "#000000";
const MT = "#111827";
const SL = "#6b7280";
const DV = "rgba(0,0,0,0.08)";

type Section = "chat" | "dms" | "channels" | "workspace" | "calendar" | "admin";

function sectionFromPath(p: string): Section {
  if (p === "/" || p.startsWith("/?")) return "chat";
  if (p.startsWith("/chat"))        return "dms";
  if (p.startsWith("/teams"))       return "channels";
  if (p.startsWith("/admin"))       return "admin";
  if (p.startsWith("/calendar"))    return "calendar";
  if (["/documents", "/collections", "/shared"].some(r => p.startsWith(r)))
    return "workspace";
  return "chat";
}

// ── Helpers ────────────────────────────────────────────────────────────────
function Ico({ d, d2 }: { d: string; d2?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 shrink-0">
      <path d={d} />{d2 && <path d={d2} />}
    </svg>
  );
}

function Item({ active, onClick, children }: {
  active?: boolean; onClick?: () => void; children: React.ReactNode;
}) {
  const [hov, setHov] = useState(false);
  return (
    <button onClick={onClick}
      className="flex w-full items-center gap-2.5 rounded-md px-3 py-2.5 text-left text-sm transition-all"
      style={{
        backgroundColor: active ? AC : hov ? HV : "transparent",
        color: active ? AT : MT,
        fontWeight: active ? 600 : 400,
      }}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}>
      {children}
    </button>
  );
}

function PlusBtn({ onClick, title }: { onClick: () => void; title: string }) {
  const [hov, setHov] = useState(false);
  return (
    <button onClick={onClick} title={title} className="rounded p-1 transition-colors"
      style={{ color: hov ? MT : SL }}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
        strokeLinecap="round" className="w-3.5 h-3.5">
        <path d="M12 5v14M5 12h14" />
      </svg>
    </button>
  );
}

// ── Icon Rail item ─────────────────────────────────────────────────────────
function RailItem({ href, d, d2, label, active, onClick, badge }: {
  href: string; d: string; d2?: string; label: string; active: boolean; onClick?: () => void;
  badge?: number;
}) {
  const [hov, setHov] = useState(false);
  return (
    <Link href={href} onClick={onClick} title={label}
      className="relative flex flex-col items-center justify-center gap-1 w-11 py-2 rounded-xl transition-colors"
      style={{
        backgroundColor: active ? "rgba(0,0,0,0.88)" : hov ? HV : "transparent",
        color: active ? "#fff" : hov ? MT : SL,
      }}
      onMouseEnter={() => setHov(true)} onMouseLeave={() => setHov(false)}>
      <div className="relative">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
          strokeLinecap="round" strokeLinejoin="round" className="w-[17px] h-[17px] shrink-0">
          <path d={d} />{d2 && <path d={d2} />}
        </svg>
        {!!badge && badge > 0 && (
          <span className="absolute -top-1.5 -right-2 flex h-[14px] min-w-[14px] items-center justify-center rounded-full bg-red-500 px-[3px] text-[8px] font-bold text-white leading-none">
            {badge > 99 ? "99+" : badge}
          </span>
        )}
      </div>
      <span className="text-[9px] font-medium leading-none">{label}</span>
    </Link>
  );
}

function relTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "now";
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

const MESSAGING_ENABLED = process.env.NEXT_PUBLIC_ENABLE_MESSAGING !== "false";

// ── Presence dot ───────────────────────────────────────────────────────────
function PresenceDot({ status }: { status: "online" | "away" | "dnd" | "offline" }) {
  const color =
    status === "online" ? "#10b981" :
    status === "away"   ? "#facc15" :
    status === "dnd"    ? "#facc15" :
                          "#d1d5db";
  return (
    <span className="absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full border border-white"
      style={{ backgroundColor: color }} />
  );
}

// ── Main component ─────────────────────────────────────────────────────────
export default function AppSidebar({ onClose }: Props) {
  const pathname     = usePathname();
  const router       = useRouter();
  const searchParams = useSearchParams();
  const { getStatus, getCustomStatus } = usePresence();

  const [activeConvId, setActiveConvId] = useState<string | null>(() => searchParams.get("conv"));
  const [mounted,  setMounted]  = useState(false);
  const [user,     setUser]     = useState<User | null>(null);
  const [convs,    setConvs]    = useState<Conv[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [teams,    setTeams]    = useState<Team[]>([]);
  const [orgUsers,   setOrgUsers]   = useState<OrgUser[]>([]);
  const [calEvents,  setCalEvents]  = useState<CalEvent[]>([]);

  const [dmPickerOpen, setDmPickerOpen] = useState(false);
  const [dmSearch,     setDmSearch]     = useState("");
  const [dmSelectedIds, setDmSelectedIds] = useState<string[]>([]);
  const [dmGroupName,   setDmGroupName]   = useState("");

  // Create channel modal
  const [chModalOpen,  setChModalOpen]  = useState(false);
  const [chName,       setChName]       = useState("");
  const [chDesc,       setChDesc]       = useState("");
  const [chMemberSearch, setChMemberSearch] = useState("");
  const [chSelectedIds,  setChSelectedIds]  = useState<string[]>([]);
  const [chCreating,   setChCreating]   = useState(false);
  const [chError,      setChError]      = useState("");

  // Channel context menu ("...")
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [menuPos,    setMenuPos]    = useState<{ top: number; right: number } | null>(null);
  const [mutedChannels, setMutedChannels] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set();
    try { return new Set(JSON.parse(localStorage.getItem("nexus_muted_channels") ?? "[]")); }
    catch { return new Set(); }
  });
  const [dismissedCalIds, setDismissedCalIds] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set();
    try { return new Set(JSON.parse(localStorage.getItem("nexus_dismissed_cal") ?? "[]")); }
    catch { return new Set(); }
  });

  // Feature 5: Message search
  const [showMsgSearch, setShowMsgSearch] = useState(false);

  // Feature 4: User status popover
  const [showStatusPopover, setShowStatusPopover] = useState(false);
  const [statusDraft, setStatusDraft]   = useState("");
  const [statusSaving, setStatusSaving] = useState(false);
  const statusPopoverRef = useRef<HTMLDivElement>(null);

  // Derive active section from pathname + channel param.
  // If we land on /chat?channel=X where X is a public (non-DM) channel,
  // keep the section as "teams" so the channel list stays visible.
  const channelParam = searchParams.get("channel");
  const section: Section = useMemo(() => {
    const base = sectionFromPath(pathname);
    if (base === "dms" && channelParam) {
      const ch = channels.find(c => c.id === channelParam);
      if (ch && ch.type !== "dm" && ch.type !== "group") return "channels";
    }
    return base;
  }, [pathname, channelParam, channels]);

  useEffect(() => { setMounted(true); }, []);

  const fetchChannels = useCallback(() => {
    if (!MESSAGING_ENABLED) return;
    api.get<Channel[]>("/api/v1/chat/channels").then(setChannels).catch(() => {});
  }, []);

  useEffect(() => {
    const requests: Promise<unknown>[] = [
      api.get<User>("/api/v1/auth/me"),
      api.get<Conv[]>("/api/v1/conversations"),
      api.get<Team[]>("/api/v1/teams"),
    ];
    if (MESSAGING_ENABLED) {
      requests.push(
        api.get<Channel[]>("/api/v1/chat/channels"),
        api.get<OrgUser[]>("/api/v1/admin/users/search"),
      );
    }
    Promise.all(requests).then((results) => {
      const [u, cs, ts, chs, users] = results as [User, Conv[], Team[], Channel[] | undefined, OrgUser[] | undefined];
      setUser(u);
      setConvs(cs);
      setTeams(ts);
      if (chs) setChannels(chs);
      if (users) setOrgUsers(users.filter(ou => ou.id !== u.id));
    }).catch(() => {});
    // Fetch calendar events independently so a failure doesn't block the rest
    api.get<CalEvent[]>("/api/v1/calendar/events").then(setCalEvents).catch(() => {});
  }, []);

  useEffect(() => {
    if (!MESSAGING_ENABLED) return;
    window.addEventListener("focus", fetchChannels);
    // Immediately refresh when a new DM notification arrives (pushed by NotificationBell)
    window.addEventListener("chat:new-message", fetchChannels as EventListener);
    // Poll every 30 s so unread counts and new DMs appear without a page reload
    const timer = setInterval(fetchChannels, 30_000);
    return () => {
      window.removeEventListener("focus", fetchChannels);
      window.removeEventListener("chat:new-message", fetchChannels as EventListener);
      clearInterval(timer);
    };
  }, [fetchChannels]);

  // Channels keyed by partner id — still used by the DM picker to detect existing DMs
  const dmMap = useMemo(() => {
    const map = new Map<string, Channel>();
    channels.filter(c => c.type === "dm").forEach(ch => {
      if (ch.dm_partner_id) {
        map.set(ch.dm_partner_id, ch);
      } else {
        // Fallback: parse name for channels fetched before backend upgrade
        const parts = ch.name.split(":");
        const otherId = parts.find(p => p !== "dm" && p !== user?.id);
        if (otherId) map.set(otherId, ch);
      }
    });
    return map;
  }, [channels, user?.id]);

  const groupDmChannels = useMemo(() =>
    channels.filter(c => c.type === "group")
      .sort((a, b) => (b.last_message_at ?? "").localeCompare(a.last_message_at ?? "")),
    [channels]);

  const publicChannels = useMemo(() =>
    channels.filter(c => c.type !== "dm" && c.type !== "group")
      .sort((a, b) => (b.last_message_at ?? "").localeCompare(a.last_message_at ?? "")),
    [channels]);

  // Render 1:1 DMs directly from the channel list — no orgUsers dependency.
  // Newly created DMs (last_message_at == null) sort to top via "9999-12-31" sentinel.
  const sortedDmChannels = useMemo(() =>
    channels
      .filter(c => c.type === "dm")
      .sort((a, b) => {
        const at = a.last_message_at ?? "0000-01-01";
        const bt = b.last_message_at ?? "0000-01-01";
        return bt.localeCompare(at);
      }),
    [channels]);

  const isAdmin = user?.roles.includes("admin") ?? false;

  // Total unread messages across all DM + group channels
  const totalDmUnread = useMemo(() =>
    channels
      .filter(c => c.type === "dm" || c.type === "group")
      .reduce((sum, c) => sum + (c.unread_count ?? 0), 0),
    [channels]);

  // Events starting within 5 min + pending RSVPs — cleared once user clicks Cal
  const calBadge = useMemo(() => {
    const now = Date.now();
    const in5min = now + 5 * 60 * 1000;
    return calEvents.filter(e => {
      if (dismissedCalIds.has(e.id)) return false;
      const start = new Date(e.start_time).getTime();
      const upcoming = start >= now && start <= in5min;
      const pendingRsvp = e.attendees.some(a => a.user_id === user?.id && a.status === "pending");
      return upcoming || pendingRsvp;
    }).length;
  }, [calEvents, user?.id, dismissedCalIds]);

  useEffect(() => {
    setActiveConvId(searchParams.get("conv"));
  }, [searchParams]);

  // Immediately clear unread count for whichever channel the user just opened
  useEffect(() => {
    if (!channelParam) return;
    setChannels(prev => prev.map(c => c.id === channelParam ? { ...c, unread_count: 0 } : c));
  }, [channelParam]);

  function nav(href: string) {
    onClose?.();
    const convId = new URLSearchParams(href.split("?")[1] ?? "").get("conv");
    setActiveConvId(convId);
    router.push(href);
  }
  function isActive(href: string, exact = false) {
    if (href === "/") return pathname === "/";
    if (exact) return pathname === href;
    return pathname === href || pathname.startsWith(href + "/");
  }

  async function newConv() {
    try {
      const c = await api.post<Conv>("/api/v1/conversations", { title: "New conversation" });
      setConvs(prev => [c, ...prev]);
      nav(`/?conv=${c.id}`);
    } catch { /* ignore */ }
  }

  async function deleteConv(id: string) {
    try {
      await api.delete(`/api/v1/conversations/${id}`);
      setConvs(prev => prev.filter(c => c.id !== id));
    } catch { /* ignore */ }
  }

  async function deleteChannel(id: string) {
    try {
      await api.delete(`/api/v1/chat/channels/${id}`);
      setChannels(prev => prev.filter(c => c.id !== id));
    } catch { /* ignore */ }
  }

  // Close context menu when clicking outside
  useEffect(() => {
    if (!openMenuId) return;
    function handleOutside(e: MouseEvent) {
      if (!(e.target as Element).closest("[data-ch-menu]")) setOpenMenuId(null);
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [openMenuId]);

  function openMenu(e: React.MouseEvent, channelId: string) {
    e.stopPropagation();
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenuPos({ top: rect.bottom + 6, right: window.innerWidth - rect.right });
    setOpenMenuId(prev => (prev === channelId ? null : channelId));
  }

  function markRead(channelId: string) {
    api.post(`/api/v1/chat/channels/${channelId}/read`, {}).catch(() => {});
    setChannels(prev => prev.map(c => c.id === channelId ? { ...c, unread_count: 0 } : c));
    setOpenMenuId(null);
  }

  function toggleMute(channelId: string) {
    setMutedChannels(prev => {
      const next = new Set(prev);
      if (next.has(channelId)) next.delete(channelId); else next.add(channelId);
      try { localStorage.setItem("nexus_muted_channels", JSON.stringify(Array.from(next))); } catch { /**/ }
      return next;
    });
    setOpenMenuId(null);
  }

  async function leaveChannel(channelId: string) {
    if (!user) return;
    try {
      await api.delete(`/api/v1/chat/channels/${channelId}/members/${user.id}`);
      setChannels(prev => prev.filter(c => c.id !== channelId));
    } catch { /* ignore */ }
    setOpenMenuId(null);
  }

  function markAllRead() {
    const unread = channels.filter(c =>
      (c.type === "dm" || c.type === "group") && (c.unread_count ?? 0) > 0
    );
    unread.forEach(c => api.post(`/api/v1/chat/channels/${c.id}/read`, {}).catch(() => {}));
    setChannels(prev => prev.map(c =>
      (c.type === "dm" || c.type === "group") ? { ...c, unread_count: 0 } : c
    ));
  }

  const allDmsMuted = useMemo(() => {
    const dmGroupIds = channels
      .filter(c => c.type === "dm" || c.type === "group")
      .map(c => c.id);
    return dmGroupIds.length > 0 && dmGroupIds.every(id => mutedChannels.has(id));
  }, [channels, mutedChannels]);

  function toggleMuteAll() {
    const dmGroupIds = channels
      .filter(c => c.type === "dm" || c.type === "group")
      .map(c => c.id);
    setMutedChannels(prev => {
      const next = new Set(prev);
      if (allDmsMuted) {
        dmGroupIds.forEach(id => next.delete(id));
      } else {
        dmGroupIds.forEach(id => next.add(id));
      }
      try { localStorage.setItem("nexus_muted_channels", JSON.stringify(Array.from(next))); } catch { /**/ }
      return next;
    });
  }

  function dismissCalBadge() {
    const now = Date.now();
    const in5min = now + 5 * 60 * 1000;
    const ids = calEvents
      .filter(e => {
        const start = new Date(e.start_time).getTime();
        const upcoming = start >= now && start <= in5min;
        const pending = e.attendees.some(a => a.user_id === user?.id && a.status === "pending");
        return upcoming || pending;
      })
      .map(e => e.id);
    if (ids.length > 0) setDismissedCalIds(prev => {
      const next = new Set([...Array.from(prev), ...ids]);
      try { localStorage.setItem("nexus_dismissed_cal", JSON.stringify(Array.from(next))); } catch { /**/ }
      return next;
    });
  }

  // Feature 4: close status popover on outside click
  useEffect(() => {
    if (!showStatusPopover) return;
    function handler(e: MouseEvent) {
      if (statusPopoverRef.current && !statusPopoverRef.current.contains(e.target as Node)) {
        setShowStatusPopover(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showStatusPopover]);

  async function saveCustomStatus() {
    setStatusSaving(true);
    try {
      await api.patch("/api/v1/auth/status", { custom_status: statusDraft });
      setShowStatusPopover(false);
    } catch { /* ignore */ } finally { setStatusSaving(false); }
  }

  async function setAvailability(status: "online" | "away" | "dnd") {
    try {
      await api.patch("/api/v1/auth/status", { status });
    } catch { /* ignore */ }
    setShowStatusPopover(false);
  }

  async function startDmFromPicker() {
    if (dmSelectedIds.length === 0) return;
    setDmPickerOpen(false);
    const selected = orgUsers.filter(u => dmSelectedIds.includes(u.id));
    try {
      if (dmSelectedIds.length === 1) {
        const target = selected[0];
        const existing = dmMap.get(target.id);
        if (existing) { nav(`/chat?channel=${existing.id}`); setDmSelectedIds([]); return; }
        const ch = await api.post<Channel>("/api/v1/chat/channels/dm", {
          target_user_id: target.id, target_username: target.username,
        });
        setChannels(prev => prev.some(c => c.id === ch.id) ? prev : [ch, ...prev]);
        nav(`/chat?channel=${ch.id}`);
        // Sync with server so the sidebar reflects the canonical channel object
        fetchChannels();
      } else {
        // Group DM — use custom name or fall back to member names
        const fallback = selected.map(u => u.username).join(", ");
        const name = dmGroupName.trim() || fallback;
        const ch = await api.post<Channel>("/api/v1/chat/channels", {
          name,
          type: "group",
          member_ids: dmSelectedIds,
        });
        setChannels(prev => prev.some(c => c.id === ch.id) ? prev : [ch, ...prev]);
        nav(`/chat?channel=${ch.id}`);
      }
    } catch { /* ignore */ }
    setDmSelectedIds([]);
    setDmGroupName("");
  }

  async function openTeamChannel(team: Team) {
    // Find existing channel for this team
    let ch = channels.find(c => c.team_id === team.id);
    if (!ch) {
      // Create the team channel on the fly
      try {
        ch = await api.post<Channel>("/api/v1/chat/channels", {
          name: team.name.toLowerCase().replace(/\s+/g, "-"),
          type: "public",
          team_id: team.id,
        });
        setChannels(prev => prev.some(c => c.id === ch!.id) ? prev : [ch!, ...prev]);
      } catch {
        // Fallback to team page if channel creation fails
        nav(`/teams?team=${team.id}`);
        return;
      }
    }
    nav(`/chat?channel=${ch.id}`);
  }

  async function createChannel(e: React.FormEvent) {
    e.preventDefault();
    if (!chName.trim()) return;
    setChCreating(true); setChError("");
    try {
      const ch = await api.post<Channel>("/api/v1/chat/channels", {
        name: chName.trim().toLowerCase().replace(/\s+/g, "-"),
        type: "public",
        member_ids: chSelectedIds,
      });
      setChannels(prev => prev.some(c => c.id === ch.id) ? prev : [ch, ...prev]);
      setChModalOpen(false);
      nav(`/chat?channel=${ch.id}`);
    } catch (err) {
      setChError(err instanceof Error ? err.message : "Failed to create channel");
    } finally { setChCreating(false); }
  }

  const chMemberSuggestions = chMemberSearch.length > 0
    ? orgUsers.filter(u =>
        !chSelectedIds.includes(u.id) &&
        (u.username.toLowerCase().includes(chMemberSearch.toLowerCase()) ||
         u.email.toLowerCase().includes(chMemberSearch.toLowerCase()))
      )
    : [];

  const initials = user
    ? (user.username.split(".").map(p => p[0]?.toUpperCase() ?? "").join("").slice(0, 2) || user.username[0]?.toUpperCase() || "U")
    : "U";

  // Section header title + optional action button
  const SECTION_META: Record<Section, { label: string; action?: React.ReactNode }> = {
    chat:      { label: "Chat",            action: <PlusBtn onClick={newConv} title="New chat" /> },
    dms:       { label: "Direct Messages", action: (
      <div className="flex items-center gap-0.5">
        {/* Mute / unmute all */}
        <button onClick={toggleMuteAll} title={allDmsMuted ? "Unmute all notifications" : "Mute all notifications"}
          className="rounded p-1 transition-colors text-gray-400 hover:text-gray-700">
          {allDmsMuted ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
              <path d="M18.63 13A17.9 17.9 0 0 1 18 8" />
              <path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14" />
              <line x1="22" y1="2" x2="2" y2="22" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.73 21a2 2 0 0 1-3.46 0" />
            </svg>
          )}
        </button>
        {/* New message */}
        <PlusBtn onClick={() => { setDmSearch(""); setDmPickerOpen(true); }} title="New message" />
      </div>
    ) },
    channels:  { label: "Channels",        action: <PlusBtn onClick={() => { setChName(""); setChDesc(""); setChMemberSearch(""); setChSelectedIds([]); setChError(""); setChModalOpen(true); }} title="New channel" />},
    workspace: { label: "Workspace" },
    calendar:  { label: "Calendar" },
    admin:     { label: "Admin" },
  };
  const { label: sectionLabel, action: sectionAction } = SECTION_META[section];

  return (
    <>
    {/* DM picker modal — supports 1:1 and group (up to 4 members) */}
    {mounted && MESSAGING_ENABLED && dmPickerOpen && createPortal(
      <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4">
        <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl flex flex-col" style={{ maxHeight: "75vh" }}>
          <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4 shrink-0">
            <h3 className="text-sm font-semibold text-gray-900">New Message</h3>
            <button onClick={() => { setDmPickerOpen(false); setDmSelectedIds([]); setDmSearch(""); setDmGroupName(""); }}
              className="text-gray-400 hover:text-gray-700 text-lg leading-none">✕</button>
          </div>

          {/* Selected chips */}
          {dmSelectedIds.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-4 pt-3 shrink-0">
              {dmSelectedIds.map(id => {
                const u = orgUsers.find(o => o.id === id);
                if (!u) return null;
                return (
                  <span key={id} className="flex items-center gap-1 rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-medium text-indigo-700">
                    {u.username}
                    <button type="button" onClick={() => setDmSelectedIds(prev => prev.filter(x => x !== id))}
                      className="ml-0.5 text-indigo-400 hover:text-indigo-700 leading-none">×</button>
                  </span>
                );
              })}
            </div>
          )}

          {/* Group name — shown when 2+ people selected */}
          {dmSelectedIds.length >= 2 && (
            <div className="px-4 pt-3 shrink-0">
              <input
                type="text"
                value={dmGroupName}
                onChange={e => setDmGroupName(e.target.value)}
                placeholder={`Group name (optional)`}
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
              />
            </div>
          )}

          <div className="px-4 pt-3 shrink-0">
            <input autoFocus type="search" value={dmSearch} onChange={e => setDmSearch(e.target.value)}
              placeholder={dmSelectedIds.length === 0 ? "Search people…" : "Add more people…"}
              className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-gray-500"
              disabled={dmSelectedIds.length >= 3}
            />
            {dmSelectedIds.length >= 3 && (
              <p className="mt-1 text-[11px] text-gray-400">Max 4 people per group (including you)</p>
            )}
          </div>

          <ul className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
            {(() => {
              const filtered = (dmSearch
                ? orgUsers.filter(u => u.username.toLowerCase().includes(dmSearch.toLowerCase()) || u.email.toLowerCase().includes(dmSearch.toLowerCase()))
                : orgUsers
              ).filter(u => !dmSelectedIds.includes(u.id));
              return filtered.length === 0
                ? <p className="px-3 py-4 text-center text-sm text-gray-400">No users found</p>
                : filtered.map(u => (
                  <li key={u.id}>
                    <button onClick={() => { setDmSelectedIds(prev => [...prev, u.id]); setDmSearch(""); }}
                      className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left hover:bg-gray-50 transition-colors">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-900 text-white text-xs font-bold uppercase">
                        {u.username[0]}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{u.username}</p>
                        <p className="text-xs text-gray-400 truncate">{u.email}</p>
                      </div>
                      {dmMap.has(u.id) && dmSelectedIds.length === 0 && (
                        <span className="shrink-0 text-[10px] text-gray-400">existing</span>
                      )}
                    </button>
                  </li>
                ));
            })()}
          </ul>

          <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-4 shrink-0">
            <button type="button" onClick={() => { setDmPickerOpen(false); setDmSelectedIds([]); setDmSearch(""); setDmGroupName(""); }}
              className="rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-100">Cancel</button>
            <button type="button" onClick={startDmFromPicker} disabled={dmSelectedIds.length === 0}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
              {dmSelectedIds.length > 1 ? "Create group" : "Open DM"}
            </button>
          </div>
        </div>
      </div>
    , document.body)}

    {/* Create channel modal */}
    {mounted && MESSAGING_ENABLED && chModalOpen && createPortal(
      <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 p-4">
        <div className="w-full max-w-sm rounded-2xl bg-white shadow-2xl flex flex-col" style={{ maxHeight: "80vh" }}>
          <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4 shrink-0">
            <h3 className="text-sm font-semibold text-gray-900">New Channel</h3>
            <button onClick={() => setChModalOpen(false)} className="text-gray-400 hover:text-gray-700 text-lg leading-none">✕</button>
          </div>
          <form onSubmit={createChannel} className="flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Channel name</label>
                <div className="flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-2 focus-within:border-indigo-500 focus-within:ring-2 focus-within:ring-indigo-100">
                  <span className="text-gray-400 font-medium text-sm">#</span>
                  <input autoFocus type="text" value={chName} onChange={e => setChName(e.target.value)} required
                    placeholder="e.g. general"
                    className="flex-1 text-sm outline-none bg-transparent" />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Description (optional)</label>
                <input type="text" value={chDesc} onChange={e => setChDesc(e.target.value)}
                  placeholder="What's this channel about?"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-600">Add members (optional)</label>
                <input type="search" placeholder="Search by name or email…" value={chMemberSearch}
                  onChange={e => setChMemberSearch(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100" />
                {chMemberSuggestions.length > 0 && (
                  <ul className="mt-1 max-h-40 overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-sm">
                    {chMemberSuggestions.map(u => (
                      <li key={u.id}>
                        <button type="button"
                          onClick={() => { setChSelectedIds(prev => [...prev, u.id]); setChMemberSearch(""); }}
                          className="flex w-full items-center gap-2.5 px-3 py-2.5 hover:bg-gray-50 text-left">
                          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-white text-[10px] font-bold uppercase">{u.username[0]}</span>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-gray-900 truncate">{u.username}</p>
                            <p className="text-xs text-gray-400 truncate">{u.email}</p>
                          </div>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {chSelectedIds.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {chSelectedIds.map(id => {
                      const u = orgUsers.find(o => o.id === id);
                      if (!u) return null;
                      return (
                        <span key={id} className="flex items-center gap-1 rounded-full bg-indigo-100 px-2.5 py-1 text-xs font-medium text-indigo-700">
                          {u.username}
                          <button type="button" onClick={() => setChSelectedIds(prev => prev.filter(x => x !== id))}
                            className="ml-0.5 text-indigo-400 hover:text-indigo-700 leading-none">×</button>
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
              {chError && <p className="text-sm text-red-600">{chError}</p>}
            </div>
            <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-4 shrink-0">
              <button type="button" onClick={() => setChModalOpen(false)}
                className="rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-100">Cancel</button>
              <button type="submit" disabled={chCreating || !chName.trim()}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
                {chCreating ? "Creating…" : "Create channel"}
              </button>
            </div>
          </form>
        </div>
      </div>
    , document.body)}

    {/* ── Channel context menu ── */}
    {mounted && openMenuId && menuPos && createPortal(
      <div data-ch-menu
        className="fixed z-[300] min-w-[192px] rounded-xl border border-gray-100 bg-white shadow-xl py-1 text-[13px]"
        style={{ top: menuPos.top, right: menuPos.right }}>
        {/* Mark as read */}
        <button onClick={() => markRead(openMenuId)}
          className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-gray-700 hover:bg-gray-50">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-4 h-4 shrink-0 text-gray-400">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          Mark as read
        </button>
        {/* Mute / Unmute */}
        <button onClick={() => toggleMute(openMenuId)}
          className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-gray-700 hover:bg-gray-50">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-4 h-4 shrink-0 text-gray-400">
            {mutedChannels.has(openMenuId)
              ? <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 9.75L19.5 12m0 0l2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
              : <path strokeLinecap="round" strokeLinejoin="round" d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z" />
            }
          </svg>
          {mutedChannels.has(openMenuId) ? "Unmute notifications" : "Mute notifications"}
        </button>

        <div className="my-1 h-px bg-gray-100" />

        {/* Leave / Delete */}
        {(() => {
          const ch = channels.find(c => c.id === openMenuId);
          if (!ch) return null;
          const isOwnerOrAdmin = ch.created_by === user?.id || (user?.roles?.includes("admin") ?? false);
          if (ch.type === "dm") {
            return (
              <button onClick={() => leaveChannel(ch.id)}
                className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-red-500 hover:bg-red-50">
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-4 h-4 shrink-0">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
                </svg>
                Close conversation
              </button>
            );
          }
          if (isOwnerOrAdmin) {
            return (
              <button
                onClick={() => { if (confirm(`Delete "${ch.name}"?`)) { deleteChannel(ch.id); setOpenMenuId(null); } }}
                className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-red-500 hover:bg-red-50">
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-4 h-4 shrink-0">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                </svg>
                Delete {ch.type === "group" ? "group" : "channel"}
              </button>
            );
          }
          return (
            <button onClick={() => leaveChannel(ch.id)}
              className="flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-red-500 hover:bg-red-50">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-4 h-4 shrink-0">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
              </svg>
              Leave {ch.type === "group" ? "group" : "channel"}
            </button>
          );
        })()}
      </div>
    , document.body)}

    <aside className="flex h-full w-full flex-shrink-0 flex-row border-r border-gray-200" style={{ backgroundColor: SB }}>

      {/* ── Icon Rail (desktop only) ───────────────────────── */}
      <nav className="hidden md:flex flex-col w-14 shrink-0 items-center py-3 gap-1.5 overflow-y-auto"
        style={{ borderRight: `1px solid ${DV}` }}>

        {/* Nexus logo */}
        <div className="mb-2 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-black">
          <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4">
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
          </svg>
        </div>

        {/* Admin — TOP (admin-only) */}
        {isAdmin && (
          <RailItem
            href="/admin"
            d="M12 15a3 3 0 100-6 3 3 0 000 6z"
            d2="M19.07 4.93l-1.41 1.41M4.93 4.93l1.41 1.41M19.07 19.07l-1.41-1.41M4.93 19.07l1.41-1.41M12 2v2M12 20v2M2 12h2M20 12h2"
            label="Admin"
            active={section === "admin"}
            onClick={() => onClose?.()}
          />
        )}

        {/* Separator */}
        <div className="w-8 my-0.5 shrink-0" style={{ height: 1, backgroundColor: DV }} />

        {/* Primary nav */}
        <RailItem href="/" d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" label="Chat"
          active={section === "chat"} onClick={() => onClose?.()} />
        {MESSAGING_ENABLED && (
          <RailItem href="/chat" d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"
            label="DMs" active={section === "dms"} onClick={() => onClose?.()}
            badge={totalDmUnread} />
        )}
        <RailItem href="/teams"
          d="M4 9h16M4 15h16M10 3v18M16 3v18"
          label="Channels" active={section === "channels"} onClick={() => onClose?.()} />

        {/* Separator */}
        <div className="w-8 my-0.5 shrink-0" style={{ height: 1, backgroundColor: DV }} />

        {/* Workspace tools */}
        <RailItem href="/documents"
          d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" d2="M14 2v6h6M8 13h8M8 17h5"
          label="Docs" active={section === "workspace"} onClick={() => onClose?.()} />

        {/* Separator before Calendar */}
        {/* <div className="w-8 my-0.5 shrink-0" style={{ height: 1, backgroundColor: DV }} /> */}

        {/* <RailItem href="/calendar"
          d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z"
          label="Cal" active={section === "calendar"}
          onClick={() => { onClose?.(); dismissCalBadge(); }}
          badge={calBadge} /> */}

        {/* Push profile + sign-out to bottom */}
        <div className="flex-1" />

        {user && (
          <div className="relative" ref={statusPopoverRef}>
            <button
              onClick={() => router.push("/profile")}
              className="relative flex h-8 w-8 items-center justify-center rounded-full bg-black text-white text-[11px] font-bold uppercase transition-opacity hover:opacity-75">
              {initials}
              <PresenceDot status={getStatus(user.id)} />
            </button>
            {showStatusPopover && (
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-[400] w-64 rounded-xl border border-gray-200 bg-white shadow-2xl overflow-hidden">
                {/* User info header */}
                <div className="flex items-center gap-2.5 border-b border-gray-100 px-4 py-3">
                  <div className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-black text-white text-sm font-bold uppercase">
                    {initials}
                    <PresenceDot status={getStatus(user.id)} />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-900 truncate">{user.display_name || user.username}</p>
                    {getCustomStatus(user.id) && (
                      <p className="text-xs text-gray-500 truncate">{getCustomStatus(user.id)}</p>
                    )}
                  </div>
                </div>
                {/* Set custom status */}
                <div className="px-4 py-3 border-b border-gray-100">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">Set status</p>
                  <div className="flex gap-1.5">
                    <input
                      type="text"
                      value={statusDraft}
                      onChange={e => setStatusDraft(e.target.value)}
                      onKeyDown={e => { if (e.key === "Enter") saveCustomStatus(); if (e.key === "Escape") setShowStatusPopover(false); }}
                      placeholder="What's your status?"
                      className="flex-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100"
                    />
                    <button onClick={saveCustomStatus} disabled={statusSaving}
                      className="rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors">
                      {statusSaving ? "…" : "Set"}
                    </button>
                  </div>
                </div>
                {/* Availability */}
                <div className="px-4 py-3 border-b border-gray-100">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">Availability</p>
                  <div className="flex gap-1.5">
                    {(["online", "away", "dnd"] as const).map(s => {
                      const colors: Record<string, string> = { online: "#10b981", away: "#facc15", dnd: "#ef4444" };
                      const labels: Record<string, string> = { online: "Online", away: "Away", dnd: "DND" };
                      const current = getStatus(user.id);
                      return (
                        <button key={s} onClick={() => setAvailability(s)}
                          className={`flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                            current === s
                              ? "border-indigo-300 bg-indigo-50 text-indigo-700 font-medium"
                              : "border-gray-200 text-gray-600 hover:bg-gray-50"
                          }`}>
                          <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: colors[s] }} />
                          {labels[s]}
                        </button>
                      );
                    })}
                  </div>
                </div>
                {/* Sign out */}
                <button
                  onClick={() => { if (confirm("Sign out of Nexus?")) logout(); }}
                  className="flex w-full items-center gap-2 px-4 py-3 text-sm text-red-500 hover:bg-red-50 transition-colors">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                    strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 shrink-0">
                    <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
                  </svg>
                  Sign out
                </button>
              </div>
            )}
          </div>
        )}

        {/* Sign out — in rail */}
        <button
          onClick={() => { if (confirm("Sign out of Nexus?")) logout(); }}
          title="Sign out"
          className="mb-1 mt-0.5 flex h-8 w-8 items-center justify-center rounded-xl transition-colors hover:bg-gray-100"
          style={{ color: SL }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
            strokeLinecap="round" strokeLinejoin="round" className="w-[17px] h-[17px]">
            <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
          </svg>
        </button>
      </nav>

      {/* ── Content Panel ──────────────────────────────────── */}
      <div className="flex flex-1 min-w-0 flex-col overflow-hidden">

        {/* Section header */}
        <div className="flex items-center justify-between px-4 py-3.5 shrink-0"
          style={{ borderBottom: `1px solid ${DV}` }}>
          <div className="flex items-center gap-2">
            {/* Nexus logo — mobile only */}
            <div className="md:hidden flex h-6 w-6 items-center justify-center rounded-md bg-black">
              <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="w-3.5 h-3.5">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <span className="text-sm font-semibold" style={{ color: MT }}>{sectionLabel}</span>
          </div>
          <div className="flex items-center gap-1">
            {sectionAction}
            {onClose && (
              <button onClick={onClose} className="rounded p-1 md:hidden" style={{ color: SL }}>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* Section content */}
        <div className="flex-1 overflow-y-auto px-2 py-2">

          {/* ── CHAT ── */}
          {section === "chat" && (
            <div className="space-y-0.5">
              {convs.length === 0
                ? <p className="px-3 py-2 text-[12px]" style={{ color: SL }}>No conversations yet — press + to start one</p>
                : convs.slice(0, 30).map(c => {
                    const active = pathname === "/" && activeConvId === c.id;
                    return (
                      <div key={c.id} className="group relative">
                        <Item active={active} onClick={() => nav(`/?conv=${c.id}`)}>
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
                            strokeLinecap="round" className="w-3.5 h-3.5 shrink-0" style={{ color: active ? AT : SL }}>
                            <path d="M8 10h8M8 14h5M5 3h14a2 2 0 012 2v11a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
                          </svg>
                          <span className="truncate flex-1 text-[13px]">{c.title}</span>
                          <span className="shrink-0 text-[10px] group-hover:hidden" style={{ color: SL }}>{relTime(c.updated_at)}</span>
                          <button
                            onClick={e => { e.stopPropagation(); deleteConv(c.id); }}
                            className="hidden group-hover:flex shrink-0 h-4 w-4 items-center justify-center rounded hover:bg-red-100 text-slate-400 hover:text-red-500 text-xs leading-none"
                            title="Delete conversation"
                          >✕</button>
                        </Item>
                      </div>
                    );
                  })
              }
            </div>
          )}

          {/* ── DIRECT MESSAGES ── */}
          {section === "dms" && MESSAGING_ENABLED && (
            <div className="space-y-0.5">
              {/* Message search panel */}
              {showMsgSearch && (
                <div className="mb-2 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden" style={{ maxHeight: 320 }}>
                  <MessageSearch onClose={() => setShowMsgSearch(false)} />
                </div>
              )}
              {sortedDmChannels.length === 0 && groupDmChannels.length === 0 && (
                <p className="px-3 py-2 text-[12px]" style={{ color: SL }}>No messages yet — press + to start one</p>
              )}
              {/* 1:1 DMs — rendered directly from the channel list */}
              {sortedDmChannels.map(dmCh => {
                // Prefer the backend-supplied partner name; fall back to orgUsers lookup;
                // last resort: parse the raw "dm:{id1}:{id2}" channel name.
                const partnerName = (dmCh.dm_partner_username ?? (() => {
                  const parts = dmCh.name.split(":");
                  const otherId = parts.find(p => p !== "dm" && p !== user?.id);
                  return orgUsers.find(u => u.id === otherId)?.username ?? "";
                })()) || dmCh.name;
                const active = pathname === "/chat" && channelParam === dmCh.id;
                const unread = active ? 0 : (dmCh.unread_count ?? 0);
                const partnerPresence = dmCh.dm_partner_id ? getStatus(dmCh.dm_partner_id) : "offline";
                return (
                  <div key={dmCh.id} className="group relative">
                    <Item active={active} onClick={() => nav(`/chat?channel=${dmCh.id}`)}>
                      <span className="relative flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-gray-900 text-white text-[10px] font-bold uppercase">
                        {partnerName[0] ?? "?"}
                        <PresenceDot status={partnerPresence} />
                      </span>
                      <span className={`flex-1 min-w-0 truncate text-[13px] ${unread > 0 ? "font-semibold" : ""}`}>{partnerName}</span>
                      {unread > 0 ? (
                        <span className="shrink-0 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-indigo-600 px-1 text-[9px] font-bold text-white">
                          {unread > 99 ? "99+" : unread}
                        </span>
                      ) : dmCh.last_message_at ? (
                        <span className="shrink-0 text-[10px] group-hover:hidden" style={{ color: SL }}>{relTime(dmCh.last_message_at)}</span>
                      ) : null}
                      <button data-ch-menu onClick={e => openMenu(e, dmCh.id)}
                        className="hidden group-hover:flex shrink-0 h-5 w-5 items-center justify-center rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 leading-none"
                        title="Options">
                        <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
                          <circle cx="2" cy="8" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="14" cy="8" r="1.5"/>
                        </svg>
                      </button>
                    </Item>
                  </div>
                );
              })}
              {/* Group DMs */}
              {groupDmChannels.map(ch => {
                const active = pathname === "/chat" && channelParam === ch.id;
                const unread = active ? 0 : (ch.unread_count ?? 0);
                return (
                  <div key={ch.id} className="group relative">
                    <Item active={active} onClick={() => nav(`/chat?channel=${ch.id}`)}>
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white text-[9px] font-bold">
                        {ch.member_count}
                      </span>
                      <span className={`flex-1 min-w-0 truncate text-[13px] ${unread > 0 ? "font-semibold" : ""}`}>{ch.name}</span>
                      {unread > 0 ? (
                        <span className="shrink-0 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-indigo-600 px-1 text-[9px] font-bold text-white">
                          {unread > 99 ? "99+" : unread}
                        </span>
                      ) : ch.last_message_at ? (
                        <span className="shrink-0 text-[10px] group-hover:hidden" style={{ color: SL }}>{relTime(ch.last_message_at)}</span>
                      ) : null}
                      <button data-ch-menu onClick={e => openMenu(e, ch.id)}
                        className="hidden group-hover:flex shrink-0 h-5 w-5 items-center justify-center rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 leading-none"
                        title="Options">
                        <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
                          <circle cx="2" cy="8" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="14" cy="8" r="1.5"/>
                        </svg>
                      </button>
                    </Item>
                  </div>
                );
              })}
            </div>
          )}

          {/* ── CHANNELS (teams + public channels merged) ── */}
          {section === "channels" && (
            <div className="space-y-0.5">

              {/* All channels — flat list, no teams section */}
              {MESSAGING_ENABLED && publicChannels.length > 0 ? (
                publicChannels.map(ch => {
                  const active = pathname === "/chat" && channelParam === ch.id;
                  const unread = active ? 0 : (ch.unread_count ?? 0);
                  return (
                    <div key={ch.id} className="group relative">
                      <Item active={active} onClick={() => nav(`/chat?channel=${ch.id}`)}>
                        <span className="text-[13px] shrink-0 font-semibold leading-none" style={{ color: active ? AT : SL }}>#</span>
                        <span className={`flex-1 min-w-0 truncate text-[13px] ${unread > 0 ? "font-semibold" : ""}`}>{ch.name}</span>
                        {unread > 0 ? (
                          <span className="shrink-0 flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-indigo-600 px-1 text-[9px] font-bold text-white">
                            {unread > 99 ? "99+" : unread}
                          </span>
                        ) : ch.last_message_at ? (
                          <span className="shrink-0 text-[10px] group-hover:hidden" style={{ color: SL }}>{relTime(ch.last_message_at)}</span>
                        ) : null}
                        <button data-ch-menu onClick={e => openMenu(e, ch.id)}
                          className="hidden group-hover:flex shrink-0 h-5 w-5 items-center justify-center rounded hover:bg-gray-200 text-gray-400 hover:text-gray-600 leading-none"
                          title="Options">
                          <svg viewBox="0 0 16 16" fill="currentColor" className="w-3 h-3">
                            <circle cx="2" cy="8" r="1.5"/><circle cx="8" cy="8" r="1.5"/><circle cx="14" cy="8" r="1.5"/>
                          </svg>
                        </button>
                      </Item>
                    </div>
                  );
                })
              ) : (
                <p className="px-3 py-2 text-[12px]" style={{ color: SL }}>No channels yet — press + to create one</p>
              )}
            </div>
          )}

          {/* ── WORKSPACE ── */}
          {section === "workspace" && (
            <div className="space-y-0.5">
              {[
                { href: "/documents",   label: "Documents",   d: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z", d2: "M14 2v6h6M8 13h8M8 17h5" },
                { href: "/collections", label: "Collections", d: "M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" },
                { href: "/shared",      label: "Shared",      d: "M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8M16 6l-4-4-4 4M12 2v13" },
                { href: "/data",        label: "Data Explorer", d: "M4 6h16M4 10h16M4 14h16M4 18h16" },
              ].map(w => (
                <Item key={w.href} active={isActive(w.href)} onClick={() => nav(w.href)}>
                  <Ico d={w.d} d2={w.d2} />
                  <span className="text-[13px]">{w.label}</span>
                </Item>
              ))}
            </div>
          )}

          {/* ── CALENDAR ── */}
          {section === "calendar" && (
            <div className="space-y-0.5">
              <Item active={isActive("/calendar")} onClick={() => nav("/calendar")}>
                <Ico d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z" />
                <span className="text-[13px]">My Calendar</span>
              </Item>
            </div>
          )}

          {/* ── ADMIN ── */}
          {section === "admin" && (
            <div className="space-y-0.5">
              {[
                { href: "/admin",              label: "Admin Panel",    exact: true,  d: "M12 15a3 3 0 100-6 3 3 0 000 6z", d2: "M19.07 4.93l-1.41 1.41M4.93 4.93l1.41 1.41M19.07 19.07l-1.41-1.41M4.93 19.07l1.41-1.41M12 2v2M12 20v2M2 12h2M20 12h2" },
                { href: "/admin/compliance",   label: "Compliance",     exact: false, d: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z", d2: "M9 12l2 2 4-4" },
                { href: "/admin/analytics",    label: "Analytics",      exact: false, d: "M18 20V10M12 20V4M6 20v-6" },
                { href: "/admin/connectors",   label: "Data Connectors",exact: false, d: "M8 9l3 3-3 3M13 15h3M3 5h18M3 19h18M3 12h2M19 12h2" },
                { href: "/admin/settings",     label: "Settings",       exact: false, d: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z", d2: "M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
                { href: "/admin/branding",     label: "Branding",       exact: false, d: "M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" },
                { href: "/admin/storage",      label: "Storage",        exact: false, d: "M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4" },
                { href: "/admin/webhooks",     label: "Webhooks",       exact: false, d: "M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" },
                { href: "/admin/widget",       label: "Embed Widget",   exact: false, d: "M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" },
              ].map(a => (
                <Item key={a.href} active={isActive(a.href, a.exact)} onClick={() => nav(a.href)}>
                  <Ico d={a.d} d2={a.d2} />
                  <span className="text-[13px]">{a.label}</span>
                </Item>
              ))}
            </div>
          )}

        </div>

        {/* Mobile-only section switcher */}
        <div className="md:hidden flex items-center justify-around px-2 py-2 shrink-0"
          style={{ borderTop: `1px solid ${DV}` }}>
          {[
            { href: "/",        label: "Chat",     active: section === "chat",      d: "M13 2L3 14h9l-1 8 10-12h-9l1-8z",                                                                                                                                                badge: 0 },
            ...(MESSAGING_ENABLED ? [
              { href: "/chat",  label: "DMs",      active: section === "dms",       d: "M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z",                                                                                                                    badge: totalDmUnread },
              { href: "/teams", label: "Channels", active: section === "channels",  d: "M4 9h16M4 15h16M10 3v18M16 3v18",                                                                                                                                               badge: 0 },
            ] : [
              { href: "/teams", label: "Channels", active: section === "channels",  d: "M4 9h16M4 15h16M10 3v18M16 3v18",                                                                                                                                               badge: 0 },
            ]),
            { href: "/documents", label: "Docs",   active: section === "workspace", d: "M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z", d2: "M14 2v6h6M8 13h8M8 17h5",                                                                                       badge: 0 },
            { href: "/calendar",  label: "Cal",    active: section === "calendar",  d: "M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V6a2 2 0 012-2z",                                                                                     badge: calBadge },
            ...(isAdmin ? [{ href: "/admin", label: "Admin", active: section === "admin", d: "M12 15a3 3 0 100-6 3 3 0 000 6z", d2: "M19.07 4.93l-1.41 1.41M4.93 4.93l1.41 1.41M19.07 19.07l-1.41-1.41M4.93 19.07l1.41-1.41M12 2v2M12 20v2M2 12h2M20 12h2", badge: 0 }] : []),
          ].map(item => (
            <button key={item.href}
              onClick={() => { nav(item.href); if (item.href === "/calendar") dismissCalBadge(); }}
              className="relative flex flex-col items-center gap-0.5 px-2 py-1 rounded-lg transition-colors"
              style={{ color: item.active ? AT : SL }}>
              <div className="relative">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={item.active ? 2.25 : 1.75}
                  strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]">
                  <path d={(item as { d: string; d2?: string }).d} />
                  {(item as { d2?: string }).d2 && <path d={(item as { d2?: string }).d2} />}
                </svg>
                {!!(item as { badge?: number }).badge && (item as { badge: number }).badge > 0 && (
                  <span className="absolute -top-1.5 -right-2 flex h-[14px] min-w-[14px] items-center justify-center rounded-full bg-red-500 px-[3px] text-[8px] font-bold text-white leading-none">
                    {(item as { badge: number }).badge > 99 ? "99+" : (item as { badge: number }).badge}
                  </span>
                )}
              </div>
              <span className="text-[9px] font-medium leading-none">{item.label}</span>
            </button>
          ))}
        </div>

        {/* Mobile-only footer — profile link (rail handles sign-out on desktop) */}
        <div className="md:hidden px-2 py-2" style={{ borderTop: `1px solid ${DV}` }}>
          {user && (
            <Link href="/profile" onClick={onClose}
              className="flex w-full items-center gap-2.5 rounded-md px-3 py-2.5 transition-colors"
              style={{ color: MT }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.backgroundColor = HV; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}>
              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-black text-[10px] font-bold text-white">
                {initials}
              </span>
              <span className="flex-1 min-w-0 truncate font-medium text-[13px]">{user.display_name || user.username}</span>
            </Link>
          )}
          <button onClick={() => { if (confirm("Sign out of Nexus?")) logout(); }}
            className="flex w-full items-center gap-2.5 rounded-md px-3 py-2.5 transition-colors"
            style={{ color: MT }}
            onMouseEnter={e => { e.currentTarget.style.backgroundColor = HV; }}
            onMouseLeave={e => { e.currentTarget.style.backgroundColor = "transparent"; }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round" className="w-4 h-4 shrink-0" style={{ color: SL }}>
              <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />
            </svg>
            <span className="text-[13px]">Sign out</span>
          </button>
        </div>

      </div>
    </aside>
    </>
  );
}
