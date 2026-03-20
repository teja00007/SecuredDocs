"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

export interface PresenceData {
  status: "online" | "away" | "dnd" | "offline";
  custom_status: string | null;
  last_seen: string | null;
}

type PresenceMap = Map<string, PresenceData>;

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

function getWsBase() {
  if (API_BASE) return API_BASE.replace(/^http/, "ws");
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}`;
}

// Singleton so multiple consumers share one WebSocket
let sharedWs: WebSocket | null = null;
let sharedListeners: Set<(data: { user_id: string } & PresenceData) => void> = new Set();
let sharedPingTimer: ReturnType<typeof setInterval> | null = null;
let sharedReconnectTimer: ReturnType<typeof setTimeout> | null = null;
let sharedConnecting = false;

function ensurePresenceWs() {
  if (sharedConnecting || (sharedWs && sharedWs.readyState === WebSocket.OPEN)) return;
  const token = getAccessToken();
  if (!token) return;
  sharedConnecting = true;
  // Use the notification WS endpoint for presence — it carries presence_update events
  // Fall back gracefully if the endpoint does not exist
  try {
    const ws = new WebSocket(`${getWsBase()}/api/v1/notifications/ws?token=${token}`);
    sharedWs = ws;
    ws.onopen = () => {
      sharedConnecting = false;
      if (sharedPingTimer) clearInterval(sharedPingTimer);
      sharedPingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
      }, 30000);
    };
    ws.onmessage = (e) => {
      try {
        const d = JSON.parse(e.data);
        if (d.type === "presence_update" && d.user_id) {
          sharedListeners.forEach(fn => fn(d));
        }
      } catch { /* ignore */ }
    };
    ws.onerror = () => { sharedConnecting = false; };
    ws.onclose = () => {
      sharedConnecting = false;
      if (sharedPingTimer) { clearInterval(sharedPingTimer); sharedPingTimer = null; }
      sharedWs = null;
      // Reconnect after 5s
      if (sharedListeners.size > 0) {
        sharedReconnectTimer = setTimeout(ensurePresenceWs, 5000);
      }
    };
  } catch {
    sharedConnecting = false;
  }
}

export function usePresence() {
  const [presence, setPresence] = useState<PresenceMap>(new Map());
  const listenerRef = useRef<((data: { user_id: string } & PresenceData) => void) | null>(null);

  const loadPresence = useCallback(async () => {
    try {
      const data = await api.get<Array<{ user_id: string } & PresenceData>>("/api/v1/users/presence");
      setPresence(prev => {
        const next = new Map(prev);
        data.forEach(p => next.set(p.user_id, { status: p.status, custom_status: p.custom_status, last_seen: p.last_seen }));
        return next;
      });
    } catch {
      // Presence API might not exist — silently ignore
    }
  }, []);

  useEffect(() => {
    loadPresence();

    const listener = (d: { user_id: string } & PresenceData) => {
      setPresence(prev => {
        const next = new Map(prev);
        next.set(d.user_id, { status: d.status, custom_status: d.custom_status, last_seen: d.last_seen });
        return next;
      });
    };
    listenerRef.current = listener;
    sharedListeners.add(listener);
    ensurePresenceWs();

    return () => {
      if (listenerRef.current) {
        sharedListeners.delete(listenerRef.current);
        listenerRef.current = null;
      }
      if (sharedListeners.size === 0) {
        if (sharedReconnectTimer) { clearTimeout(sharedReconnectTimer); sharedReconnectTimer = null; }
        if (sharedPingTimer) { clearInterval(sharedPingTimer); sharedPingTimer = null; }
        sharedWs?.close();
        sharedWs = null;
        sharedConnecting = false;
      }
    };
  }, [loadPresence]);

  const getStatus = useCallback((userId: string): "online" | "away" | "dnd" | "offline" => {
    return presence.get(userId)?.status ?? "offline";
  }, [presence]);

  const getCustomStatus = useCallback((userId: string): string | null => {
    return presence.get(userId)?.custom_status ?? null;
  }, [presence]);

  return { presence, getStatus, getCustomStatus };
}
