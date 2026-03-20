"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

interface PendingCall {
  id: string;
  title: string;
  body: string;
  link: string;
  created_at: string;
}

function startRing(): () => void {
  try {
    const ctx = new AudioContext();
    let ringing = true;

    const ring = () => {
      if (!ringing) return;
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.setValueAtTime(660, ctx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.25, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.4);
      setTimeout(() => { if (ringing) ring(); }, 1400);
    };
    ring();
    return () => { ringing = false; ctx.close(); };
  } catch {
    return () => {};
  }
}

export default function IncomingCallOverlay() {
  const router = useRouter();
  const [call, setCall]     = useState<PendingCall | null>(null);
  // Refs so the polling callback always sees current values without stale closures
  const callRef    = useRef<PendingCall | null>(null);
  const stopRingRef = useRef<() => void>(() => {});
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    intervalRef.current = setInterval(async () => {
      try {
        const calls = await api.get<PendingCall[]>("/api/v1/huddle/pending-calls");
        if (calls.length > 0) {
          if (!callRef.current) {
            callRef.current = calls[0];
            setCall(calls[0]);
            stopRingRef.current = startRing();
          }
        } else {
          if (callRef.current) {
            callRef.current = null;
            setCall(null);
            stopRingRef.current();
            stopRingRef.current = () => {};
          }
        }
      } catch { /* ignore */ }
    }, 2500);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      stopRingRef.current();
    };
  }, []); // run once — polling callback reads callRef (not stale `call`)

  async function accept() {
    if (!callRef.current) return;
    const c = callRef.current;
    stopRingRef.current();
    stopRingRef.current = () => {};
    callRef.current = null;
    setCall(null);
    await api.post(`/api/v1/huddle/pending-calls/${c.id}/dismiss`, {}).catch(() => {});
    const roomName = c.link.replace("/huddle/", "");
    router.push(`/huddle/${roomName}`);
  }

  async function decline() {
    if (!callRef.current) return;
    const c = callRef.current;
    stopRingRef.current();
    stopRingRef.current = () => {};
    callRef.current = null;
    setCall(null);
    await api.post(`/api/v1/huddle/pending-calls/${c.id}/dismiss`, {}).catch(() => {});
  }

  if (!call) return null;

  const callerName = call.title.replace(" is calling you", "");
  const initials   = callerName.split(".").map(p => p[0]?.toUpperCase() ?? "").join("").slice(0, 2) || callerName[0]?.toUpperCase() || "?";

  return (
    <div className="fixed bottom-6 right-6 z-[500] w-80 rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl overflow-hidden animate-in slide-in-from-bottom-4 duration-300">
      {/* Pulsing ring bar */}
      <div className="h-1 w-full bg-gradient-to-r from-indigo-500 via-emerald-400 to-indigo-500 animate-pulse" />

      <div className="p-4 flex items-center gap-4">
        {/* Avatar with pulse ring */}
        <div className="relative shrink-0">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-600 text-lg font-bold text-white select-none">
            {initials}
          </div>
          <span className="absolute inset-0 rounded-full border-2 border-indigo-400 animate-ping opacity-50" />
        </div>

        {/* Text */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-white truncate">{callerName}</p>
          <p className="text-xs text-slate-400">Incoming video call…</p>
        </div>
      </div>

      {/* Buttons */}
      <div className="flex border-t border-slate-700/60">
        <button
          onClick={decline}
          className="flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium text-slate-400 hover:bg-slate-800 hover:text-red-400 transition-colors"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4">
            <path d="M10.68 13.31a16 16 0 003.41 2.6l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7 2 2 0 012 2v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.42 19.42 0 013.43 9.63a19.86 19.86 0 01-3.07-8.67A2 2 0 012.18 1h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L6.25 8.91" />
            <line x1="23" y1="1" x2="1" y2="23" />
          </svg>
          Decline
        </button>
        <div className="w-px bg-slate-700/60" />
        <button
          onClick={accept}
          className="flex-1 flex items-center justify-center gap-2 py-3 text-sm font-medium text-emerald-400 hover:bg-emerald-900/30 hover:text-emerald-300 transition-colors"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4">
            <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 013.32 9.94 19.79 19.79 0 01.25 1.31 2 2 0 012.22 1h3a2 2 0 012 1.72 12.84 12.84 0 00.7 2.81 2 2 0 01-.45 2.11L6.25 8.91a16 16 0 006.61 6.61l1.27-1.27a2 2 0 012.11-.45 12.84 12.84 0 002.81.7A2 2 0 0122 16.92z" />
          </svg>
          Accept
        </button>
      </div>
    </div>
  );
}
