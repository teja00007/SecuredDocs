"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

interface Result {
  type: "document" | "conversation" | "channel" | "team";
  id: string;
  title: string;
  sub?: string;
  href: string;
}

interface Doc     { id: string; filename: string; file_type: string }
interface Conv    { id: string; title: string }
interface Channel { id: string; name: string; type: string }
interface Team    { id: string; name: string }

const TYPE_ICON: Record<string, React.ReactNode> = {
  document: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-blue-500">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <path d="M14 2v6h6M8 13h8M8 17h5" />
    </svg>
  ),
  conversation: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-violet-500">
      <path d="M8 10h8M8 14h5M5 3h14a2 2 0 012 2v11a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
    </svg>
  ),
  channel: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-emerald-500">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  ),
  team: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-4 h-4 text-amber-500">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
    </svg>
  ),
};

export default function GlobalSearch() {
  const router = useRouter();
  const wrapRef  = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const [open,     setOpen]     = useState(false);
  const [query,    setQuery]    = useState("");
  const [results,  setResults]  = useState<Result[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [selected, setSelected] = useState(0);

  // ⌘K / Ctrl+K to open (also ⌥⌘E for backwards compat)
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k" && !e.altKey) {
        e.preventDefault();
        setOpen(v => !v);
        if (!open) setTimeout(() => inputRef.current?.focus(), 10);
      }
      if ((e.metaKey || e.ctrlKey) && e.altKey && e.key.toLowerCase() === "e") {
        e.preventDefault();
        setOpen(true);
        setTimeout(() => inputRef.current?.focus(), 10);
      }
      if (e.key === "Escape") { setOpen(false); setQuery(""); setResults([]); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Click-outside to close (and clear state)
  useEffect(() => {
    function onMouse(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false); setQuery(""); setResults([]);
      }
    }
    if (open) document.addEventListener("mousedown", onMouse);
    return () => document.removeEventListener("mousedown", onMouse);
  }, [open]);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); return; }
    setLoading(true);
    try {
      const [docs, convs, channels, teams] = await Promise.allSettled([
        api.get<Doc[]>("/api/v1/documents"),
        api.get<Conv[]>("/api/v1/conversations"),
        api.get<Channel[]>("/api/v1/chat/channels"),
        api.get<Team[]>("/api/v1/teams"),
      ]);
      const lc = q.toLowerCase();
      const out: Result[] = [];

      if (docs.status === "fulfilled")
        docs.value.filter(d => d.filename.toLowerCase().includes(lc)).slice(0, 3)
          .forEach(d => out.push({ type: "document", id: d.id, title: d.filename, sub: (d.file_type ?? "").toUpperCase(), href: "/documents" }));

      if (convs.status === "fulfilled")
        convs.value.filter(c => c.title.toLowerCase().includes(lc)).slice(0, 3)
          .forEach(c => out.push({ type: "conversation", id: c.id, title: c.title, sub: "AI Chat", href: `/?conv=${c.id}` }));

      if (channels.status === "fulfilled")
        channels.value.filter(c => c.name.toLowerCase().includes(lc)).slice(0, 3)
          .forEach(c => out.push({ type: "channel", id: c.id, title: c.name, sub: c.type === "dm" ? "Direct Message" : "Channel", href: `/chat?channel=${c.id}` }));

      if (teams.status === "fulfilled")
        teams.value.filter(t => t.name.toLowerCase().includes(lc)).slice(0, 3)
          .forEach(t => out.push({ type: "team", id: t.id, title: t.name, sub: "Team", href: `/teams?team=${t.id}` }));

      setResults(out);
      setSelected(0);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => runSearch(query), 220);
    return () => clearTimeout(t);
  }, [query, runSearch]);

  function go(href: string) {
    setOpen(false);
    setQuery("");
    router.push(href);
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setSelected(s => Math.min(s + 1, results.length - 1)); }
    if (e.key === "ArrowUp")   { e.preventDefault(); setSelected(s => Math.max(s - 1, 0)); }
    if (e.key === "Enter" && results[selected]) go(results[selected].href);
  }

  return (
    <div ref={wrapRef} className="relative w-full">
      {/* Trigger bar */}
      <button
        onClick={() => { setOpen(true); setTimeout(() => inputRef.current?.focus(), 10); }}
        className="flex w-full items-center gap-2.5 rounded-lg border border-gray-200 bg-gray-50 px-4 py-2 text-sm text-gray-400 hover:border-indigo-300 hover:bg-white transition-all"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4 shrink-0">
          <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
        </svg>
        <span className="flex-1 text-left select-none">Search</span>
        <span className="hidden sm:inline-flex items-center gap-0.5 rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-500 select-none">
          ⌘K
        </span>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute left-0 right-0 top-full mt-1.5 rounded-xl border border-gray-200 bg-white shadow-2xl z-[300] overflow-hidden">
          {/* Input row */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4 text-gray-400 shrink-0">
              <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
            </svg>
            <input
              ref={inputRef}
              value={query}
              onChange={e => setQuery(e.target.value)}
              onKeyDown={onKey}
              placeholder="Search documents, conversations, channels, teams…"
              className="flex-1 text-sm text-gray-800 outline-none placeholder:text-gray-400 bg-transparent"
              autoComplete="off"
              spellCheck={false}
            />
            {loading && (
              <svg className="w-4 h-4 animate-spin text-gray-300 shrink-0" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
              </svg>
            )}
          </div>

          {/* Results */}
          {results.length > 0 ? (
            <ul className="max-h-72 overflow-y-auto py-1.5">
              {results.map((r, i) => (
                <li key={`${r.type}-${r.id}`}>
                  <button
                    onClick={() => go(r.href)}
                    onMouseEnter={() => setSelected(i)}
                    className={`flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors ${
                      i === selected ? "bg-indigo-50" : "hover:bg-gray-50"
                    }`}
                  >
                    <span className="shrink-0">{TYPE_ICON[r.type]}</span>
                    <span className="flex-1 min-w-0">
                      <span className="block truncate text-sm font-medium text-gray-800">{r.title}</span>
                      {r.sub && <span className="text-[11px] text-gray-400">{r.sub}</span>}
                    </span>
                    {i === selected && (
                      <kbd className="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-400">↵</kbd>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          ) : query.trim() ? (
            <div className="px-4 py-8 text-center text-sm text-gray-400">
              No results for <span className="font-medium text-gray-600">"{query}"</span>
            </div>
          ) : (
            <div className="px-4 py-6 text-center text-xs text-gray-400">
              Start typing to search across Nexus
            </div>
          )}

          {/* Footer hints */}
          <div className="border-t border-gray-100 px-4 py-2 flex items-center gap-4 text-[10px] text-gray-400 select-none">
            <span className="flex items-center gap-1">
              <kbd className="rounded bg-gray-100 px-1 py-0.5">↑</kbd>
              <kbd className="rounded bg-gray-100 px-1 py-0.5">↓</kbd>
              navigate
            </span>
            <span className="flex items-center gap-1"><kbd className="rounded bg-gray-100 px-1 py-0.5">↵</kbd> open</span>
            <span className="flex items-center gap-1"><kbd className="rounded bg-gray-100 px-1 py-0.5">esc</kbd> close</span>
          </div>
        </div>
      )}
    </div>
  );
}
