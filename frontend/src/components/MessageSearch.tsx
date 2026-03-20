"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

interface MessageSearchResult {
  id: string;
  channel_id: string;
  channel_name: string;
  sender_username: string;
  content: string;
  created_at: string;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function highlight(text: string, query: string): React.ReactNode {
  if (!query.trim()) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-yellow-200 text-yellow-900 rounded px-0.5">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  );
}

export default function MessageSearch({ onClose }: { onClose?: () => void }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MessageSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 50);
  }, []);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); setSearched(false); return; }
    setLoading(true);
    setSearched(true);
    try {
      const res = await api.get<MessageSearchResult[]>(
        `/api/v1/messages/search?q=${encodeURIComponent(q)}&limit=20`
      );
      setResults(res);
    } catch {
      // Fallback: search channel messages client-side via what we have
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => runSearch(query), 300);
    return () => clearTimeout(t);
  }, [query, runSearch]);

  function goToMessage(result: MessageSearchResult) {
    router.push(`/chat?channel=${result.channel_id}&highlight=${result.id}`);
    onClose?.();
  }

  return (
    <div className="flex flex-col overflow-hidden">
      {/* Search input */}
      <div className="flex items-center gap-2.5 border-b border-gray-100 px-3 py-2.5">
        {loading ? (
          <svg className="h-4 w-4 animate-spin text-gray-400 shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
            className="h-4 w-4 text-gray-400 shrink-0">
            <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
          </svg>
        )}
        <input
          ref={inputRef}
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search messages…"
          className="flex-1 text-sm text-gray-800 outline-none placeholder:text-gray-400 bg-transparent"
          autoComplete="off"
          spellCheck={false}
        />
        {query && (
          <button onClick={() => { setQuery(""); setResults([]); setSearched(false); }}
            className="text-gray-400 hover:text-gray-600 text-xs">✕</button>
        )}
      </div>

      {/* Results */}
      <div className="flex-1 overflow-y-auto">
        {!searched && (
          <p className="px-4 py-6 text-center text-xs text-gray-400">
            Type to search across all messages
          </p>
        )}
        {searched && loading && (
          <div className="flex justify-center py-8">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
          </div>
        )}
        {searched && !loading && results.length === 0 && (
          <div className="px-4 py-8 text-center">
            <p className="text-sm text-gray-500">No results for</p>
            <p className="text-sm font-semibold text-gray-700 mt-0.5">"{query}"</p>
          </div>
        )}
        {results.map(r => (
          <button key={r.id} onClick={() => goToMessage(r)}
            className="flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-gray-50 transition-colors border-b border-gray-50 last:border-0">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-indigo-600 truncate">#{r.channel_name}</span>
              <span className="text-[10px] text-gray-400 shrink-0">{timeAgo(r.created_at)}</span>
            </div>
            <p className="text-xs font-medium text-gray-600">{r.sender_username}</p>
            <p className="text-sm text-gray-700 line-clamp-2 leading-relaxed">
              {highlight(r.content, query)}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
