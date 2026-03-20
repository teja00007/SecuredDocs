"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface LinkPreview {
  url: string;
  title: string | null;
  description: string | null;
  image: string | null;
  favicon: string | null;
  site_name: string | null;
}

export default function LinkPreviewCard({ url }: { url: string }) {
  const [preview, setPreview] = useState<LinkPreview | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .get<LinkPreview>(`/api/v1/chat/link-preview?url=${encodeURIComponent(url)}`)
      .then((r) => {
        if (!cancelled) setPreview(r);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => { cancelled = true; };
  }, [url]);

  if (failed || (!preview && preview !== null)) return null;
  if (!preview) {
    // Loading skeleton
    return (
      <div className="mt-2 rounded-xl border border-slate-200 bg-white overflow-hidden max-w-sm animate-pulse">
        <div className="h-2 w-full bg-slate-100" />
        <div className="p-3 space-y-2">
          <div className="h-3 w-2/3 bg-slate-100 rounded" />
          <div className="h-2 w-full bg-slate-100 rounded" />
          <div className="h-2 w-3/4 bg-slate-100 rounded" />
        </div>
      </div>
    );
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="mt-2 flex max-w-sm rounded-xl border border-slate-200 bg-white overflow-hidden hover:shadow-md transition-shadow no-underline"
    >
      {preview.image && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={preview.image}
          alt={preview.title ?? ""}
          className="w-28 h-24 object-cover shrink-0"
          onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
        />
      )}
      <div className="p-3 min-w-0 flex flex-col justify-center">
        <div className="flex items-center gap-1.5 mb-1">
          {preview.favicon && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview.favicon} alt="" className="w-4 h-4 shrink-0"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
          )}
          <span className="text-xs text-slate-400 truncate">{preview.site_name ?? new URL(url).hostname}</span>
        </div>
        {preview.title && (
          <p className="text-sm font-semibold text-slate-800 line-clamp-2 leading-snug">{preview.title}</p>
        )}
        {preview.description && (
          <p className="text-xs text-slate-500 line-clamp-2 mt-0.5 leading-relaxed">{preview.description}</p>
        )}
      </div>
    </a>
  );
}
