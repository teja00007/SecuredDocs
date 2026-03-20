"use client";

import { Suspense, useEffect, useRef, useState, useCallback, FormEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getAccessToken } from "@/lib/auth";
import { api } from "@/lib/api";
import SourceCitation from "@/components/SourceCitation";
import MarkdownMessage from "@/components/MarkdownMessage";
import { useToast } from "@/components/Toast";
import type {
  Collection, Conversation, ConversationDetail,
  ConversationMessage, Source,
} from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function dateSeparator(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "long", day: "numeric", year: "numeric" });
}

interface StreamingMessage extends ConversationMessage {
  streaming?: boolean;
  feedback: number | null;
  confidence_score?: number;
  confidence_label?: string;
  follow_up_questions?: string[];
}

function computeConfidence(sources: Source[]): { score: number; label: string } {
  if (!sources || sources.length === 0) return { score: 0, label: "Uncertain" };
  const avg = sources.reduce((s, src) => s + src.score, 0) / sources.length;
  const score = Math.min(Math.max(avg, 0), 1);
  if (score >= 0.75) return { score, label: "Verified" };
  if (score >= 0.50) return { score, label: "Likely" };
  return { score, label: "Uncertain" };
}

function ConfidenceBadge({ sources, score, label }: { sources: Source[] | null; score?: number; label?: string }) {
  if (!sources || sources.length === 0) return null;
  const conf = (score !== undefined && label) ? { score, label } : computeConfidence(sources);
  const styles: Record<string, string> = {
    Verified: "bg-gray-700 text-white",
    Likely:   "bg-gray-500 text-white",
    Uncertain:"bg-gray-200 text-gray-600",
  };
  const icons: Record<string, string> = { Verified: "✓", Likely: "~", Uncertain: "?" };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${styles[conf.label] ?? styles.Uncertain}`}>
      <span>{icons[conf.label] ?? "?"}</span>
      {conf.label}
    </span>
  );
}

function ChatPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { success, info } = useToast();
  const [currentUser, setCurrentUser] = useState<{ username: string } | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [userTeams, setUserTeams] = useState<{ id: string; name: string }[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConv, setActiveConv] = useState<ConversationDetail | null>(null);
  const [messages, setMessages] = useState<StreamingMessage[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [activeCollectionId, setActiveCollectionId] = useState<string | null>(null);
  const [activeScope, setActiveScope] = useState<string>("all");
  const [showScrollBtn, setShowScrollBtn] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const titleInputRef = useRef<HTMLInputElement>(null);
  const [showExportMenu, setShowExportMenu] = useState(false);
  const exportMenuRef = useRef<HTMLDivElement>(null);

  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Mirrors activeConv.id synchronously — updated alongside every setActiveConv call
  // so the searchParams effect can read the latest value without relying on stale state
  // (avoids the React StrictMode double-invocation problem with "consume once" refs).
  const activeConvIdRef = useRef<string | null>(null);

  // Warn the user if they try to close/reload the tab during streaming
  useEffect(() => {
    if (!isLoading) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [isLoading]);

  // On unmount, don't hard-abort an active stream — let the backend finish
  // generating and persist the message. Only cancel non-streaming requests.
  useEffect(() => {
    return () => {
      // If actively streaming, let it complete in background (backend will save it).
      // Only abort if it's a pre-stream request (loading=true but no content yet isn't
      // distinguishable here, so we skip the abort entirely — AbortControllers are
      // cleaned up by the GC once the component is gone).
    };
  }, []);

  // Load collections + conversations once on mount
  useEffect(() => {
    const collectionParam = searchParams.get("collection");
    Promise.all([
      api.get<Collection[]>("/api/v1/collections"),
      api.get<Conversation[]>("/api/v1/conversations"),
      api.get<{ username: string; teams: string[] }>("/api/v1/auth/me"),
      api.get<{ id: string; name: string }[]>("/api/v1/teams"),
    ]).then(([cols, convs, me, teams]) => {
      setCollections(cols);
      setConversations(convs);
      setCurrentUser(me);
      // Only show teams the user is a member of
      const myTeamIds = new Set(me.teams ?? []);
      setUserTeams(teams.filter((t) => myTeamIds.has(t.id)));
      // Pre-select collection from query param (e.g. ?collection=<id> from collections page)
      if (collectionParam && cols.some(c => c.id === collectionParam)) {
        setActiveCollectionId(collectionParam);
      }
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist active conversation ID so we can restore it when navigating back via sidebar
  useEffect(() => {
    if (activeConv?.id) {
      localStorage.setItem("nexus_last_conv_id", activeConv.id);
    }
  }, [activeConv?.id]);

  // React to ?conv=<id> param changes (sidebar navigation)
  useEffect(() => {
    const convId = searchParams.get("conv");

    // No conv param (e.g. user clicked "Chat" icon in sidebar which links to "/"):
    // restore the last active conversation from localStorage.
    if (!convId) {
      const lastConvId = localStorage.getItem("nexus_last_conv_id");
      if (lastConvId) {
        router.replace(`/?conv=${lastConvId}`);
      }
      return;
    }

    // We navigated here ourselves (sendMessage / newConversation) — already have
    // the correct messages in state, don't reload and wipe the streaming reply.
    // activeConvIdRef mirrors activeConv.id synchronously so this check is
    // idempotent and safe under React StrictMode double-invocation.
    if (activeConvIdRef.current === convId) return;
    // Abort any in-progress stream — prevents two streams running at once and
    // corrupting each other's messages. The backend saves via its finally block.
    abortRef.current?.abort();
    setIsLoading(false);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    const loadConv = (id: string, retry = false) => {
      api.get<ConversationDetail>(`/api/v1/conversations/${id}`)
        .then((detail) => {
          activeConvIdRef.current = detail.id;
          setActiveConv(detail);
          setMessages(detail.messages);
          setActiveCollectionId(detail.collection_id ?? null);
          setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "instant" }), 50);
          // If the last message is from the user (assistant reply not yet in DB),
          // the backend's finally block may still be committing — retry once.
          if (!retry) {
            const last = detail.messages[detail.messages.length - 1];
            if (last?.role === "user") {
              setTimeout(() => loadConv(id, true), 1500);
            }
          }
        })
        .catch(() => {});
    };
    loadConv(convId);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Auto-scroll to bottom when new messages arrive (only if near bottom)
  useEffect(() => {
    const el = scrollAreaRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
    if (nearBottom) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Show scroll-to-bottom button when user scrolls up
  const handleScroll = useCallback(() => {
    const el = scrollAreaRef.current;
    if (!el) return;
    setShowScrollBtn(el.scrollHeight - el.scrollTop - el.clientHeight > 200);
  }, []);

  // ⌘N / Ctrl+N → new conversation
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        newConversation();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeCollectionId]);

  function scrollToBottom() {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }

  async function newConversation() {
    abortRef.current?.abort();
    setIsLoading(false);
    const conv = await api.post<Conversation>("/api/v1/conversations", {
      title: "New conversation",
      collection_id: activeCollectionId ?? undefined,
    });
    setConversations((prev) => [conv, ...prev]);
    activeConvIdRef.current = conv.id;
    setActiveConv({ ...conv, messages: [] });
    setMessages([]);
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    router.replace(`/?conv=${conv.id}`);
  }

  async function deleteConversation(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("Delete this conversation?")) return;
    await api.delete(`/api/v1/conversations/${id}`);
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeConv?.id === id) {
      activeConvIdRef.current = null;
      setActiveConv(null);
      setMessages([]);
      router.replace("/");
    }
  }

  function copyMessage(id: string, content: string) {
    navigator.clipboard.writeText(content).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    });
  }

  function startRenameConv() {
    if (!activeConv) return;
    setTitleDraft(activeConv.title);
    setEditingTitle(true);
    setTimeout(() => titleInputRef.current?.select(), 10);
  }

  async function saveRenameConv(e?: FormEvent) {
    e?.preventDefault();
    if (!activeConv || !titleDraft.trim()) { setEditingTitle(false); return; }
    const newTitle = titleDraft.trim();
    if (newTitle === activeConv.title) { setEditingTitle(false); return; }
    await api.patch(`/api/v1/conversations/${activeConv.id}/title`, { title: newTitle });
    setActiveConv((prev) => prev ? { ...prev, title: newTitle } : prev);
    setConversations((prev) => prev.map((c) => c.id === activeConv.id ? { ...c, title: newTitle } : c));
    setEditingTitle(false);
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";

    let conv = activeConv;
    if (!conv) {
      const newConv = await api.post<Conversation>("/api/v1/conversations", {
        title: text.slice(0, 60),
        collection_id: activeCollectionId ?? undefined,
      });
      const detail: ConversationDetail = { ...newConv, messages: [] };
      setConversations((prev) => [newConv, ...prev]);
      activeConvIdRef.current = newConv.id;
      setActiveConv(detail);
      router.replace(`/?conv=${newConv.id}`);
      conv = detail;
    }

    const tempUser: StreamingMessage = {
      id: `tmp-${Date.now()}`,
      role: "user",
      content: text,
      sources: null,
      feedback: null,
      created_at: new Date().toISOString(),
    };
    const tempAssistant: StreamingMessage = {
      id: `stream-${Date.now()}`,
      role: "assistant",
      content: "",
      sources: null,
      feedback: null,
      created_at: new Date().toISOString(),
      streaming: true,
    };
    setMessages((prev) => [...prev, tempUser, tempAssistant]);
    setIsLoading(true);

    const token = getAccessToken();
    const ac = new AbortController();
    abortRef.current = ac;

    try {
      const response = await fetch(
        `/sse/${conv.id}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ query: text, top_k: 5, scope: activeScope }),
          signal: ac.signal,
        },
      );

      if (!response.ok || !response.body) {
        const err = await response.text();
        throw new Error(err || `HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
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
                const msgs = [...prev];
                const last = msgs[msgs.length - 1];
                if (last?.streaming) {
                  msgs[msgs.length - 1] = { ...last, content: last.content + data.content };
                }
                return msgs;
              });
            } else if (data.type === "done") {
              const sources: Source[] = data.sources ?? [];
              setMessages((prev) => {
                const msgs = [...prev];
                const last = msgs[msgs.length - 1];
                if (last?.streaming) {
                  msgs[msgs.length - 1] = {
                    ...last,
                    streaming: false,
                    sources,
                    confidence_score: data.confidence_score,
                    confidence_label: data.confidence_label,
                    follow_up_questions: data.follow_up_questions ?? [],
                  };
                }
                return msgs;
              });
            } else if (data.type === "error") {
              throw new Error(data.message ?? "Stream error");
            }
          } catch (parseErr) {
            if (!(parseErr instanceof SyntaxError)) throw parseErr;
            // ignore JSON parse errors from partial/malformed chunks
          }
        }
      }

      // Flush any remaining buffer (edge case: stream closed mid-event)
      if (buffer.trim()) {
        const line = buffer.startsWith("data: ") ? buffer.slice(6) : buffer;
        if (line.trim()) {
          try {
            const data = JSON.parse(line);
            if (data.type === "done") {
              const sources: Source[] = data.sources ?? [];
              setMessages((prev) => {
                const msgs = [...prev];
                const last = msgs[msgs.length - 1];
                if (last?.streaming) {
                  msgs[msgs.length - 1] = { ...last, streaming: false, sources };
                }
                return msgs;
              });
            }
          } catch { /* ignore */ }
        }
      }

      // Ensure any still-streaming message is marked done (guards against missed done event)
      setMessages((prev) => prev.map((m) => m.streaming ? { ...m, streaming: false } : m));

    } catch (err: unknown) {
      if ((err as Error)?.name === "AbortError") return;
      // Keep any content that was streamed — only mark streaming as done, don't delete messages
      setMessages((prev) => {
        const msgs = prev.map((m) => m.streaming ? { ...m, streaming: false } : m);
        const lastMsg = msgs[msgs.length - 1];
        // Only add error bubble if the last assistant message has no content
        if (lastMsg?.role === "assistant" && !lastMsg.content) {
          msgs[msgs.length - 1] = {
            ...lastMsg,
            content: `Something went wrong: ${err instanceof Error ? err.message : "Request failed"}. Please try again.`,
          };
          return msgs;
        }
        return msgs;
      });
    } finally {
      setIsLoading(false);
      abortRef.current = null;
      textareaRef.current?.focus();
      // Reload conversation list (title + updated_at) — outside try/catch so it never
      // triggers the error handler and wipes messages
      api.get<Conversation[]>("/api/v1/conversations")
        .then((updatedConvs) => setConversations(updatedConvs))
        .catch(() => {});
    }
  }

  // Close export dropdown when clicking outside
  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false);
      }
    }
    if (showExportMenu) document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [showExportMenu]);

  function buildMarkdownContent(): string {
    if (!activeConv) return "";
    const lines: string[] = [
      `# Conversation: ${activeConv.title}`,
      `Exported: ${new Date().toLocaleString()}`,
      "",
      "---",
      "",
    ];
    for (const msg of messages) {
      if (msg.streaming) continue;
      if (msg.role === "user") {
        lines.push(`## Q: ${msg.content}`, "");
      } else {
        lines.push(`**A:** ${msg.content}`, "");
        if (msg.sources && msg.sources.length > 0) {
          lines.push("Sources:");
          for (const s of msg.sources) {
            lines.push(`- ${s.filename}${s.page_number != null ? ` (p. ${s.page_number})` : ""}${s.chunk_text ? ` — chunk ${s.chunk_text.slice(0, 30)}…` : ""}`);
          }
          lines.push("");
        }
        lines.push("---", "");
      }
    }
    return lines.join("\n");
  }

  function exportConversation(format: "markdown" | "text" = "markdown") {
    if (!activeConv || messages.length === 0) return;
    setShowExportMenu(false);
    const safeName = activeConv.title.replace(/[^a-z0-9]/gi, "_");

    if (format === "markdown") {
      const content = buildMarkdownContent();
      const blob = new Blob([content], { type: "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${safeName}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } else {
      // Plain text
      const lines: string[] = [`Conversation: ${activeConv.title}`, `Exported: ${new Date().toLocaleString()}`, "", "---", ""];
      for (const msg of messages) {
        if (msg.streaming) continue;
        lines.push(msg.role === "user" ? `You: ${msg.content}` : `Nexus: ${msg.content}`);
        if (msg.sources && msg.sources.length > 0) {
          lines.push("Sources: " + msg.sources.map(s => s.filename).join(", "));
        }
        lines.push("");
      }
      const blob = new Blob([lines.join("\n")], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${safeName}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    }
  }

  async function handleFeedback(messageId: string, feedback: number | null) {
    if (!activeConv) return;
    const params = feedback !== null ? `?feedback=${feedback}` : "";
    await api.patch(
      `/api/v1/conversations/${activeConv.id}/messages/${messageId}/feedback${params}`,
      {},
    );
    setMessages((prev) =>
      prev.map((m) => m.id === messageId ? { ...m, feedback } : m)
    );
    if (feedback === 1) success("Marked as helpful");
    else if (feedback === -1) info("Feedback recorded");
    else info("Feedback removed");
  }

  function handleKeyDown(e: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  }

  // Build messages with date separators
  const messagesWithSeparators = messages.reduce<Array<StreamingMessage | { type: "separator"; label: string; key: string }>>((acc, msg, i) => {
    const prev = messages[i - 1];
    if (!prev || dateSeparator(msg.created_at) !== dateSeparator(prev.created_at)) {
      acc.push({ type: "separator", label: dateSeparator(msg.created_at), key: `sep-${i}` });
    }
    acc.push(msg);
    return acc;
  }, []);

  const activeConvId = searchParams.get("conv");
  const scopedCollection = collections.find((c) => c.id === activeCollectionId);

  return (
    <main className="flex flex-1 flex-col overflow-hidden bg-white">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-2.5 shadow-sm">
        <div className="flex-1 min-w-0">
          {editingTitle ? (
            <form onSubmit={saveRenameConv} className="flex items-center gap-1.5">
              <input
                ref={titleInputRef}
                value={titleDraft}
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={() => saveRenameConv()}
                onKeyDown={(e) => e.key === "Escape" && setEditingTitle(false)}
                className="flex-1 rounded border border-gray-400 px-2 py-0.5 text-sm font-semibold text-gray-900 outline-none focus:ring-2 focus:ring-gray-200 min-w-0"
                maxLength={80}
              />
              <button type="submit" className="text-xs text-gray-700 hover:underline shrink-0">Save</button>
            </form>
          ) : (
            <h2
              className="truncate text-sm font-semibold text-gray-900 cursor-pointer hover:text-gray-600 transition-colors"
              title={activeConv ? "Click to rename" : undefined}
              onClick={activeConv ? startRenameConv : undefined}
            >
              {activeConv?.title ?? "Nexus AI"}
            </h2>
          )}
          {scopedCollection ? (
            <p className="text-xs text-gray-600 flex items-center gap-1">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3 h-3">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
              </svg>
              {scopedCollection.name}
            </p>
          ) : (
            <p className="text-xs text-gray-400">All collections</p>
          )}
        </div>

        {/* Scope picker */}
        <select
          value={activeScope}
          onChange={(e) => setActiveScope(e.target.value)}
          className="hidden sm:block rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-600 outline-none focus:border-gray-500 hover:bg-gray-50"
          title="Search scope"
        >
          <option value="all">All sources</option>
          <option value="personal">Personal</option>
          {userTeams.map((t) => (
            <option key={t.id} value={`team:${t.id}`}>Team: {t.name}</option>
          ))}
        </select>

        {/* Collection picker */}
        <select
          value={activeCollectionId ?? ""}
          onChange={(e) => setActiveCollectionId(e.target.value || null)}
          className="hidden sm:block rounded-lg border border-gray-200 bg-white px-2.5 py-1.5 text-xs text-gray-600 outline-none focus:border-gray-500 hover:bg-gray-50"
        >
          <option value="">All collections</option>
          {collections.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        {activeConv && messages.length > 0 && (
          <div className="relative" ref={exportMenuRef}>
            <button
              onClick={() => setShowExportMenu(v => !v)}
              title="Export conversation"
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 transition-colors flex items-center gap-1"
            >
              <span>↓</span> Export
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-3 h-3 ml-0.5">
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {showExportMenu && (
              <div className="absolute right-0 top-full mt-1 z-50 w-44 rounded-xl border border-gray-200 bg-white shadow-xl py-1">
                <button
                  onClick={() => exportConversation("markdown")}
                  className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  <span className="text-base">📄</span>
                  <div>
                    <p className="text-xs font-medium">Export as Markdown</p>
                    <p className="text-[10px] text-gray-400">.md file</p>
                  </div>
                </button>
                <button
                  onClick={() => exportConversation("text")}
                  className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                >
                  <span className="text-base">📝</span>
                  <div>
                    <p className="text-xs font-medium">Export as Text</p>
                    <p className="text-[10px] text-gray-400">.txt file</p>
                  </div>
                </button>
              </div>
            )}
          </div>
        )}
        <button
          onClick={newConversation}
          className="rounded-lg bg-gray-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-gray-600 transition-colors"
        >
          + New chat
        </button>
      </div>

      {/* Message area */}
      <div
        ref={scrollAreaRef}
        onScroll={handleScroll}
        className="relative flex-1 overflow-y-auto px-4 py-6"
      >
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-gray-400">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gray-700 shadow-lg">
              <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" className="h-7 w-7">
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
              </svg>
            </div>
            <p className="mt-4 text-lg font-semibold text-gray-900">Ask Nexus anything</p>
            <p className="mt-1 text-sm text-gray-400 text-center max-w-xs">
              Get answers, summarize documents, or search your knowledge base.
            </p>
            <div className="mt-6 grid grid-cols-2 gap-2 w-full max-w-sm">
              {[
                "Summarize the latest report",
                "What is our refund policy?",
                "Explain this quarter's numbers",
                "Who do I contact for IT support?",
              ].map((hint) => (
                <button
                  key={hint}
                  onClick={() => { setInput(hint); textareaRef.current?.focus(); }}
                  className="rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-left text-xs text-gray-600 hover:border-gray-400 hover:bg-gray-50 transition-colors shadow-sm"
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-2xl space-y-1">
            {messagesWithSeparators.map((item) => {
              if ("type" in item && item.type === "separator") {
                return (
                  <div key={item.key} className="flex items-center gap-3 py-3">
                    <div className="flex-1 h-px bg-gray-200" />
                    <span className="text-[11px] text-gray-400 font-medium">{item.label}</span>
                    <div className="flex-1 h-px bg-gray-200" />
                  </div>
                );
              }
              const msg = item as StreamingMessage;
              return (
                <div
                  key={msg.id}
                  className={`group flex items-start mb-4 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                >
                  {msg.role === "assistant" && (
                    <div className="mr-2.5 mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-gray-700">
                      <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" className="h-3.5 w-3.5">
                        <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                      </svg>
                    </div>
                  )}
                  <div className="max-w-[85%] flex flex-col">
                    <div className={`rounded-2xl px-4 py-3 shadow-sm ${
                      msg.role === "user"
                        ? "bg-gray-700 text-white"
                        : "bg-white text-gray-900 ring-1 ring-gray-200"
                    }`}>
                      {msg.content ? (
                        <MarkdownMessage content={msg.content} inverted={msg.role === "user"} />
                      ) : msg.streaming ? (
                        <span className="flex gap-1 items-center h-5">
                          <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:0ms]" />
                          <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:150ms]" />
                          <span className="h-1.5 w-1.5 rounded-full bg-gray-400 animate-bounce [animation-delay:300ms]" />
                        </span>
                      ) : null}
                      {msg.streaming && msg.content && (
                        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-gray-400 align-middle" />
                      )}
                    </div>

                    {/* Toolbar: timestamp + actions */}
                    <div className={`mt-1 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ${
                      msg.role === "user" ? "justify-end" : "justify-start"
                    }`}>
                      <span className="text-[10px] text-gray-400">{timeAgo(msg.created_at)}</span>
                      <button
                        onClick={() => copyMessage(msg.id, msg.content)}
                        title="Copy"
                        className="rounded p-1 text-xs text-gray-400 hover:text-gray-700 transition-colors"
                      >
                        {copiedId === msg.id ? "✓" : (
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-3.5 w-3.5">
                            <rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
                          </svg>
                        )}
                      </button>
                      {msg.role === "assistant" && !msg.streaming && (
                        <>
                          <button
                            onClick={() => handleFeedback(msg.id, msg.feedback === 1 ? null : 1)}
                            title="Helpful"
                            className={`rounded p-1 text-sm transition-colors ${msg.feedback === 1 ? "text-gray-800" : "text-gray-300 hover:text-gray-600"}`}
                          >👍</button>
                          <button
                            onClick={() => handleFeedback(msg.id, msg.feedback === -1 ? null : -1)}
                            title="Not helpful"
                            className={`rounded p-1 text-sm transition-colors ${msg.feedback === -1 ? "text-gray-800" : "text-gray-300 hover:text-gray-600"}`}
                          >👎</button>
                        </>
                      )}
                    </div>

                    {msg.role === "assistant" && !msg.streaming && msg.sources && msg.sources.length > 0 && (
                      <div className="mt-1.5 flex items-center gap-2">
                        <ConfidenceBadge
                          sources={msg.sources}
                          score={msg.confidence_score}
                          label={msg.confidence_label}
                        />
                      </div>
                    )}
                    {msg.role === "assistant" && !msg.streaming && msg.sources && msg.sources.length > 0 && (
                      <SourceCitation sources={msg.sources} />
                    )}
                    {msg.role === "assistant" && !msg.streaming && msg.follow_up_questions && msg.follow_up_questions.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {msg.follow_up_questions.map((q, i) => (
                          <button
                            key={i}
                            onClick={() => { setInput(q); textareaRef.current?.focus(); }}
                            className="rounded-full border border-gray-200 bg-white px-3 py-1 text-xs text-gray-600 hover:border-gray-400 hover:bg-gray-50 transition-colors shadow-sm text-left"
                          >
                            {q}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  {msg.role === "user" && (
                    <div className="ml-2.5 mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-600 text-[11px] font-bold text-white uppercase">
                      {currentUser?.username?.[0] ?? "U"}
                    </div>
                  )}
                </div>
              );
            })}
            <div ref={bottomRef} />
          </div>
        )}

        {/* Scroll-to-bottom button */}
        {showScrollBtn && (
          <button
            onClick={scrollToBottom}
            className="fixed bottom-24 right-6 z-10 flex h-9 w-9 items-center justify-center rounded-full bg-white shadow-lg ring-1 ring-gray-200 hover:bg-gray-50 transition-all"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4 text-gray-600">
              <path d="M12 5v14M5 12l7 7 7-7" />
            </svg>
          </button>
        )}
      </div>

      {/* Input area */}
      <div className="border-t border-gray-200 bg-white px-4 py-3">
        <div className="mx-auto flex max-w-2xl flex-col gap-2">
          {/* Collection + scope pickers on mobile */}
          <div className="flex sm:hidden items-center gap-2">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5 text-gray-400 shrink-0">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
            </svg>
            <select
              value={activeCollectionId ?? ""}
              onChange={(e) => setActiveCollectionId(e.target.value || null)}
              className="flex-1 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs text-gray-600 outline-none"
            >
              <option value="">All collections</option>
              {collections.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <select
              value={activeScope}
              onChange={(e) => setActiveScope(e.target.value)}
              className="flex-1 rounded-lg border border-gray-200 bg-white px-2 py-1 text-xs text-gray-600 outline-none"
            >
              <option value="all">All sources</option>
              <option value="personal">Personal</option>
              {userTeams.map((t) => (
                <option key={t.id} value={`team:${t.id}`}>Team: {t.name}</option>
              ))}
            </select>
          </div>

          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              placeholder="Ask Nexus anything… (Enter or ⌘↵ to send)"
              rows={1}
              className="flex-1 resize-none rounded-xl border border-gray-300 bg-white px-4 py-3 text-sm outline-none focus:border-gray-600 focus:ring-2 focus:ring-gray-100 disabled:opacity-60 transition-colors"
              style={{ maxHeight: 160 }}
              onInput={(e) => {
                const t = e.currentTarget;
                t.style.height = "auto";
                t.style.height = `${Math.min(t.scrollHeight, 160)}px`;
              }}
            />
            {isLoading ? (
              <button
                onClick={() => abortRef.current?.abort()}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors ring-1 ring-gray-300"
                title="Stop generating"
              >
                <svg className="h-5 w-5" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              </button>
            ) : (
              <button
                onClick={sendMessage}
                disabled={!input.trim()}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gray-700 text-white transition-all hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
                title="Send (Enter or ⌘↵)"
              >
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>
            )}
          </div>
          <div className="flex items-center justify-between">
            <p className="text-[10px] text-gray-400">
              Nexus can make mistakes. Verify important information.
            </p>
            {input.length > 100 && (
              <span className={`text-[10px] tabular-nums ${input.length > 1900 ? "text-red-500" : "text-gray-400"}`}>
                {input.length}/2000
              </span>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

export default function Page() {
  return <Suspense><ChatPage /></Suspense>;
}
