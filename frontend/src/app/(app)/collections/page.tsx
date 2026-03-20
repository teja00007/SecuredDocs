"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import DocumentUpload from "@/components/DocumentUpload";
import type { Channel, Collection, Document, User } from "@/types";

const STATUS_COLORS: Record<string, string> = {
  pending: "bg-yellow-100 text-yellow-700",
  processing: "bg-blue-100 text-blue-700",
  ready: "bg-green-100 text-green-700",
  flagged: "bg-orange-100 text-orange-700",
  compliance_blocked: "bg-red-100 text-red-700",
  failed: "bg-red-100 text-red-700",
};

export default function CollectionsPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();
  const [user, setUser] = useState<User | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);

  const [colSearch, setColSearch] = useState("");

  // Detail panel
  const [selectedCol, setSelectedCol] = useState<Collection | null>(null);
  const [colDocs, setColDocs] = useState<Document[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [deletingDoc, setDeletingDoc] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    load();
  }, [router]);

  async function load() {
    const [u, cols, chs] = await Promise.all([
      api.get<User>("/api/v1/auth/me"),
      api.get<Collection[]>("/api/v1/collections"),
      api.get<Channel[]>("/api/v1/chat/channels"),
    ]);
    setUser(u);
    setCollections(cols);
    setChannels(chs);
  }

  async function openCollection(col: Collection) {
    setSelectedCol(col);
    setDocsLoading(true);
    try {
      const docs = await api.get<Document[]>(`/api/v1/documents?collection_id=${col.id}&limit=100`);
      setColDocs(docs);
    } finally {
      setDocsLoading(false);
    }
  }

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      const col = await api.post<Collection>("/api/v1/collections", { name, description });
      setCollections((prev) => [col, ...prev]);
      setShowCreate(false);
      setName("");
      setDescription("");
      success("Collection created");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create collection");
    } finally {
      setCreating(false);
    }
  }

  async function handleDeleteCollection(id: string) {
    if (!confirm("Delete this collection? Documents will NOT be deleted, just unassigned.")) return;
    setDeleting(id);
    try {
      await api.delete(`/api/v1/collections/${id}`);
      setCollections((prev) => prev.filter((c) => c.id !== id));
      if (selectedCol?.id === id) setSelectedCol(null);
      success("Collection deleted");
    } catch {
      toastError("Failed to delete collection");
    } finally {
      setDeleting(null);
    }
  }

  async function handleDeleteDoc(docId: string) {
    if (!confirm("Permanently delete this document?")) return;
    setDeletingDoc(docId);
    try {
      await api.delete(`/api/v1/documents/${docId}`);
      setColDocs((prev) => prev.filter((d) => d.id !== docId));
      success("Document deleted");
      // Update doc count on the collection card
      setCollections((prev) =>
        prev.map((c) =>
          c.id === selectedCol?.id ? { ...c, document_count: c.document_count - 1 } : c
        )
      );
    } finally {
      setDeletingDoc(null);
    }
  }

  async function handleReplaceDoc(docId: string) {
    // Trigger file picker and re-upload with same collection
    const input = document.createElement("input");
    input.type = "file";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file || !selectedCol) return;
      // Delete old first
      await api.delete(`/api/v1/documents/${docId}`);
      setColDocs((prev) => prev.filter((d) => d.id !== docId));
      // Upload new
      const form = new FormData();
      form.append("file", file);
      form.append("visibility", "public");
      form.append("collection_id", selectedCol.id);
      const result = await api.upload<{ document_id: string }>("/api/v1/documents/upload", form);
      // Reload docs after a brief moment for the ingestion to register
      setTimeout(() => openCollection(selectedCol), 500);
    };
    input.click();
  }

  if (!user) return null;

  return (
    <div className="flex flex-1 overflow-hidden">
        {/* Collections list */}
        <div className={`flex flex-col ${selectedCol ? "w-72 border-r border-slate-200" : "flex-1"} bg-slate-50`}>
          <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
            <h2 className="font-semibold text-slate-800">Collections</h2>
            <button
              onClick={() => setShowCreate(true)}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700"
            >
              + New
            </button>
          </div>

          {/* Search */}
          <div className="border-b border-slate-100 bg-white px-4 py-2">
            <div className="relative">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none">
                <circle cx="11" cy="11" r="8" /><path d="M21 21l-4.35-4.35" />
              </svg>
              <input
                type="search"
                value={colSearch}
                onChange={e => setColSearch(e.target.value)}
                placeholder="Search collections…"
                className="w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 py-1.5 text-xs text-slate-700 outline-none focus:border-blue-400 focus:bg-white transition"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            {collections.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                <p className="text-3xl">🗂️</p>
                <p className="mt-2 text-sm">No collections yet.</p>
              </div>
            ) : (
              <div className={`grid gap-3 ${selectedCol ? "grid-cols-1" : "sm:grid-cols-2 lg:grid-cols-3"}`}>
                {collections.filter(c => !colSearch.trim() || c.name.toLowerCase().includes(colSearch.toLowerCase()) || (c.description ?? "").toLowerCase().includes(colSearch.toLowerCase())).map((col) => (
                  <button
                    key={col.id}
                    onClick={() => openCollection(col)}
                    className={`rounded-xl border bg-white p-4 shadow-sm text-left transition-all hover:border-blue-300 hover:shadow-md ${
                      selectedCol?.id === col.id ? "border-blue-400 ring-1 ring-blue-200" : "border-slate-200"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h3 className="truncate font-semibold text-slate-800">{col.name}</h3>
                        {col.description && (
                          <p className="mt-1 text-xs text-slate-500 line-clamp-2">{col.description}</p>
                        )}
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteCollection(col.id); }}
                        disabled={deleting === col.id}
                        className="shrink-0 rounded p-1 text-slate-300 hover:bg-red-50 hover:text-red-500 disabled:opacity-40"
                        title="Delete collection"
                      >
                        ✕
                      </button>
                    </div>
                    <div className="mt-3 flex items-center gap-3 text-xs text-slate-400">
                      <span>{col.document_count} doc{col.document_count !== 1 ? "s" : ""}</span>
                      <span>·</span>
                      <span>{col.is_public ? "Public" : "Private"}</span>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        {selectedCol && (
          <div className="flex flex-1 flex-col overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
              <div>
                <h3 className="font-semibold text-slate-800">{selectedCol.name}</h3>
                {selectedCol.description && (
                  <p className="text-xs text-slate-400">{selectedCol.description}</p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Link
                  href={`/?collection=${selectedCol.id}`}
                  className="flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-700 hover:bg-indigo-100 transition-colors"
                  title="Open RAG chat scoped to this collection"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-3.5 h-3.5">
                    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
                  </svg>
                  Query
                </Link>
                <DocumentUpload
                  onUpload={() => openCollection(selectedCol)}
                  channels={channels}
                  collections={collections}
                  defaultCollectionId={selectedCol.id}
                />
                <button
                  onClick={() => setSelectedCol(null)}
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                  title="Close"
                >
                  ✕
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto">
              {docsLoading ? (
                <p className="p-5 text-sm text-slate-400">Loading documents…</p>
              ) : colDocs.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-20 text-slate-400">
                  <p className="text-3xl">📄</p>
                  <p className="mt-2 text-sm">No documents in this collection yet.</p>
                  <p className="text-xs mt-1">Use the Upload button to add some.</p>
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-3 text-left">File</th>
                      <th className="px-4 py-3 text-left">Type</th>
                      <th className="px-4 py-3 text-left">Status</th>
                      <th className="px-4 py-3 text-left">Chunks</th>
                      <th className="px-4 py-3 text-left">Uploaded</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {colDocs.map((doc) => (
                      <tr key={doc.id} className="hover:bg-slate-50">
                        <td
                          className="max-w-[220px] truncate px-4 py-3 font-medium text-slate-700"
                          title={doc.filename}
                        >
                          {doc.filename}
                        </td>
                        <td className="px-4 py-3 font-mono text-xs text-slate-500">{doc.file_type}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium capitalize ${
                              STATUS_COLORS[doc.status] ?? "bg-slate-100 text-slate-600"
                            }`}
                          >
                            {doc.status.replace("_", " ")}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-500">{doc.chunk_count}</td>
                        <td className="px-4 py-3 text-slate-400 text-xs">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => handleReplaceDoc(doc.id)}
                              className="text-xs text-blue-500 hover:underline"
                              title="Replace with a new file"
                            >
                              Replace
                            </button>
                            <button
                              onClick={() => handleDeleteDoc(doc.id)}
                              disabled={deletingDoc === doc.id}
                              className="text-xs text-red-500 hover:underline disabled:opacity-40"
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

      {/* Create dialog */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h3 className="font-semibold">New Collection</h3>
              <button onClick={() => setShowCreate(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={handleCreate} className="space-y-4 px-5 py-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Description (optional)</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>
              {error && <p className="text-sm text-red-600">{error}</p>}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setShowCreate(false)} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
                  Cancel
                </button>
                <button type="submit" disabled={creating} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40">
                  {creating ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
