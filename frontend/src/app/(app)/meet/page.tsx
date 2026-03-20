"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

interface CalendarEvent {
  id: string;
  title: string;
  start_time: string;
  end_time: string;
  room_name: string | null;
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

function formatDuration(start: string, end: string) {
  const mins = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60000);
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60), m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export default function MeetPage() {
  const router  = useRouter();
  const [code,     setCode]     = useState("");
  const [starting, setStarting] = useState(false);
  const [meetings, setMeetings] = useState<CalendarEvent[]>([]);

  useEffect(() => {
    api.get<CalendarEvent[]>("/api/v1/calendar/events")
      .then(events => {
        const now = Date.now();
        setMeetings(
          events
            .filter(e => e.room_name && new Date(e.start_time).getTime() >= now - 30 * 60 * 1000)
            .sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())
            .slice(0, 8),
        );
      })
      .catch(() => {});
  }, []);

  async function startMeeting() {
    setStarting(true);
    try {
      const res = await api.post<{ room_name: string }>("/api/v1/huddle/rooms/instant", {});
      router.push(`/huddle/${res.room_name}`);
    } catch {
      setStarting(false);
    }
  }

  function joinWithCode() {
    const clean = code.trim().replace(/\s+/g, "-");
    if (clean) router.push(`/huddle/${clean}`);
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-slate-50">
      <div className="mx-auto w-full max-w-2xl px-6 py-10 space-y-8">

        {/* ── Hero ──────────────────────────────────────────────────────── */}
        <div className="text-center space-y-3">
          <div className="flex justify-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-indigo-600 shadow-lg shadow-indigo-200">
              <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="1.75" strokeLinecap="round" className="w-8 h-8">
                <polygon points="23 7 16 12 23 17 23 7" />
                <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
              </svg>
            </div>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Nexus Meet</h1>
          <p className="text-sm text-gray-500">HD video &amp; voice calls — powered by Livekit</p>
        </div>

        {/* ── Actions ───────────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">

          {/* New meeting */}
          <button
            onClick={startMeeting}
            disabled={starting}
            className="flex items-center gap-4 rounded-2xl bg-indigo-600 px-6 py-5 text-white shadow-sm hover:bg-indigo-700 active:bg-indigo-800 transition-colors disabled:opacity-60 text-left"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/15">
              {starting ? (
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" className="w-5 h-5">
                  <polygon points="23 7 16 12 23 17 23 7" />
                  <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                </svg>
              )}
            </div>
            <div>
              <div className="font-semibold text-base">New meeting</div>
              <div className="text-xs text-indigo-200 mt-0.5">Start an instant call</div>
            </div>
          </button>

          {/* Join with code */}
          <div className="flex flex-col justify-center gap-3 rounded-2xl border-2 border-dashed border-gray-200 bg-white px-6 py-5">
            <div className="flex items-center gap-2 text-gray-700">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4 shrink-0">
                <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3" />
              </svg>
              <span className="text-sm font-semibold">Join with a code</span>
            </div>
            <div className="flex gap-2">
              <input
                value={code}
                onChange={e => setCode(e.target.value)}
                onKeyDown={e => e.key === "Enter" && joinWithCode()}
                placeholder="Room code or link…"
                className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 transition"
              />
              <button
                onClick={joinWithCode}
                disabled={!code.trim()}
                className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-40 transition-colors"
              >
                Join
              </button>
            </div>
          </div>
        </div>

        {/* ── Upcoming video meetings ────────────────────────────────────── */}
        {meetings.length > 0 && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
            <div className="flex items-center gap-2 px-5 py-4 border-b border-gray-50">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-indigo-500">
                <rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" />
              </svg>
              <h2 className="text-sm font-semibold text-gray-800">Upcoming &amp; ongoing video meetings</h2>
            </div>
            <ul>
              {meetings.map((evt, i) => {
                const isNow = new Date(evt.start_time).getTime() <= Date.now() && new Date(evt.end_time).getTime() >= Date.now();
                return (
                  <li key={evt.id} className={`flex items-center gap-4 px-5 py-3.5 group hover:bg-gray-50 transition-colors ${i < meetings.length - 1 ? "border-b border-gray-50" : ""}`}>
                    {/* Time indicator */}
                    <div className="shrink-0 w-20 text-right">
                      {isNow ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" /> Live
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">{formatDateTime(evt.start_time).split(", ").slice(1).join(", ")}</span>
                      )}
                    </div>
                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-800 truncate">{evt.title}</p>
                      <p className="text-[11px] text-gray-400 mt-0.5">{formatDateTime(evt.start_time)} · {formatDuration(evt.start_time, evt.end_time)}</p>
                    </div>
                    {/* Join */}
                    <button
                      onClick={() => router.push(`/huddle/${evt.room_name}`)}
                      className="shrink-0 rounded-lg bg-indigo-600 px-3.5 py-1.5 text-xs font-medium text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-indigo-700"
                    >
                      Join
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {/* ── Feature pills ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-3">
          {[
            { icon: (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5 text-indigo-500">
                  <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3zM19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8" />
                </svg>
              ), label: "HD Audio",   sub: "Crystal-clear voice" },
            { icon: (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5 text-violet-500">
                  <polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                </svg>
              ), label: "1080p Video", sub: "All participants" },
            { icon: (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5 text-emerald-500">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
              ), label: "Encrypted",   sub: "End-to-end secure" },
          ].map(f => (
            <div key={f.label} className="flex flex-col items-center gap-2 rounded-xl bg-white border border-gray-100 shadow-sm px-4 py-5 text-center">
              {f.icon}
              <div className="text-sm font-semibold text-gray-700">{f.label}</div>
              <div className="text-[11px] text-gray-400">{f.sub}</div>
            </div>
          ))}
        </div>

      </div>
    </div>
  );
}
