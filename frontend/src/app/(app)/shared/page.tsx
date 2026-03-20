"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import type { Collection, Document, User } from "@/types";

const STATUS_COLORS: Record<string, string> = {
  ready: "bg-green-100 text-green-700",
  pending: "bg-yellow-100 text-yellow-700",
  processing: "bg-blue-100 text-blue-700",
  failed: "bg-red-100 text-red-700",
  flagged: "bg-orange-100 text-orange-700",
  compliance_blocked: "bg-red-100 text-red-700",
};

const VISIBILITY_LABELS: Record<string, string> = {
  public: "🌐 Public",
  team: "👥 Team",
  confidential: "🔒 Confidential",
};

function formatBytes(bytes: number | null) {
  if (!bytes) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function SharedDocsPage() {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [search, setSearch] = useState("");
  const [filterVis, setFilterVis] = useState<string>("all");

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    Promise.all([
      api.get<User>("/api/v1/auth/me"),
      api.get<Collection[]>("/api/v1/collections"),
      api.get<Document[]>("/api/v1/documents?limit=200"),
    ]).then(([u, cols, docs]) => {
      setUser(u);
      setCollections(cols);
      setDocuments(docs);
    }).catch((err) => {
      console.error("Failed to load shared docs:", err?.message);
    });
  }, [router]);

  const filtered = documents.filter((d) => {
    const matchSearch = d.filename.toLowerCase().includes(search.toLowerCase());
    const matchVis = filterVis === "all" || d.visibility === filterVis;
    return matchSearch && matchVis;
  });

  // Group by collection
  const byCollection: Record<string, Document[]> = {};
  const noCollection: Document[] = [];
  for (const doc of filtered) {
    if (doc.collection_id) {
      (byCollection[doc.collection_id] ??= []).push(doc);
    } else {
      noCollection.push(doc);
    }
  }

  if (!user) return null;

  return (
    <main className="flex flex-1 flex-col overflow-hidden">
        <div className="border-b border-slate-200 bg-white px-5 py-3">
          <h2 className="font-semibold text-slate-800">Shared with me</h2>
          <p className="text-xs text-slate-400 mt-0.5">Documents accessible to you — public, team-shared, or directly shared</p>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-5 py-2">
          <input
            type="search"
            placeholder="Search…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full max-w-xs rounded-lg border border-slate-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          />
          <div className="flex gap-1">
            {["all", "public", "team", "confidential"].map((v) => (
              <button
                key={v}
                onClick={() => setFilterVis(v)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                  filterVis === v ? "bg-blue-600 text-white" : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"
                }`}
              >
                {v === "all" ? "All" : VISIBILITY_LABELS[v]}
              </button>
            ))}
          </div>
          <span className="ml-auto text-xs text-slate-400">{filtered.length} document{filtered.length !== 1 ? "s" : ""}</span>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-slate-400">
              <p className="text-3xl">📂</p>
              <p className="mt-2">No documents found.</p>
            </div>
          ) : (
            <>
              {Object.entries(byCollection).map(([colId, docs]) => {
                const col = collections.find((c) => c.id === colId);
                return (
                  <section key={colId}>
                    <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <span>🗂️</span>
                      {col?.name ?? "Collection"}
                    </h3>
                    <DocTable docs={docs} />
                  </section>
                );
              })}
              {noCollection.length > 0 && (
                <section>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">No collection</h3>
                  <DocTable docs={noCollection} />
                </section>
              )}
            </>
          )}
        </div>
    </main>
  );
}

function DocTable({ docs }: { docs: Document[] }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <table className="w-full text-sm">
        <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-2 text-left">File</th>
            <th className="px-4 py-2 text-left">Type</th>
            <th className="px-4 py-2 text-left">Size</th>
            <th className="px-4 py-2 text-left">Visibility</th>
            <th className="px-4 py-2 text-left">Status</th>
            <th className="px-4 py-2 text-left">Chunks</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {docs.map((doc) => (
            <tr key={doc.id} className="hover:bg-slate-50">
              <td className="max-w-[240px] truncate px-4 py-2.5 font-medium text-slate-700" title={doc.filename}>
                {doc.filename}
              </td>
              <td className="px-4 py-2.5 font-mono text-xs text-slate-500">{doc.file_type}</td>
              <td className="px-4 py-2.5 text-slate-500 text-xs">{formatBytes(doc.file_size)}</td>
              <td className="px-4 py-2.5 text-xs text-slate-500">{VISIBILITY_LABELS[doc.visibility] ?? doc.visibility}</td>
              <td className="px-4 py-2.5">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[doc.status] ?? "bg-slate-100 text-slate-600"}`}>
                  {doc.status.replace(/_/g, " ")}
                </span>
              </td>
              <td className="px-4 py-2.5 text-slate-500 text-xs">{doc.chunk_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
