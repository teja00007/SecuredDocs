"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import { getAccessToken, isAuthenticated } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Attendee {
  user_id: string;
  username: string;
  status: "pending" | "accepted" | "declined";
}

interface CalendarEvent {
  id: string;
  title: string;
  description: string | null;
  location: string | null;
  start_time: string;
  end_time: string;
  created_by: string;
  creator_username: string;
  attendees: Attendee[];
  room_name: string | null;
}

interface TranscriptData {
  meeting_notes: string | null;
  transcript_document_id: string | null;
  summary_document_id: string | null;
}

interface AgendaData {
  agenda: string;
  relevant_doc_count: number;
  sources: { document_id: string; filename: string }[];
}

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources: { document_id: string; filename: string; score: number; chunk_text: string }[] | null;
  streaming?: boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Simple markdown → HTML renderer (handles bold, italic, bullet lists, headers, code blocks)
function renderMarkdown(md: string): string {
  let html = md
    // Escape HTML to prevent injection
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    // Fenced code blocks
    .replace(/```[\s\S]*?```/g, (m) => `<pre class="rounded-lg bg-slate-900 text-slate-100 p-3 text-xs overflow-x-auto my-2 whitespace-pre-wrap">${m.slice(3, -3)}</pre>`)
    // Inline code
    .replace(/`([^`]+)`/g, '<code class="rounded bg-slate-100 px-1 py-0.5 text-xs font-mono text-slate-800">$1</code>')
    // Headers
    .replace(/^### (.+)$/gm, '<h3 class="text-sm font-bold text-slate-800 mt-3 mb-1">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="text-base font-bold text-slate-900 mt-4 mb-1.5">$1</h2>')
    .replace(/^# (.+)$/gm, '<h1 class="text-lg font-bold text-slate-900 mt-4 mb-2">$1</h1>')
    // Bold + italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Bullet lists
    .replace(/^- (.+)$/gm, '<li class="ml-4 list-disc text-sm text-slate-700">$1</li>')
    .replace(/^(\d+)\. (.+)$/gm, '<li class="ml-4 list-decimal text-sm text-slate-700">$2</li>')
    // Horizontal rule
    .replace(/^---$/gm, '<hr class="my-3 border-slate-200" />')
    // Paragraphs (double newlines)
    .replace(/\n\n/g, '</p><p class="text-sm text-slate-700 mt-2">')
    // Single line breaks
    .replace(/\n/g, "<br />");

  return `<p class="text-sm text-slate-700">${html}</p>`;
}

function MarkdownBlock({ content }: { content: string }) {
  return (
    <div
      className="prose-sm max-w-none"
      dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
    />
  );
}

// ── Section card wrapper ───────────────────────────────────────────────────────
function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      <div className="flex items-center gap-2.5 border-b border-slate-100 px-5 py-3.5">
        <span className="text-indigo-600">{icon}</span>
        <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
      </div>
      <div className="px-5 py-4">{children}</div>
    </div>
  );
}

// ── Mini RAG chat ──────────────────────────────────────────────────────────────
function MeetingChat({
  transcriptDocId,
  summaryDocId,
}: {
  transcriptDocId: string | null;
  summaryDocId: string | null;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [convId, setConvId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Use the summary doc's collection as the scoping context (if available)
  // We pass it via the conversation's collection_id
  const collectionId: string | null = null; // meeting docs aren't in a collection by default

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");

    // Create conversation if first message
    let activeConvId = convId;
    if (!activeConvId) {
      try {
        const conv = await api.post<{ id: string }>("/api/v1/conversations", {
          title: `Meeting Q&A`,
          collection_id: collectionId,
        });
        activeConvId = conv.id;
        setConvId(conv.id);
      } catch {
        return;
      }
    }

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: text,
      sources: null,
    };
    const streamMsg: ChatMessage = {
      id: `s-${Date.now()}`,
      role: "assistant",
      content: "",
      sources: null,
      streaming: true,
    };
    setMessages((prev) => [...prev, userMsg, streamMsg]);
    setLoading(true);

    const token = getAccessToken();
    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const res = await fetch(`/sse/${activeConvId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ query: text, top_k: 5 }),
        signal: ac.signal,
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          const line = part.startsWith("data: ") ? part.slice(6) : part;
          if (!line.trim()) continue;
          try {
            const data = JSON.parse(line);
            if (data.type === "token") {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.streaming) updated[updated.length - 1] = { ...last, content: last.content + data.token };
                return updated;
              });
            } else if (data.type === "done") {
              setMessages((prev) => {
                const updated = [...prev];
                const last = updated[updated.length - 1];
                if (last?.streaming) {
                  updated[updated.length - 1] = {
                    ...last,
                    streaming: false,
                    sources: data.sources ?? null,
                    id: data.message_id ?? last.id,
                  };
                }
                return updated;
              });
            }
          } catch {}
        }
      }
    } catch (err: unknown) {
      if ((err as { name?: string }).name === "AbortError") return;
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last?.streaming) {
          updated[updated.length - 1] = {
            ...last,
            streaming: false,
            content: last.content || "An error occurred. Please try again.",
          };
        }
        return updated;
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {/* No docs warning */}
      {!transcriptDocId && !summaryDocId && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-xs text-amber-700">
          Upload a transcript first to enable meeting-scoped Q&amp;A. Questions will use the global knowledge base.
        </div>
      )}

      {/* Message history */}
      {messages.length > 0 && (
        <div className="max-h-80 overflow-y-auto flex flex-col gap-3 pr-1">
          {messages.map((m) => (
            <div
              key={m.id}
              className={`flex gap-2.5 ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {m.role === "assistant" && (
                <div className="h-6 w-6 shrink-0 rounded-full bg-indigo-600 flex items-center justify-center text-white text-[10px] font-bold mt-0.5">
                  N
                </div>
              )}
              <div
                className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                  m.role === "user"
                    ? "bg-indigo-600 text-white rounded-tr-sm"
                    : "bg-slate-100 text-slate-800 rounded-tl-sm"
                }`}
              >
                {m.streaming ? (
                  <span>
                    {m.content}
                    <span className="inline-block ml-0.5 h-3.5 w-0.5 bg-slate-500 animate-pulse rounded-full" />
                  </span>
                ) : m.role === "assistant" ? (
                  <MarkdownBlock content={m.content} />
                ) : (
                  m.content
                )}
                {m.sources && m.sources.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {m.sources.map((s, i) => (
                      <span
                        key={i}
                        className="inline-block rounded-full bg-white border border-slate-200 px-2 py-0.5 text-[10px] text-slate-500"
                      >
                        {s.filename}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {m.role === "user" && (
                <div className="h-6 w-6 shrink-0 rounded-full bg-slate-200 flex items-center justify-center text-slate-600 text-[10px] font-bold mt-0.5">
                  Y
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}

      {/* Input */}
      <div className="flex gap-2 items-end">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              sendMessage();
            }
          }}
          placeholder="Ask about this meeting…"
          rows={2}
          className="flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-800 placeholder:text-slate-400 outline-none focus:border-indigo-400 focus:bg-white transition-colors"
        />
        <button
          onClick={sendMessage}
          disabled={loading || !input.trim()}
          className="h-10 w-10 shrink-0 rounded-xl bg-indigo-600 text-white flex items-center justify-center hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          aria-label="Send"
        >
          <svg className="h-4 w-4 rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
          </svg>
        </button>
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────

export default function MeetingIntelPage() {
  const params = useParams();
  const router = useRouter();
  const eventId = params.eventId as string;

  const [event, setEvent] = useState<CalendarEvent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Transcript section state
  const [transcriptData, setTranscriptData] = useState<TranscriptData | null>(null);
  const [transcriptStatus, setTranscriptStatus] = useState<
    "idle" | "uploading" | "processing" | "done" | "error"
  >("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [transcriptError, setTranscriptError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Agenda section state
  const [agendaData, setAgendaData] = useState<AgendaData | null>(null);
  const [agendaContext, setAgendaContext] = useState("");
  const [agendaLoading, setAgendaLoading] = useState(false);
  const [agendaError, setAgendaError] = useState<string | null>(null);

  // Auth guard
  useEffect(() => {
    if (!isAuthenticated()) router.replace("/login");
  }, [router]);

  // Load event
  useEffect(() => {
    if (!eventId) return;
    setLoading(true);
    api
      .get<CalendarEvent>(`/api/v1/calendar/events/${eventId}`)
      .then((ev) => {
        setEvent(ev);
        setLoading(false);
      })
      .catch((err: unknown) => {
        const e = err as ApiError;
        setError(e.message || "Failed to load event");
        setLoading(false);
      });
  }, [eventId]);

  // Load existing transcript data
  useEffect(() => {
    if (!eventId) return;
    api
      .get<TranscriptData>(`/api/v1/calendar/events/${eventId}/transcript`)
      .then((data) => {
        setTranscriptData(data);
        if (data.transcript_document_id || data.summary_document_id) {
          setTranscriptStatus("done");
        }
      })
      .catch(() => {
        // 404 means no transcript yet — that's fine
        setTranscriptStatus("idle");
      });
  }, [eventId]);

  // Load existing agenda
  useEffect(() => {
    if (!eventId) return;
    api
      .get<AgendaData>(`/api/v1/calendar/events/${eventId}/agenda`)
      .then((data) => setAgendaData(data))
      .catch(() => {
        // 404 means no agenda yet
      });
  }, [eventId]);

  // Poll for transcript completion
  const startPolling = useCallback(() => {
    if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    pollTimerRef.current = setInterval(async () => {
      try {
        const data = await api.get<TranscriptData>(
          `/api/v1/calendar/events/${eventId}/transcript`
        );
        if (data.transcript_document_id || data.summary_document_id || data.meeting_notes) {
          setTranscriptData(data);
          setTranscriptStatus("done");
          if (pollTimerRef.current) clearInterval(pollTimerRef.current);
        }
      } catch {
        // still processing or not ready
      }
    }, 4000);
  }, [eventId]);

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearInterval(pollTimerRef.current);
    };
  }, []);

  // Upload transcript
  async function handleUpload(file: File) {
    setTranscriptError(null);
    setTranscriptStatus("uploading");
    setUploadProgress(0);

    const formData = new FormData();
    formData.append("file", file);

    try {
      await api.uploadWithProgress<{ status: string }>(
        `/api/v1/calendar/events/${eventId}/transcript`,
        formData,
        (pct) => setUploadProgress(pct),
      );
      setTranscriptStatus("processing");
      startPolling();
    } catch (err: unknown) {
      const e = err as ApiError;
      setTranscriptError(e.message || "Upload failed");
      setTranscriptStatus("error");
    }
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
    e.target.value = "";
  }

  function onDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  }

  // Generate agenda
  async function handleGenerateAgenda() {
    setAgendaError(null);
    setAgendaLoading(true);
    try {
      const data = await api.post<AgendaData>(
        `/api/v1/calendar/events/${eventId}/agenda`,
        { context: agendaContext || null },
      );
      setAgendaData(data);
    } catch (err: unknown) {
      const e = err as ApiError;
      setAgendaError(e.message || "Agenda generation failed");
    } finally {
      setAgendaLoading(false);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-[3px] border-slate-200 border-t-indigo-600" />
      </div>
    );
  }

  if (error || !event) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-slate-500">
        <p className="text-sm">{error || "Event not found"}</p>
        <Link href="/calendar" className="text-sm font-medium text-indigo-600 hover:underline">
          Back to Calendar
        </Link>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-slate-50">
      {/* ── Top nav ── */}
      <div className="flex shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-5 py-3">
        <Link
          href="/calendar"
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-500 hover:bg-slate-100 hover:text-slate-800 transition-colors"
        >
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          Calendar
        </Link>
        <span className="text-slate-300">/</span>
        <span className="text-sm font-semibold text-slate-800 truncate">{event.title}</span>
        <span className="ml-auto rounded-full bg-indigo-50 px-2.5 py-0.5 text-[11px] font-semibold text-indigo-700 border border-indigo-100">
          Meeting Intelligence
        </span>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-5 md:px-8 md:py-7">
        <div className="mx-auto max-w-3xl space-y-5">

          {/* ── 1. Event Header ── */}
          <Section
            title="Event Details"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
            }
          >
            <div className="space-y-2.5">
              <h1 className="text-xl font-bold text-slate-900">{event.title}</h1>
              <div className="flex flex-wrap gap-x-6 gap-y-1.5 text-sm text-slate-600">
                <span className="flex items-center gap-1.5">
                  <svg className="h-3.5 w-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                  {fmtDate(event.start_time)}
                </span>
                <span className="flex items-center gap-1.5">
                  <svg className="h-3.5 w-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  {fmtTime(event.start_time)} &ndash; {fmtTime(event.end_time)}
                </span>
                {event.location && (
                  <span className="flex items-center gap-1.5">
                    <svg className="h-3.5 w-3.5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    {event.location}
                  </span>
                )}
              </div>
              {event.description && (
                <p className="text-sm text-slate-600 leading-relaxed">{event.description}</p>
              )}
              {/* Attendees */}
              {event.attendees.length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {event.attendees.map((a) => (
                    <div
                      key={a.user_id}
                      className="flex items-center gap-1.5 rounded-full bg-slate-100 pl-1 pr-2.5 py-0.5"
                    >
                      <div className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-600 text-[9px] font-bold text-white uppercase">
                        {a.username[0]}
                      </div>
                      <span className="text-xs font-medium text-slate-700">{a.username}</span>
                      <span
                        className={`text-[10px] font-medium ${
                          a.status === "accepted"
                            ? "text-emerald-600"
                            : a.status === "declined"
                            ? "text-red-500"
                            : "text-slate-400"
                        }`}
                      >
                        {a.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Section>

          {/* ── 2. Upload Transcript ── */}
          <Section
            title="Upload Transcript"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            }
          >
            {transcriptStatus === "done" ? (
              <div className="flex items-center gap-3 rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3">
                <svg className="h-5 w-5 text-emerald-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-emerald-800">Transcript processed</p>
                  <p className="text-xs text-emerald-600 mt-0.5">AI summary and transcript have been indexed for RAG search.</p>
                </div>
                <button
                  onClick={() => {
                    setTranscriptStatus("idle");
                    setTranscriptData(null);
                  }}
                  className="shrink-0 text-xs text-emerald-700 hover:text-emerald-900 font-medium underline"
                >
                  Re-upload
                </button>
              </div>
            ) : transcriptStatus === "processing" ? (
              <div className="flex items-center gap-3 rounded-xl bg-indigo-50 border border-indigo-200 px-4 py-3">
                <div className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-600" />
                <div>
                  <p className="text-sm font-semibold text-indigo-800">Processing…</p>
                  <p className="text-xs text-indigo-600 mt-0.5">
                    Transcribing audio and generating AI summary. This may take a few minutes.
                  </p>
                </div>
              </div>
            ) : transcriptStatus === "uploading" ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-slate-600">
                  <span>Uploading…</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-indigo-600 transition-all"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                {transcriptError && (
                  <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
                    {transcriptError}
                  </div>
                )}
                <div
                  onDrop={onDrop}
                  onDragOver={(e) => e.preventDefault()}
                  onClick={() => fileInputRef.current?.click()}
                  className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-300 px-6 py-8 text-center transition-colors hover:border-indigo-400 hover:bg-indigo-50/50"
                >
                  <svg className="h-8 w-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3" />
                  </svg>
                  <div>
                    <p className="text-sm font-medium text-slate-700">Drop audio file here or click to browse</p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      Supports MP3, MP4, WAV, M4A, OGG, WebM (LiveKit recordings)
                    </p>
                  </div>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".mp3,.mp4,.wav,.m4a,.ogg,.webm,audio/*"
                  className="sr-only"
                  onChange={onFileChange}
                />
              </div>
            )}
          </Section>

          {/* ── 3. AI Summary ── */}
          <Section
            title="AI Summary"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            }
          >
            {transcriptStatus === "processing" ? (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-500" />
                Generating AI summary…
              </div>
            ) : transcriptData?.meeting_notes ? (
              <div className="rounded-xl bg-slate-50 border border-slate-200 p-4">
                <MarkdownBlock content={transcriptData.meeting_notes} />
              </div>
            ) : (
              <p className="text-sm text-slate-400 italic">
                No transcript uploaded yet. Upload a meeting recording above to generate an AI summary.
              </p>
            )}
          </Section>

          {/* ── 4. Linked Documents ── */}
          {(transcriptData?.transcript_document_id || transcriptData?.summary_document_id) && (
            <Section
              title="Linked Documents"
              icon={
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                </svg>
              }
            >
              <div className="flex flex-wrap gap-3">
                {transcriptData.transcript_document_id && (
                  <a
                    href={`${API_BASE}/api/v1/documents/${transcriptData.transcript_document_id}/download`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm hover:border-indigo-300 hover:text-indigo-700 transition-colors"
                  >
                    <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    Download Transcript
                  </a>
                )}
                {transcriptData.summary_document_id && (
                  <a
                    href={`${API_BASE}/api/v1/documents/${transcriptData.summary_document_id}/download`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 shadow-sm hover:border-indigo-300 hover:text-indigo-700 transition-colors"
                  >
                    <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                    </svg>
                    Download Summary
                  </a>
                )}
                {transcriptData.transcript_document_id && (
                  <Link
                    href={`/?doc=${transcriptData.transcript_document_id}`}
                    className="flex items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-2.5 text-sm font-medium text-indigo-700 shadow-sm hover:bg-indigo-100 transition-colors"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                    </svg>
                    View in RAG
                  </Link>
                )}
              </div>
            </Section>
          )}

          {/* ── 5. Generate Agenda ── */}
          <Section
            title="Generate Agenda"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 10h16M4 14h10M4 18h6" />
              </svg>
            }
          >
            <div className="space-y-3">
              <p className="text-xs text-slate-500">
                Nexus will search your knowledge base for relevant documents and generate a structured agenda.
              </p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={agendaContext}
                  onChange={(e) => setAgendaContext(e.target.value)}
                  placeholder="Optional: describe what this meeting is about…"
                  className="flex-1 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2.5 text-sm text-slate-700 placeholder:text-slate-400 outline-none focus:border-indigo-400 focus:bg-white transition-colors"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !agendaLoading) handleGenerateAgenda();
                  }}
                />
                <button
                  onClick={handleGenerateAgenda}
                  disabled={agendaLoading}
                  className="shrink-0 flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                >
                  {agendaLoading ? (
                    <>
                      <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                      Generating…
                    </>
                  ) : (
                    <>
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                      </svg>
                      Generate
                    </>
                  )}
                </button>
              </div>

              {agendaError && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
                  {agendaError}
                </div>
              )}

              {agendaData && (
                <div className="space-y-3">
                  {agendaData.sources.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 items-center">
                      <span className="text-[11px] text-slate-400 font-medium mr-1">
                        Based on {agendaData.relevant_doc_count} document{agendaData.relevant_doc_count !== 1 ? "s" : ""}:
                      </span>
                      {agendaData.sources.slice(0, 5).map((s) => (
                        <span
                          key={s.document_id}
                          className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600 border border-slate-200"
                        >
                          {s.filename}
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="rounded-xl bg-slate-50 border border-slate-200 p-4">
                    <MarkdownBlock content={agendaData.agenda} />
                  </div>
                </div>
              )}
            </div>
          </Section>

          {/* ── 6. Ask About This Meeting ── */}
          <Section
            title="Ask About This Meeting"
            icon={
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            }
          >
            <MeetingChat
              transcriptDocId={transcriptData?.transcript_document_id ?? null}
              summaryDocId={transcriptData?.summary_document_id ?? null}
            />
          </Section>

        </div>
      </div>
    </div>
  );
}
