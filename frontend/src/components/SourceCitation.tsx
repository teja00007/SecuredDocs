"use client";

import { useState } from "react";
import type { Source } from "@/types";

interface Props {
  sources: Source[];
}

function scoreColor(pct: number) {
  if (pct >= 80) return { bar: "bg-gray-900", text: "text-gray-900", bg: "bg-gray-100" };
  if (pct >= 60) return { bar: "bg-gray-700", text: "text-gray-700", bg: "bg-gray-100" };
  if (pct >= 40) return { bar: "bg-gray-500", text: "text-gray-600", bg: "bg-gray-100" };
  return           { bar: "bg-gray-300",       text: "text-gray-500", bg: "bg-gray-50"  };
}

export default function SourceCitation({ sources }: Props) {
  const [open, setOpen] = useState(false);

  if (sources.length === 0) return null;

  return (
    <div className="mt-2 rounded-lg border border-gray-200 bg-gray-50 text-sm">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2 text-gray-600 hover:text-gray-800 transition-colors"
      >
        <span className="font-medium flex items-center gap-1.5">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-3.5 h-3.5 text-gray-400">
            <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
            <path d="M14 2v6h6M8 13h8M8 17h5" />
          </svg>
          {sources.length} source{sources.length !== 1 ? "s" : ""}
        </span>
        <svg
          className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="divide-y divide-gray-200 border-t border-gray-200">
          {sources.map((src, i) => {
            const pct = Math.round(src.score * 100);
            const { bar, text, bg } = scoreColor(pct);
            return (
              <div key={i} className="px-3 py-2.5 hover:bg-white transition-colors">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-gray-700 truncate flex-1" title={src.filename}>
                    {src.filename}
                  </span>
                  <div className="flex items-center gap-2 shrink-0">
                    {src.page_number != null && (
                      <span className="text-[10px] text-gray-400">p.{src.page_number}</span>
                    )}
                    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${bg} ${text}`}>
                      {pct}%
                    </span>
                  </div>
                </div>
                {/* Relevance score bar */}
                <div className="mt-1.5 h-1 w-full rounded-full bg-gray-200 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${bar}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                {/* Staleness warning */}
                {src.is_stale && (
                  <div className="mt-1.5 flex items-center gap-1 rounded bg-gray-100 px-2 py-1 text-[11px] text-gray-600">
                    <span>⚠</span>
                    <span>
                      Source last updated{" "}
                      {src.days_since_update != null
                        ? `${src.days_since_update} day${src.days_since_update !== 1 ? "s" : ""} ago`
                        : "a while ago"}
                      {" — verify this information is current"}
                    </span>
                  </div>
                )}
                <p className="mt-1.5 line-clamp-3 text-[12px] text-gray-500 leading-relaxed">
                  {src.chunk_text}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
