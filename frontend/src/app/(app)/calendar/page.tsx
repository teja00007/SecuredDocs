"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import type { User } from "@/types";

interface Attendee {
  user_id: string;
  username: string;
  status: "pending" | "accepted" | "declined";
}
interface CalendarEvent {
  id: string;
  title: string;
  description: string | null;
  start_time: string;
  end_time: string;
  created_by: string;
  creator_username: string;
  room_name: string | null;
  created_at: string;
  attendees: Attendee[];
}
interface OrgUser { id: string; username: string; email: string; }

type ViewMode = "month" | "week" | "agenda";

// ── Custom time picker ─────────────────────────────────────────────────────
function TimePickerBtn({ h, m, ap, onChange }: {
  h: number; m: string; ap: string;
  onChange: (h: number, m: string, ap: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pos,  setPos]  = useState({ top: 0, left: 0 });
  const btnRef  = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || listRef.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Scroll selected into view
  useEffect(() => {
    if (!open || !listRef.current) return;
    const sel = listRef.current.querySelector<HTMLButtonElement>("[data-sel='1']");
    if (sel) sel.scrollIntoView({ block: "center" });
  }, [open]);

  function toggle() {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      setPos({ top: r.bottom + 6, left: r.left });
    }
    setOpen(o => !o);
  }

  const slots = Array.from({ length: 96 }, (_, i) => {
    const hh24 = Math.floor((i * 15) / 60);
    const mm   = String((i * 15) % 60).padStart(2, "0");
    const ap2  = hh24 < 12 ? "AM" : "PM";
    const h12  = hh24 === 0 ? 12 : hh24 > 12 ? hh24 - 12 : hh24;
    return { h: h12, m: mm, ap: ap2, label: `${h12}:${mm} ${ap2}` };
  });

  const dropdown = open ? createPortal(
    <div ref={listRef}
      className="fixed z-[9999] w-32 overflow-y-auto rounded-xl border border-slate-200 bg-white py-1 shadow-2xl"
      style={{ top: pos.top, left: pos.left, maxHeight: 220 }}>
      {slots.map((s, i) => {
        const selected = s.h === h && s.m === m && s.ap === ap;
        return (
          <button key={i} type="button" data-sel={selected ? "1" : "0"}
            onClick={() => { onChange(s.h, s.m, s.ap); setOpen(false); }}
            className={`w-full px-3 py-1.5 text-left text-xs transition-colors ${
              selected ? "bg-indigo-600 text-white font-semibold" : "text-slate-600 hover:bg-slate-50"
            }`}>
            {s.label}
          </button>
        );
      })}
    </div>,
    document.body
  ) : null;

  return (
    <>
      <button ref={btnRef} type="button" onClick={toggle}
        className="rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-200 transition-colors min-w-[76px] text-center tabular-nums">
        {h}:{m} {ap}
      </button>
      {dropdown}
    </>
  );
}

const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const MONTHS_S = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DAYS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
const DAYS_S = ["S","M","T","W","T","F","S"];
const HOUR_H = 56; // px per hour in week view
const HOURS = Array.from({ length: 24 }, (_, i) => i);

const RSVP_COLORS: Record<string, string> = {
  accepted: "bg-emerald-100 text-emerald-700",
  declined: "bg-red-100 text-red-700",
  pending: "bg-amber-100 text-amber-700",
};

const EVENT_BG = [
  "#6366f1","#8b5cf6","#0ea5e9","#10b981","#f59e0b","#ef4444","#ec4899","#14b8a6",
];
function evColor(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return EVENT_BG[Math.abs(h) % EVENT_BG.length];
}

function isSameDay(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function addDays(d: Date, n: number) { const r = new Date(d); r.setDate(r.getDate() + n); return r; }
function getWeekStart(d: Date) { const r = new Date(d); r.setDate(r.getDate() - r.getDay()); r.setHours(0,0,0,0); return r; }
function fmtTime(iso: string) { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
function fmtDate(iso: string) {
  const d = new Date(iso);
  return `${DAYS[d.getDay()]}, ${MONTHS_S[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}
function pad(n: number) { return String(n).padStart(2, "0"); }
function hourLabel(h: number) { return h === 0 ? "12 AM" : h < 12 ? `${h} AM` : h === 12 ? "12 PM" : `${h-12} PM`; }
function fmtDisplayDate(ds: string) {
  if (!ds) return "Pick date";
  const d = new Date(ds + "T00:00:00");
  return `${DAYS[d.getDay()]}, ${MONTHS_S[d.getMonth()]} ${d.getDate()}`;
}

export default function CalendarPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [viewDate, setViewDate] = useState(new Date());
  const [view, setView] = useState<ViewMode>("week");
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  // Create form
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [startDate, setStartDate] = useState("");
  const [startH,  setStartH]  = useState(9);
  const [startM,  setStartM]  = useState("00");
  const [startAP, setStartAP] = useState("AM");
  const [endDate, setEndDate] = useState("");
  const [endH,  setEndH]  = useState(10);
  const [endM,  setEndM]  = useState("00");
  const [endAP, setEndAP] = useState("AM");
  const [withVideo, setWithVideo] = useState(false);
  const [recurrence, setRecurrence] = useState<"none" | "daily" | "weekly" | "monthly">("none");
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [inviteSearch, setInviteSearch] = useState("");
  const [invited, setInvited] = useState<OrgUser[]>([]);
  const [creating, setCreating] = useState(false);

  const weekGridRef = useRef<HTMLDivElement>(null);
  const startDateRef = useRef<HTMLInputElement>(null);
  const endDateRef   = useRef<HTMLInputElement>(null);
  const today = new Date();

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    Promise.all([
      api.get<User>("/api/v1/auth/me"),
      api.get<CalendarEvent[]>("/api/v1/calendar/events"),
    ]).then(([u, evs]) => { setUser(u); setEvents(evs); }).catch(() => {});
  }, [router]);

  useEffect(() => {
    if (view === "week") {
      setTimeout(() => {
        weekGridRef.current?.scrollTo({ top: 7 * HOUR_H, behavior: "smooth" });
      }, 50);
    }
  }, [view]);

  const year = viewDate.getFullYear();
  const month = viewDate.getMonth();
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const weekStart = getWeekStart(viewDate);
  const weekDays = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));

  function prev() {
    if (view === "month") setViewDate(new Date(year, month - 1, 1));
    else if (view === "week") setViewDate(addDays(viewDate, -7));
    else setViewDate(addDays(viewDate, -30));
  }
  function next() {
    if (view === "month") setViewDate(new Date(year, month + 1, 1));
    else if (view === "week") setViewDate(addDays(viewDate, 7));
    else setViewDate(addDays(viewDate, 30));
  }
  function goToday() { setViewDate(new Date()); }

  function navLabel() {
    if (view === "week") {
      const we = addDays(weekStart, 6);
      if (weekStart.getMonth() === we.getMonth())
        return `${MONTHS[weekStart.getMonth()]} ${weekStart.getFullYear()}`;
      return `${MONTHS_S[weekStart.getMonth()]} – ${MONTHS_S[we.getMonth()]} ${we.getFullYear()}`;
    }
    return `${MONTHS[month]} ${year}`;
  }

  function eventsOnDay(date: Date) {
    return events.filter(ev => isSameDay(new Date(ev.start_time), date));
  }

  function to24h(h: number, m: string, ap: string): string {
    let hh = h;
    if (ap === "AM" && h === 12) hh = 0;
    else if (ap === "PM" && h !== 12) hh = h + 12;
    return `${pad(hh)}:${m}`;
  }
  function from24h(hhmm: string): { h: number; m: string; ap: string } {
    const [hh] = hhmm.split(":").map(Number);
    return {
      h:  hh === 0 ? 12 : hh > 12 ? hh - 12 : hh,
      m:  "00",
      ap: hh < 12 ? "AM" : "PM",
    };
  }

  function openCreate(day?: Date, hStr?: string) {
    api.get<OrgUser[]>("/api/v1/admin/users/search")
      .then(u => setOrgUsers(u.filter(x => x.id !== user?.id)))
      .catch(() => {});
    const d = day ?? new Date();
    const ds = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
    const sh = hStr ?? "09:00";
    const s = from24h(sh);
    const [hh24] = sh.split(":").map(Number);
    const endHh24 = Math.min(hh24 + 1, 23);
    const e = from24h(`${pad(endHh24)}:00`);
    setTitle(""); setDescription(""); setInvited([]); setWithVideo(false); setInviteSearch(""); setRecurrence("none");
    setStartDate(ds); setEndDate(ds);
    setStartH(s.h); setStartM(s.m); setStartAP(s.ap);
    setEndH(e.h); setEndM(e.m); setEndAP(e.ap);
    setShowCreate(true);
  }

  function closeCreate() {
    setShowCreate(false);
    setTitle(""); setDescription(""); setStartDate(""); setEndDate(""); setInvited([]);
    setStartH(9); setStartM("00"); setStartAP("AM");
    setEndH(10); setEndM("00"); setEndAP("AM");
    setRecurrence("none");
  }

  async function handleCreate() {
    if (!title.trim() || !startDate || !endDate) return;
    setCreating(true);
    try {
      const ev = await api.post<CalendarEvent>("/api/v1/calendar/events", {
        title: title.trim(),
        description: description.trim() || null,
        start_time: new Date(`${startDate}T${to24h(startH, startM, startAP)}`).toISOString(),
        end_time: new Date(`${endDate}T${to24h(endH, endM, endAP)}`).toISOString(),
        attendee_ids: invited.map(u => u.id),
        attendee_usernames: Object.fromEntries(invited.map(u => [u.id, u.username])),
        with_video: withVideo,
        recurrence_rule: recurrence === "none" ? null : `RRULE:FREQ=${recurrence.toUpperCase()}`,
      });
      setEvents(prev => [...prev, ev]);
      closeCreate();
    } finally { setCreating(false); }
  }

  async function handleRSVP(eventId: string, status: "accepted" | "declined") {
    const updated = await api.post<CalendarEvent>(`/api/v1/calendar/events/${eventId}/rsvp`, { status });
    setEvents(prev => prev.map(e => e.id === eventId ? updated : e));
    setSelectedEvent(updated);
  }

  async function addRoom(ev: CalendarEvent) {
    const updated = await api.post<CalendarEvent>(`/api/v1/calendar/events/${ev.id}/room`, {});
    setEvents(prev => prev.map(e => e.id === updated.id ? updated : e));
    setSelectedEvent(updated);
  }

  async function deleteEvent(ev: CalendarEvent) {
    if (!confirm("Delete this event?")) return;
    await api.delete(`/api/v1/calendar/events/${ev.id}`);
    setEvents(prev => prev.filter(e => e.id !== ev.id));
    setSelectedEvent(null);
  }

  const myStatus = (ev: CalendarEvent) => ev.attendees.find(a => a.user_id === user?.id)?.status ?? null;

  if (!user) return null;

  return (
    <main className="flex flex-1 flex-col overflow-hidden bg-white">

      {/* ── Toolbar ──────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-2.5 shrink-0 flex-wrap">
        <button onClick={goToday}
          className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 shrink-0">
          Today
        </button>
        <div className="flex shrink-0">
          <button onClick={prev}
            className="rounded-l-lg border border-slate-200 px-2.5 py-1.5 text-slate-500 hover:bg-slate-50">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 18l-6-6 6-6" />
            </svg>
          </button>
          <button onClick={next}
            className="rounded-r-lg border border-l-0 border-slate-200 px-2.5 py-1.5 text-slate-500 hover:bg-slate-50">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 18l6-6-6-6" />
            </svg>
          </button>
        </div>
        <h2 className="text-sm font-semibold text-slate-800 min-w-[140px]">{navLabel()}</h2>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded-lg border border-slate-200 overflow-hidden text-xs shrink-0">
            {(["week","month","agenda"] as ViewMode[]).map(v => (
              <button key={v} onClick={() => setView(v)}
                className={`px-3 py-1.5 capitalize transition-colors ${
                  view === v ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"
                }`}>
                {v}
              </button>
            ))}
          </div>
          <button
            onClick={() => {
              // Generate iCal (.ics) from current events
              const lines = [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "PRODID:-//Nexus//Calendar//EN",
                "CALSCALE:GREGORIAN",
                "METHOD:PUBLISH",
              ];
              for (const ev of events) {
                const fmt = (iso: string) => iso.replace(/[-:]/g, "").replace(/\.\d+/, "").replace("Z", "Z");
                lines.push("BEGIN:VEVENT");
                lines.push(`UID:${ev.id}@nexus`);
                lines.push(`DTSTART:${fmt(ev.start_time)}`);
                lines.push(`DTEND:${fmt(ev.end_time)}`);
                lines.push(`SUMMARY:${ev.title.replace(/\n/g, "\\n")}`);
                if (ev.description) lines.push(`DESCRIPTION:${ev.description.replace(/\n/g, "\\n")}`);
                lines.push(`DTSTAMP:${fmt(new Date().toISOString())}`);
                lines.push("END:VEVENT");
              }
              lines.push("END:VCALENDAR");
              const blob = new Blob([lines.join("\r\n")], { type: "text/calendar" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url; a.download = "nexus-calendar.ics"; a.click();
              setTimeout(() => URL.revokeObjectURL(url), 5000);
            }}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 shrink-0">
            Export .ics
          </button>
          <button onClick={() => openCreate()}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700 shrink-0">
            + New Event
          </button>
        </div>
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* ── Main calendar ──────────────────────────────────────────── */}
        <div className="flex flex-1 flex-col min-w-0 overflow-hidden">

          {/* MONTH VIEW */}
          {view === "month" && (
            <div className="flex flex-1 flex-col overflow-y-auto">
              <div className="grid grid-cols-7 border-b border-slate-200 shrink-0">
                {DAYS.map((d, i) => (
                  <div key={d} className={`py-2.5 text-center text-xs font-medium ${i === 0 || i === 6 ? "text-rose-400" : "text-slate-500"}`}>{d}</div>
                ))}
              </div>
              <div className="grid grid-cols-7 flex-1" style={{ gridAutoRows: "minmax(96px, 1fr)" }}>
                {Array.from({ length: firstDay }).map((_, i) => (
                  <div key={`e${i}`} className="border-b border-r border-slate-100 bg-slate-50/60" />
                ))}
                {Array.from({ length: daysInMonth }, (_, i) => i + 1).map(day => {
                  const date = new Date(year, month, day);
                  const dayEvs = eventsOnDay(date);
                  const isToday = isSameDay(date, today);
                  const isWeekend = date.getDay() === 0 || date.getDay() === 6;
                  return (
                    <div key={day}
                      className={`border-b border-r border-slate-100 p-1.5 cursor-pointer group hover:bg-slate-50/80 transition-colors ${isWeekend ? "bg-rose-50/20" : ""}`}
                      onClick={() => openCreate(date)}>
                      <div className="flex items-center justify-between mb-1">
                        <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold transition-colors ${
                          isToday ? "bg-indigo-600 text-white" : "text-slate-700 group-hover:bg-slate-200"
                        }`}>{day}</span>
                        {dayEvs.length > 0 && (
                          <span className="text-[10px] text-slate-400 mr-0.5">{dayEvs.length}</span>
                        )}
                      </div>
                      <div className="space-y-0.5">
                        {dayEvs.slice(0, 3).map(ev => (
                          <button key={ev.id}
                            onClick={e => { e.stopPropagation(); setSelectedEvent(ev); }}
                            className="w-full truncate rounded px-1.5 py-0.5 text-left text-[11px] font-medium text-white hover:opacity-90 transition-opacity"
                            style={{ backgroundColor: evColor(ev.id) }}>
                            {fmtTime(ev.start_time)} {ev.title}
                          </button>
                        ))}
                        {dayEvs.length > 3 && (
                          <p className="text-[10px] text-slate-400 px-1">+{dayEvs.length - 3} more</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* WEEK VIEW */}
          {view === "week" && (
            <div className="flex flex-col flex-1 overflow-hidden">
              {/* Day headers */}
              <div className="grid shrink-0 border-b border-slate-200" style={{ gridTemplateColumns: "52px repeat(7, 1fr)" }}>
                <div className="border-r border-slate-100" />
                {weekDays.map((d, i) => {
                  const isToday = isSameDay(d, today);
                  return (
                    <div key={i} className="py-2 text-center border-r border-slate-100">
                      <p className="text-[10px] font-medium text-slate-500 uppercase">{DAYS[d.getDay()]}</p>
                      <p className={`text-base font-semibold mt-0.5 leading-none w-8 h-8 flex items-center justify-center rounded-full mx-auto ${
                        isToday ? "bg-indigo-600 text-white" : "text-slate-800"
                      }`}>{d.getDate()}</p>
                    </div>
                  );
                })}
              </div>

              {/* Scrollable time grid */}
              <div ref={weekGridRef} className="flex-1 overflow-y-auto overflow-x-hidden">
                <div className="relative flex" style={{ height: `${24 * HOUR_H}px` }}>

                  {/* Time gutter */}
                  <div className="w-[52px] shrink-0 border-r border-slate-100 relative">
                    {HOURS.map(h => (
                      <div key={h} className="absolute w-full border-b border-slate-100 flex items-start justify-end pr-2 pt-1"
                        style={{ top: h * HOUR_H, height: HOUR_H }}>
                        {h > 0 && <span className="text-[10px] text-slate-400 -mt-2">{hourLabel(h)}</span>}
                      </div>
                    ))}
                  </div>

                  {/* Day columns */}
                  {weekDays.map((day, colIdx) => (
                    <div key={colIdx} className="flex-1 relative border-r border-slate-100">
                      {/* Hour dividers + click zones */}
                      {HOURS.map(h => (
                        <div key={h}
                          className="absolute w-full border-b border-slate-100 hover:bg-indigo-50/30 cursor-pointer transition-colors"
                          style={{ top: h * HOUR_H, height: HOUR_H }}
                          onClick={() => openCreate(day, `${pad(h)}:00`)}
                        />
                      ))}

                      {/* Events */}
                      {eventsOnDay(day).map(ev => {
                        const start = new Date(ev.start_time);
                        const end = new Date(ev.end_time);
                        const topMins = start.getHours() * 60 + start.getMinutes();
                        const durMins = Math.max((end.getTime() - start.getTime()) / 60000, 30);
                        const top = (topMins / 60) * HOUR_H;
                        const height = Math.max((durMins / 60) * HOUR_H, 22);
                        return (
                          <button key={ev.id}
                            onClick={e => { e.stopPropagation(); setSelectedEvent(ev); }}
                            className="absolute inset-x-1 z-10 rounded-md px-1.5 py-0.5 text-left text-[11px] font-medium text-white overflow-hidden hover:brightness-110 transition-all"
                            style={{ top, height, backgroundColor: evColor(ev.id) }}>
                            <p className="truncate leading-tight">{ev.title}</p>
                            {height > 36 && <p className="opacity-80 text-[10px]">{fmtTime(ev.start_time)}</p>}
                          </button>
                        );
                      })}

                      {/* Current time line */}
                      {isSameDay(day, today) && (() => {
                        const now = new Date();
                        const topPx = (now.getHours() * 60 + now.getMinutes()) / 60 * HOUR_H;
                        return (
                          <div className="absolute inset-x-0 z-20 flex items-center pointer-events-none"
                            style={{ top: topPx }}>
                            <div className="h-2 w-2 rounded-full bg-red-500 ml-0.5 shrink-0" />
                            <div className="flex-1 h-px bg-red-400" />
                          </div>
                        );
                      })()}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* AGENDA VIEW */}
          {view === "agenda" && (
            <div className="flex-1 overflow-y-auto px-4 py-4">
              {events.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-24 text-slate-400">
                  <svg className="h-12 w-12 mb-3 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  <p className="text-sm font-medium text-slate-500">No events yet</p>
                  <p className="text-xs text-slate-400 mt-1">Click + New Event to create one</p>
                </div>
              ) : (() => {
                const sorted = [...events].sort((a, b) =>
                  new Date(a.start_time).getTime() - new Date(b.start_time).getTime()
                );
                const groups = new Map<string, CalendarEvent[]>();
                for (const ev of sorted) {
                  const key = new Date(ev.start_time).toDateString();
                  if (!groups.has(key)) groups.set(key, []);
                  groups.get(key)!.push(ev);
                }
                return Array.from(groups.entries()).map(([ds, evs]) => {
                  const date = new Date(ds);
                  const isToday = isSameDay(date, today);
                  return (
                    <div key={ds} className="mb-6">
                      <div className="mb-3 flex items-center gap-3">
                        <div className={`flex h-11 w-11 shrink-0 flex-col items-center justify-center rounded-xl ${
                          isToday ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-700"
                        }`}>
                          <span className="text-[10px] font-semibold uppercase leading-none">{DAYS_S[date.getDay()]}</span>
                          <span className="text-lg font-bold leading-none mt-0.5">{date.getDate()}</span>
                        </div>
                        <div>
                          <p className="text-sm font-semibold text-slate-800">
                            {MONTHS_S[date.getMonth()]} {date.getDate()}, {date.getFullYear()}
                          </p>
                          {isToday && <p className="text-xs font-medium text-indigo-600">Today</p>}
                        </div>
                      </div>
                      <div className="space-y-2 pl-14">
                        {evs.map(ev => (
                          <button key={ev.id}
                            onClick={() => setSelectedEvent(ev)}
                            className="w-full rounded-xl border border-slate-100 bg-white p-3 text-left shadow-sm hover:shadow-md hover:border-slate-200 transition-all">
                            <div className="flex items-start gap-3">
                              <div className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: evColor(ev.id) }} />
                              <div className="flex-1 min-w-0">
                                <p className="text-sm font-medium text-slate-800 truncate">{ev.title}</p>
                                <p className="text-xs text-slate-500 mt-0.5">
                                  {fmtTime(ev.start_time)} – {fmtTime(ev.end_time)}
                                  {ev.attendees.length > 0 && ` · ${ev.attendees.length} attendee${ev.attendees.length !== 1 ? "s" : ""}`}
                                </p>
                              </div>
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          )}
        </div>

        {/* ── Event detail panel ──────────────────────────────────────── */}
        {selectedEvent && (
          <div className="w-72 shrink-0 border-l border-slate-200 bg-white flex flex-col overflow-hidden">
            <div className="flex items-start justify-between border-b border-slate-200 px-4 py-3 shrink-0">
              <div className="flex items-center gap-2 min-w-0">
                <div className="h-3 w-3 shrink-0 rounded-full mt-0.5" style={{ backgroundColor: evColor(selectedEvent.id) }} />
                <h3 className="text-sm font-semibold text-slate-800 truncate">{selectedEvent.title}</h3>
              </div>
              <button onClick={() => setSelectedEvent(null)} className="shrink-0 ml-2 text-slate-400 hover:text-slate-600">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-xs text-slate-600">
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  {fmtDate(selectedEvent.start_time)}
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-600">
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {fmtTime(selectedEvent.start_time)} – {fmtTime(selectedEvent.end_time)}
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-600">
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                  Organized by <span className="font-medium text-slate-700 ml-1">{selectedEvent.creator_username}</span>
                </div>
              </div>

              {selectedEvent.description && (
                <p className="text-xs text-slate-600 whitespace-pre-wrap leading-relaxed bg-slate-50 rounded-lg p-3">
                  {selectedEvent.description}
                </p>
              )}

              {myStatus(selectedEvent) !== null && (
                <div>
                  <p className="mb-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Your RSVP</p>
                  <div className="flex gap-2">
                    <button onClick={() => handleRSVP(selectedEvent.id, "accepted")}
                      className={`flex-1 rounded-lg py-1.5 text-xs font-medium transition-colors ${
                        myStatus(selectedEvent) === "accepted" ? "bg-emerald-600 text-white" : "bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                      }`}>
                      ✓ Accept
                    </button>
                    <button onClick={() => handleRSVP(selectedEvent.id, "declined")}
                      className={`flex-1 rounded-lg py-1.5 text-xs font-medium transition-colors ${
                        myStatus(selectedEvent) === "declined" ? "bg-red-500 text-white" : "bg-red-50 text-red-600 hover:bg-red-100"
                      }`}>
                      ✗ Decline
                    </button>
                  </div>
                </div>
              )}

              <div>
                <p className="mb-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">Video</p>
                {selectedEvent.room_name ? (
                  <Link href={`/huddle/${selectedEvent.room_name}`}
                    className="flex items-center justify-center gap-2 w-full rounded-lg bg-indigo-600 py-2 text-xs font-medium text-white hover:bg-indigo-700">
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    Join meeting
                  </Link>
                ) : selectedEvent.created_by === user.id ? (
                  <button onClick={() => addRoom(selectedEvent)}
                    className="w-full rounded-lg border border-dashed border-slate-300 py-2 text-xs text-slate-500 hover:bg-slate-50 hover:border-slate-400 transition-colors">
                    + Add video room
                  </button>
                ) : (
                  <p className="text-xs text-slate-400">No video room</p>
                )}
              </div>

              <div>
                <p className="mb-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wide">
                  Attendees ({selectedEvent.attendees.length})
                </p>
                <div className="space-y-1.5">
                  {selectedEvent.attendees.map(a => (
                    <div key={a.user_id} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold uppercase text-slate-600">
                          {a.username[0]}
                        </div>
                        <span className="text-xs text-slate-700">{a.username}</span>
                      </div>
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${RSVP_COLORS[a.status]}`}>
                        {a.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Meeting Intelligence link */}
              <div>
                <Link href={`/calendar/meeting/${selectedEvent.id}`}
                  className="flex items-center justify-center gap-2 w-full rounded-lg bg-gradient-to-r from-indigo-600 to-violet-600 py-2 text-xs font-semibold text-white hover:from-indigo-700 hover:to-violet-700 transition-all shadow-sm">
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                  </svg>
                  Meeting Intel
                </Link>
              </div>

              {selectedEvent.created_by === user.id && (
                <button onClick={() => deleteEvent(selectedEvent)}
                  className="w-full rounded-lg py-2 text-xs text-red-500 hover:bg-red-50 transition-colors border border-transparent hover:border-red-100">
                  Delete event
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Create event modal ──────────────────────────────────────── */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-2xl flex flex-col overflow-hidden max-h-[90vh]">

            {/* Color accent bar */}
            <div className="h-1 w-full shrink-0 bg-indigo-500" />

            {/* Title row */}
            <div className="flex items-start gap-3 px-5 pt-4 pb-3 shrink-0">
              <input type="text" value={title} onChange={e => setTitle(e.target.value)}
                placeholder="Event title" autoFocus
                className="flex-1 text-lg font-semibold text-slate-900 placeholder:text-slate-300 placeholder:font-normal outline-none bg-transparent" />
              <button onClick={closeCreate}
                className="shrink-0 mt-1 rounded-lg p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors">
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="mx-5 h-px bg-slate-100 shrink-0" />

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-5 py-3 space-y-2.5">

              {/* Date/time card */}
              <div className="rounded-xl border border-slate-200 overflow-hidden">
                {/* Start */}
                <div className="flex items-center gap-3 px-4 py-2.5">
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  <span className="text-xs font-medium text-slate-500 w-8 shrink-0">Start</span>
                  <div className="flex items-center gap-2 flex-wrap">
                    <button type="button"
                      onClick={() => (startDateRef.current as HTMLInputElement & { showPicker?: () => void })?.showPicker?.() ?? startDateRef.current?.click()}
                      className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 transition-colors">
                      {fmtDisplayDate(startDate)}
                    </button>
                    <input ref={startDateRef} type="date" value={startDate}
                      onChange={e => { setStartDate(e.target.value); if (!endDate || endDate < e.target.value) setEndDate(e.target.value); }}
                      className="sr-only" />
                    <TimePickerBtn h={startH} m={startM} ap={startAP}
                      onChange={(h, m, ap) => { setStartH(h); setStartM(m); setStartAP(ap); }} />
                  </div>
                </div>
                <div className="mx-4 h-px bg-slate-100" />
                {/* End */}
                <div className="flex items-center gap-3 px-4 py-2.5">
                  <svg className="h-3.5 w-3.5 shrink-0 text-transparent" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path d="M8 7V3m8 4V3m-9 8h10M5 21h14" />
                  </svg>
                  <span className="text-xs font-medium text-slate-500 w-8 shrink-0">End</span>
                  <div className="flex items-center gap-2 flex-wrap">
                    <button type="button"
                      onClick={() => (endDateRef.current as HTMLInputElement & { showPicker?: () => void })?.showPicker?.() ?? endDateRef.current?.click()}
                      className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-200 transition-colors">
                      {fmtDisplayDate(endDate)}
                    </button>
                    <input ref={endDateRef} type="date" value={endDate} min={startDate}
                      onChange={e => setEndDate(e.target.value)}
                      className="sr-only" />
                    <TimePickerBtn h={endH} m={endM} ap={endAP}
                      onChange={(h, m, ap) => { setEndH(h); setEndM(m); setEndAP(ap); }} />
                  </div>
                </div>
              </div>

              {/* Description */}
              <div className="flex items-start gap-3 rounded-xl border border-slate-200 px-4 py-2.5">
                <svg className="h-3.5 w-3.5 shrink-0 mt-0.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h12M4 18h8" />
                </svg>
                <textarea value={description} onChange={e => setDescription(e.target.value)}
                  placeholder="Add a description…" rows={2}
                  className="flex-1 resize-none bg-transparent text-sm text-slate-700 placeholder:text-slate-400 outline-none" />
              </div>

              {/* Video room toggle */}
              <div className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-2.5">
                <div className="flex items-center gap-3">
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                  <div>
                    <p className="text-sm font-medium text-slate-700">Video room</p>
                    <p className="text-xs text-slate-400">A meeting link will be created</p>
                  </div>
                </div>
                <button onClick={() => setWithVideo(v => !v)}
                  className={`relative h-5 w-9 rounded-full transition-colors duration-200 ${withVideo ? "bg-indigo-600" : "bg-slate-200"}`}>
                  <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${withVideo ? "translate-x-4" : ""}`} />
                </button>
              </div>

              {/* Recurrence */}
              <div className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-2.5">
                <div className="flex items-center gap-3">
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  <p className="text-sm font-medium text-slate-700">Repeat</p>
                </div>
                <div className="flex gap-1">
                  {(["none", "daily", "weekly", "monthly"] as const).map(r => (
                    <button key={r} type="button" onClick={() => setRecurrence(r)}
                      className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors capitalize ${
                        recurrence === r
                          ? "bg-indigo-600 text-white"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                      }`}>
                      {r === "none" ? "Off" : r}
                    </button>
                  ))}
                </div>
              </div>

              {/* Invite people */}
              <div className="rounded-xl border border-slate-200 overflow-hidden">
                <div className="px-4 py-2.5">
                  <div className="flex items-center gap-2 mb-1">
                    <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0" />
                    </svg>
                    <span className="text-sm font-medium text-slate-700">Invite people</span>
                  </div>
                  {invited.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {invited.map(u => (
                        <div key={u.id} className="flex items-center gap-1 rounded-full bg-indigo-50 border border-indigo-100 pl-1 pr-1.5 py-0.5">
                          <div className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-[8px] font-bold text-white uppercase">
                            {u.username[0]}
                          </div>
                          <span className="text-xs font-medium text-indigo-700">{u.username}</span>
                          <button onClick={() => setInvited(prev => prev.filter(i => i.id !== u.id))}
                            className="text-indigo-300 hover:text-indigo-600 transition-colors ml-0.5">
                            <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="h-px bg-slate-100" />
                <div className="flex items-center gap-2 px-4 py-2">
                  <svg className="h-3.5 w-3.5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                  <input type="search" value={inviteSearch} onChange={e => setInviteSearch(e.target.value)}
                    placeholder="Search by name or email…"
                    className="flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400 text-slate-700" />
                </div>
                {inviteSearch.length > 0 && (() => {
                  const matches = orgUsers.filter(u =>
                    !invited.some(i => i.id === u.id) && (
                      u.username.toLowerCase().includes(inviteSearch.toLowerCase()) ||
                      u.email.toLowerCase().includes(inviteSearch.toLowerCase())
                    )
                  );
                  return (
                    <div className="max-h-32 overflow-y-auto border-t border-slate-100">
                      {matches.length === 0
                        ? <p className="px-4 py-2.5 text-xs text-slate-400">No users found</p>
                        : matches.map(u => (
                          <button key={u.id}
                            onClick={() => { setInvited(prev => [...prev, u]); setInviteSearch(""); }}
                            className="flex items-center gap-3 w-full px-4 py-2 hover:bg-slate-50 text-left transition-colors">
                            <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-bold uppercase text-slate-600">
                              {u.username[0]}
                            </div>
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-slate-700">{u.username}</p>
                              <p className="text-xs text-slate-400 truncate">{u.email}</p>
                            </div>
                          </button>
                        ))
                      }
                    </div>
                  );
                })()}
              </div>

            </div>

            {/* Footer */}
            <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 shrink-0">
              <button onClick={closeCreate}
                className="rounded-lg px-3 py-2 text-sm text-slate-500 hover:bg-slate-100 transition-colors">
                Cancel
              </button>
              <button onClick={handleCreate} disabled={creating || !title.trim() || !startDate || !endDate}
                className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40 transition-colors">
                {creating ? "Creating…" : (
                  <>
                    Create Event
                    <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M13 7l5 5m0 0l-5 5m5-5H6" />
                    </svg>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
