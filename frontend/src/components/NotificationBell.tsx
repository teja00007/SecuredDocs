"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";
function getWsBase() {
  if (API_BASE) return API_BASE.replace(/^http/, "ws");
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}`;
}

interface Notif {
  id: string;
  type: string;
  title: string;
  body: string | null;
  link: string | null;
  is_read: boolean;
  created_at: string;
}

function relTime(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

const TYPE_ICON: Record<string, string> = {
  mention:   "💬",
  document:  "📄",
  calendar:  "📅",
  compliance:"🛡️",
  system:    "⚙️",
};

export default function NotificationBell() {
  const [notifs,    setNotifs]    = useState<Notif[]>([]);
  const [unread,    setUnread]    = useState(0);
  const [open,      setOpen]      = useState(false);
  const [loading,   setLoading]   = useState(false);
  const dropRef  = useRef<HTMLDivElement>(null);
  const wsRef    = useRef<WebSocket | null>(null);

  // Load notifications
  const load = useCallback(async () => {
    try {
      setLoading(true);
      const [ns, uc] = await Promise.all([
        api.get<Notif[]>("/api/v1/notifications?limit=20"),
        api.get<{ count: number }>("/api/v1/notifications/unread-count"),
      ]);
      setNotifs(ns);
      setUnread(uc.count);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();

    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;

    function connect() {
      const token = getAccessToken();
      if (!token || cancelled) return;
      const ws = new WebSocket(`${getWsBase()}/api/v1/notifications/ws?token=${token}`);
      wsRef.current = ws;
      ws.onopen = () => {
        // Re-sync count and list in case notifications arrived while disconnected
        load();
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send("ping");
        }, 30000);
      };
      ws.onmessage = (e) => {
        try {
          const raw = JSON.parse(e.data);
          // Backend sends {type:"notification", notif_type:"dm"} — normalise to {type:"dm"}
          const data = { ...raw, type: raw.notif_type ?? raw.type } as Notif;
          setNotifs(prev => [data, ...prev].slice(0, 20));
          setUnread(u => u + 1);
          // Tell AppSidebar to immediately refresh channel unread counts
          window.dispatchEvent(new CustomEvent("chat:new-message"));
        } catch { /* ignore */ }
      };
      ws.onclose = () => {
        if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
        if (!cancelled) reconnectTimer = setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pingTimer) clearInterval(pingTimer);
      wsRef.current?.close();
    };
  }, [load]);

  // Close on click-outside
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  async function markRead(id: string) {
    await api.patch(`/api/v1/notifications/${id}/read`, {});
    setNotifs(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
    setUnread(u => Math.max(0, u - 1));
  }

  async function markAllRead() {
    await api.patch("/api/v1/notifications/read-all", {});
    setNotifs(prev => prev.map(n => ({ ...n, is_read: true })));
    setUnread(0);
  }

  function handleOpen() {
    setOpen(v => !v);
  }

  return (
    <div ref={dropRef} className="relative">
      <button
        onClick={handleOpen}
        className={`relative flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
          open ? "bg-indigo-50 text-indigo-600" : "text-gray-500 hover:bg-gray-100 hover:text-gray-900"
        }`}
        aria-label="Notifications"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5">
          <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[9px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 rounded-xl border border-gray-200 bg-white shadow-2xl z-[300] overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-3">
            <h3 className="text-sm font-semibold text-gray-800">Notifications</h3>
            {unread > 0 && (
              <button
                onClick={markAllRead}
                className="text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
              >
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-80 overflow-y-auto">
            {loading ? (
              <div className="flex justify-center py-8">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
              </div>
            ) : notifs.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-gray-400">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-8 h-8 mb-2 text-gray-300">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9M13.73 21a2 2 0 01-3.46 0" />
                </svg>
                <p className="text-sm">No notifications yet</p>
              </div>
            ) : (
              notifs.map((n) => (
                <button
                  key={n.id}
                  onClick={() => { if (!n.is_read) markRead(n.id); if (n.link) window.location.href = n.link; }}
                  className={`flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-gray-50 ${
                    !n.is_read ? "bg-indigo-50/40" : ""
                  }`}
                >
                  <span className="mt-0.5 text-base shrink-0">{TYPE_ICON[n.type] ?? "🔔"}</span>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm leading-snug ${!n.is_read ? "font-semibold text-gray-800" : "font-medium text-gray-700"}`}>
                      {n.title}
                    </p>
                    {n.body && <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{n.body}</p>}
                    <p className="text-[10px] text-gray-400 mt-1">{relTime(n.created_at)}</p>
                  </div>
                  {!n.is_read && (
                    <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-indigo-500" />
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
