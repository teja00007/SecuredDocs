"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import DocumentUpload from "@/components/DocumentUpload";
import { useToast } from "@/components/Toast";
import MarkdownMessage from "@/components/MarkdownMessage";
import type { Channel, Collection, Document, User } from "@/types";


const STATUS_COLORS: Record<string, string> = {
  pending:           "bg-yellow-50 text-yellow-700 ring-1 ring-yellow-200",
  processing:        "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  ready:             "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  flagged:           "bg-orange-50 text-orange-700 ring-1 ring-orange-200",
  compliance_blocked:"bg-red-50 text-red-700 ring-1 ring-red-200",
  failed:            "bg-red-50 text-red-700 ring-1 ring-red-200",
  embedding_failed:  "bg-red-50 text-red-700 ring-1 ring-red-200",
};

const STATUS_DOT: Record<string, string> = {
  pending:           "bg-yellow-400 animate-pulse",
  processing:        "bg-blue-400 animate-pulse",
  ready:             "bg-emerald-500",
  flagged:           "bg-orange-400",
  compliance_blocked:"bg-red-500",
  failed:            "bg-red-500",
  embedding_failed:  "bg-red-500",
};

const VISIBILITY_COLORS: Record<string, string> = {
  public:       "bg-slate-100 text-slate-600",
  team:         "bg-purple-50 text-purple-700 ring-1 ring-purple-200",
  channel:      "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  confidential: "bg-red-50 text-red-600 ring-1 ring-red-200",
};

const VISIBILITY_ICONS: Record<string, string> = {
  public:       "🌐",
  team:         "👥",
  channel:      "#",
  confidential: "🔒",
};

function formatBytes(bytes: number | null) {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function FileTypeIcon({ type }: { type: string }) {
  const ext = type.replace(".", "").toLowerCase();
  const configs: Record<string, { bg: string; label: string }> = {
    pdf:  { bg: "bg-red-100 text-red-700",    label: "PDF" },
    docx: { bg: "bg-blue-100 text-blue-700",   label: "DOC" },
    doc:  { bg: "bg-blue-100 text-blue-700",   label: "DOC" },
    xlsx: { bg: "bg-green-100 text-green-700", label: "XLS" },
    xls:  { bg: "bg-green-100 text-green-700", label: "XLS" },
    csv:  { bg: "bg-green-100 text-green-700", label: "CSV" },
    pptx: { bg: "bg-orange-100 text-orange-700", label: "PPT" },
    ppt:  { bg: "bg-orange-100 text-orange-700", label: "PPT" },
    txt:  { bg: "bg-slate-100 text-slate-600",  label: "TXT" },
    md:   { bg: "bg-slate-100 text-slate-600",  label: "MD" },
    json: { bg: "bg-violet-100 text-violet-700", label: "JSON" },
    xml:  { bg: "bg-violet-100 text-violet-700", label: "XML" },
    html: { bg: "bg-amber-100 text-amber-700",  label: "HTML" },
  };
  const cfg = configs[ext] ?? { bg: "bg-slate-100 text-slate-500", label: ext.slice(0, 4).toUpperCase() || "FILE" };
  return (
    <span className={`inline-flex items-center justify-center rounded-md px-1.5 py-0.5 text-[10px] font-bold ${cfg.bg}`}>
      {cfg.label}
    </span>
  );
}

type SortField = "name" | "date" | "size" | "status";
type SortDir   = "asc" | "desc";

export default function DocumentsPage() {
  const router = useRouter();
  const { success, error: toastError, info } = useToast();
  const [user, setUser] = useState<User | null>(null);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [search,      setSearch]      = useState("");
  const [statusFilter,setStatusFilter]= useState<string>("");
  const [sortField,   setSortField]   = useState<SortField>("date");
  const [sortDir,     setSortDir]     = useState<SortDir>("desc");
  const [selected,    setSelected]    = useState<Set<string>>(new Set());
  const [deleting,    setDeleting]    = useState<string | null>(null);
  const [reingesting, setReingesting] = useState<string | null>(null);
  const [bulkWorking, setBulkWorking] = useState(false);
  const [showMoveDialog, setShowMoveDialog] = useState(false);
  const [moveTargetId, setMoveTargetId] = useState<string>("");


  // Document viewer (slide-in panel)
  const [viewingDoc,    setViewingDoc]    = useState<Document | null>(null);
  const [viewBlobUrl,   setViewBlobUrl]   = useState<string | null>(null);
  const [viewTextContent, setViewTextContent] = useState<string | null>(null);
  const [viewLoading,   setViewLoading]   = useState(false);

  // Tab state
  const [tab, setTab] = useState<"docs" | "cols">("docs");

  // Collections tab state
  const [selectedCol, setSelectedCol] = useState<Collection | null>(null);
  const [colDocs, setColDocs] = useState<Document[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [deletingDoc, setDeletingDoc] = useState<string | null>(null);
  const [showCreateCol, setShowCreateCol] = useState(false);
  const [colName, setColName] = useState("");
  const [colDesc, setColDesc] = useState("");
  const [colCreating, setColCreating] = useState(false);
  const [colError, setColError] = useState("");
  const [deletingCol, setDeletingCol] = useState<string | null>(null);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  // Auto-poll documents that are still processing (every 5s until all are done)
  useEffect(() => {
    const hasInProgress = documents.some(d => d.status === "pending" || d.status === "processing");
    if (!hasInProgress) return;
    const timer = setInterval(async () => {
      try {
        const fresh = await api.get<Document[]>("/api/v1/documents?limit=200");
        setDocuments(fresh);
        const stillInProgress = fresh.some(d => d.status === "pending" || d.status === "processing");
        if (!stillInProgress) clearInterval(timer);
      } catch { /* ignore */ }
    }, 5000);
    return () => clearInterval(timer);
  }, [documents]);

  async function load() {
    const [u, cols, chs, docs] = await Promise.all([
      api.get<User>("/api/v1/auth/me"),
      api.get<Collection[]>("/api/v1/collections"),
      api.get<Channel[]>("/api/v1/chat/channels"),
      api.get<Document[]>("/api/v1/documents?limit=200"),
    ]);
    setUser(u);
    setCollections(cols);
    setChannels(chs);
    setDocuments(docs);
    setSelected(new Set());
  }


  // ── Document functions ───────────────────────────────────────────────────

  async function handleDelete(id: string) {
    if (!confirm("Delete this document? This cannot be undone.")) return;
    setDeleting(id);
    try {
      await api.delete(`/api/v1/documents/${id}`);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
      setSelected((prev) => { const s = new Set(prev); s.delete(id); return s; });
    } finally {
      setDeleting(null);
    }
  }

  const TEXT_TYPES = [".txt", ".md", ".csv"];
  const IFRAME_TYPES = [".pdf", ".html"];

  async function handleView(doc: Document) {
    setViewingDoc(doc);
    setViewBlobUrl(null);
    setViewTextContent(null);
    setViewLoading(true);
    try {
      const blob = await api.blob(`/api/v1/documents/${doc.id}/download`);
      if (TEXT_TYPES.includes(doc.file_type)) {
        // Render as text/markdown
        const text = await blob.text();
        setViewTextContent(text);
      } else {
        const url = URL.createObjectURL(blob);
        setViewBlobUrl(url);
      }
    } catch {
      toastError("Could not load file");
      setViewingDoc(null);
    } finally {
      setViewLoading(false);
    }
  }

  function closeViewer() {
    if (viewBlobUrl) URL.revokeObjectURL(viewBlobUrl);
    setViewingDoc(null);
    setViewBlobUrl(null);
    setViewTextContent(null);
  }

  async function handleDownload(doc: Document) {
    try {
      const blob = await api.blob(`/api/v1/documents/${doc.id}/download`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc.filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch {
      toastError("Failed to download document");
    }
  }

  async function handleReingest(id: string) {
    setReingesting(id);
    try {
      await api.post(`/api/v1/documents/${id}/reingest`, {});
      setDocuments((prev) => prev.map((d) => d.id === id ? { ...d, status: "pending" } : d));
      info("Re-ingestion queued — document will be re-indexed shortly");
    } catch {
      toastError("Failed to re-ingest document");
    } finally {
      setReingesting(null);
    }
  }

  async function handleBulkDelete() {
    if (selected.size === 0) return;
    if (!confirm(`Delete ${selected.size} document(s)? This cannot be undone.`)) return;
    setBulkWorking(true);
    try {
      const result = await api.post<{ deleted: number }>("/api/v1/documents/bulk/delete", {
        document_ids: Array.from(selected),
      });
      setDocuments((prev) => prev.filter((d) => !selected.has(d.id)));
      setSelected(new Set());
      if (result.deleted < selected.size) {
        toastError(`${result.deleted} deleted. Some could not be deleted (not owner or not found).`);
      } else {
        success(`${result.deleted} document${result.deleted !== 1 ? "s" : ""} deleted`);
      }
    } finally {
      setBulkWorking(false);
    }
  }

  async function handleBulkMove() {
    if (selected.size === 0) return;
    setBulkWorking(true);
    try {
      await api.patch("/api/v1/documents/bulk/collection", {
        document_ids: Array.from(selected),
        collection_id: moveTargetId || null,
      });
      setShowMoveDialog(false);
      await load();
    } finally {
      setBulkWorking(false);
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const s = new Set(prev);
      s.has(id) ? s.delete(id) : s.add(id);
      return s;
    });
  }

  function toggleAll() {
    const deletable = filtered.filter(d => user?.roles.includes("admin") || d.owner_id === user?.id);
    if (selected.size === deletable.length && deletable.length > 0) {
      setSelected(new Set());
    } else {
      setSelected(new Set(deletable.map((d) => d.id)));
    }
  }

  function toggleSort(field: SortField) {
    if (sortField === field) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortDir("asc"); }
  }

  const filtered = documents
    .filter((d) => {
      const matchSearch = d.filename.toLowerCase().includes(search.toLowerCase());
      const matchStatus = !statusFilter || d.status === statusFilter;
      return matchSearch && matchStatus;
    })
    .sort((a, b) => {
      let cmp = 0;
      if (sortField === "name")   cmp = a.filename.localeCompare(b.filename);
      if (sortField === "date")   cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
      if (sortField === "size")   cmp = (a.file_size ?? 0) - (b.file_size ?? 0);
      if (sortField === "status") cmp = a.status.localeCompare(b.status);
      return sortDir === "asc" ? cmp : -cmp;
    });
  const allSelected = filtered.length > 0 && selected.size === filtered.length;

  function SortArrow({ field }: { field: SortField }) {
    if (sortField !== field) return <span className="ml-1 text-slate-300">↕</span>;
    return <span className="ml-1">{sortDir === "asc" ? "↑" : "↓"}</span>;
  }

  // ── Collection functions ─────────────────────────────────────────────────

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

  async function handleCreateCol(e: FormEvent) {
    e.preventDefault();
    setColCreating(true);
    setColError("");
    try {
      const col = await api.post<Collection>("/api/v1/collections", { name: colName, description: colDesc });
      setCollections((prev) => [col, ...prev]);
      setShowCreateCol(false);
      setColName("");
      setColDesc("");
    } catch (err: unknown) {
      setColError(err instanceof Error ? err.message : "Failed to create collection");
    } finally {
      setColCreating(false);
    }
  }

  async function handleDeleteCol(id: string) {
    if (!confirm("Delete this collection? Documents will NOT be deleted, just unassigned.")) return;
    setDeletingCol(id);
    try {
      await api.delete(`/api/v1/collections/${id}`);
      setCollections((prev) => prev.filter((c) => c.id !== id));
      if (selectedCol?.id === id) setSelectedCol(null);
    } finally {
      setDeletingCol(null);
    }
  }

  async function handleDeleteColDoc(docId: string) {
    if (!confirm("Permanently delete this document?")) return;
    setDeletingDoc(docId);
    try {
      await api.delete(`/api/v1/documents/${docId}`);
      setColDocs((prev) => prev.filter((d) => d.id !== docId));
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
    const input = document.createElement("input");
    input.type = "file";
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file || !selectedCol) return;
      await api.delete(`/api/v1/documents/${docId}`);
      setColDocs((prev) => prev.filter((d) => d.id !== docId));
      const form = new FormData();
      form.append("file", file);
      form.append("visibility", "public");
      form.append("collection_id", selectedCol.id);
      await api.upload<{ document_id: string }>("/api/v1/documents/upload", form);
      setTimeout(() => openCollection(selectedCol), 500);
    };
    input.click();
  }

  if (!user) return null;

  // Determine preview mode
  const isTextPreview = viewingDoc ? TEXT_TYPES.includes(viewingDoc.file_type) : false;
  const isIframePreview = viewingDoc ? IFRAME_TYPES.includes(viewingDoc.file_type) : false;
  const isNoPreview = viewingDoc ? (!isTextPreview && !isIframePreview) : false;

  return (
    <>
    <div className="flex flex-1 overflow-hidden">
    {/* ── Main content area ─────────────────────────────────────────── */}
    <main className="flex flex-1 flex-col overflow-hidden min-w-0">

      {/* ── Header + tab bar ─────────────────────────────────────────── */}
      <div className="shrink-0 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-800">Documents</h2>
          {tab === "docs"
            ? <DocumentUpload onUpload={load} channels={channels} collections={collections} />
            : <button onClick={() => setShowCreateCol(true)} className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700">+ New Collection</button>
          }
        </div>
        <div className="flex border-t border-slate-100 px-5">
          {(["docs", "cols"] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`mr-4 pb-2 pt-1.5 text-xs font-medium border-b-2 transition-colors ${
                tab === t ? "border-indigo-600 text-indigo-600" : "border-transparent text-slate-500 hover:text-slate-700"
              }`}>
              {t === "docs" ? "Documents" : "Collections"}
            </button>
          ))}
        </div>
      </div>

      {/* ── Documents tab ────────────────────────────────────────────── */}
      {tab === "docs" && (
        <>
        <div className="flex flex-1 flex-col overflow-hidden min-h-0">
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-5 py-2">
            <div className="relative">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400 pointer-events-none">
                <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
              </svg>
              <input
                type="search"
                placeholder="Search by filename…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-60 rounded-lg border border-slate-200 pl-9 pr-3 py-1.5 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 outline-none focus:border-blue-400"
            >
              <option value="">All statuses</option>
              <option value="ready">Ready</option>
              <option value="processing">Processing</option>
              <option value="pending">Pending</option>
              <option value="failed">Failed</option>
              <option value="embedding_failed">Embedding Failed</option>
              <option value="flagged">Flagged</option>
              <option value="compliance_blocked">Compliance Blocked</option>
            </select>
            <span className="text-xs text-slate-400 ml-1">{filtered.length} doc{filtered.length !== 1 ? "s" : ""}</span>

            {selected.size > 0 && (
              <div className="ml-auto flex items-center gap-2">
                <span className="text-xs text-slate-500">{selected.size} selected</span>
                <button
                  onClick={() => setShowMoveDialog(true)}
                  disabled={bulkWorking}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-100 disabled:opacity-40"
                >
                  Move to collection
                </button>
                <button
                  onClick={handleBulkDelete}
                  disabled={bulkWorking}
                  className="rounded-lg bg-red-50 px-3 py-1.5 text-xs text-red-600 hover:bg-red-100 disabled:opacity-40"
                >
                  Delete selected
                </button>
              </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center text-slate-400">
                <p className="text-3xl">📄</p>
                <p className="mt-2 text-sm">No documents yet — upload one to get started.</p>
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium text-slate-500 select-none">
                  <tr>
                    <th className="px-4 py-3">
                      <input type="checkbox" checked={allSelected} onChange={toggleAll} className="accent-blue-600" />
                    </th>
                    <th className="px-4 py-3 text-left">
                      <button onClick={() => toggleSort("name")} className="flex items-center gap-0.5 hover:text-slate-700 uppercase tracking-wide">
                        File <SortArrow field="name" />
                      </button>
                    </th>
                    <th className="px-4 py-3 text-left uppercase tracking-wide">Type</th>
                    <th className="px-4 py-3 text-left">
                      <button onClick={() => toggleSort("size")} className="flex items-center gap-0.5 hover:text-slate-700 uppercase tracking-wide">
                        Size <SortArrow field="size" />
                      </button>
                    </th>
                    <th className="px-4 py-3 text-left uppercase tracking-wide">Visibility</th>
                    <th className="px-4 py-3 text-left">
                      <button onClick={() => toggleSort("status")} className="flex items-center gap-0.5 hover:text-slate-700 uppercase tracking-wide">
                        Status <SortArrow field="status" />
                      </button>
                    </th>
                    <th className="px-4 py-3 text-left uppercase tracking-wide">Chunks</th>
                    <th className="px-4 py-3 text-left">
                      <button onClick={() => toggleSort("date")} className="flex items-center gap-0.5 hover:text-slate-700 uppercase tracking-wide">
                        Uploaded <SortArrow field="date" />
                      </button>
                    </th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filtered.map((doc) => (
                    <tr
                      key={doc.id}
                      className={`hover:bg-slate-50 ${selected.has(doc.id) ? "bg-blue-50" : ""}`}
                    >
                      <td className="px-4 py-3">
                        {(user.roles.includes("admin") || doc.owner_id === user.id) && (
                          <input
                            type="checkbox"
                            checked={selected.has(doc.id)}
                            onChange={() => toggleSelect(doc.id)}
                            className="accent-blue-600"
                          />
                        )}
                      </td>
                      <td className="px-4 py-3 font-medium text-slate-700">
                        <span className="flex items-center gap-2 max-w-[200px]">
                          <FileTypeIcon type={doc.file_type} />
                          {doc.status === "ready" ? (
                            <button
                              onClick={() => handleView(doc)}
                              className="truncate text-left hover:text-blue-600 hover:underline transition-colors"
                              title={doc.filename}
                            >
                              {doc.filename}
                            </button>
                          ) : (
                            <span className="truncate" title={doc.filename}>{doc.filename}</span>
                          )}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-400 font-mono">{doc.file_type || "—"}</td>
                      <td className="px-4 py-3 text-sm text-slate-500">{formatBytes(doc.file_size)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${VISIBILITY_COLORS[doc.visibility] ?? ""}`}>
                          <span>{VISIBILITY_ICONS[doc.visibility]}</span>
                          {doc.visibility}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${STATUS_COLORS[doc.status] ?? "bg-slate-100 text-slate-600"}`}>
                          <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${STATUS_DOT[doc.status] ?? "bg-slate-400"}`} />
                          {doc.status.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-500">{doc.chunk_count}</td>
                      <td className="px-4 py-3 text-slate-400">
                        {new Date(doc.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          {doc.status === "ready" && (
                            <button
                              onClick={() => handleDownload(doc)}
                              className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
                            >
                              Download
                            </button>
                          )}
                          {(doc.status === "failed" || doc.status === "embedding_failed") && (
                            <button
                              onClick={() => handleReingest(doc.id)}
                              disabled={reingesting === doc.id}
                              className="rounded px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 disabled:opacity-40"
                            >
                              {reingesting === doc.id ? "…" : "Re-ingest"}
                            </button>
                          )}
                          {(user.roles.includes("admin") || doc.owner_id === user.id) && (
                            <button
                              onClick={() => handleDelete(doc.id)}
                              disabled={deleting === doc.id}
                              className="rounded px-2 py-1 text-xs text-red-500 hover:bg-red-50 disabled:opacity-40"
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Move to collection dialog */}
          {showMoveDialog && (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
              <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
                <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
                  <h3 className="text-sm font-semibold text-slate-800">Move {selected.size} document(s)</h3>
                  <button onClick={() => setShowMoveDialog(false)} className="text-slate-400 hover:text-slate-600">✕</button>
                </div>
                <div className="space-y-4 px-5 py-4">
                  <div>
                    <label className="mb-1 block text-xs font-medium text-slate-600">Target Collection</label>
                    <select
                      value={moveTargetId}
                      onChange={(e) => setMoveTargetId(e.target.value)}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500"
                    >
                      <option value="">— Remove from collection —</option>
                      {collections.map((c) => (
                        <option key={c.id} value={c.id}>{c.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="flex justify-end gap-2">
                    <button onClick={() => setShowMoveDialog(false)}
                      className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">Cancel</button>
                    <button onClick={handleBulkMove} disabled={bulkWorking}
                      className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40">
                      {bulkWorking ? "Moving…" : "Move"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>{/* end docs flex layout */}
        </>
      )}

      {/* ── Collections tab ──────────────────────────────────────────── */}
      {tab === "cols" && (
        <div className="flex flex-1 overflow-hidden">
          {/* Collections list */}
          <div className={`flex flex-col ${selectedCol ? "w-72 border-r border-slate-200" : "flex-1"} bg-slate-50`}>
            <div className="flex-1 overflow-y-auto p-4">
              {collections.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-slate-400">
                  <p className="text-3xl">🗂️</p>
                  <p className="mt-2 text-sm">No collections yet.</p>
                </div>
              ) : (
                <div className={`grid gap-3 ${selectedCol ? "grid-cols-1" : "sm:grid-cols-2 lg:grid-cols-3"}`}>
                  {collections.map((col) => (
                    <button
                      key={col.id}
                      onClick={() => openCollection(col)}
                      className={`rounded-xl border bg-white p-4 shadow-sm text-left transition-all hover:border-indigo-300 hover:shadow-md ${
                        selectedCol?.id === col.id ? "border-indigo-400 ring-1 ring-indigo-200" : "border-slate-200"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <h3 className="truncate text-sm font-semibold text-slate-800">{col.name}</h3>
                          {col.description && (
                            <p className="mt-1 text-xs text-slate-500 line-clamp-2">{col.description}</p>
                          )}
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDeleteCol(col.id); }}
                          disabled={deletingCol === col.id}
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
                  <h3 className="text-sm font-semibold text-slate-800">{selectedCol.name}</h3>
                  {selectedCol.description && (
                    <p className="text-xs text-slate-400">{selectedCol.description}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
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
                          <td className="max-w-[220px] px-4 py-3 font-medium text-slate-700">
                            {doc.status === "ready" ? (
                              <button
                                onClick={() => handleView(doc)}
                                className="truncate block w-full text-left hover:text-blue-600 hover:underline transition-colors"
                                title={doc.filename}
                              >
                                {doc.filename}
                              </button>
                            ) : (
                              <span className="truncate block" title={doc.filename}>{doc.filename}</span>
                            )}
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
                              {doc.status === "ready" && (
                                <button
                                  onClick={() => handleDownload(doc)}
                                  className="text-xs text-slate-500 hover:underline"
                                >
                                  Download
                                </button>
                              )}
                              <button
                                onClick={() => handleReplaceDoc(doc.id)}
                                className="text-xs text-blue-500 hover:underline"
                                title="Replace with a new file"
                              >
                                Replace
                              </button>
                              {(user.roles.includes("admin") || doc.owner_id === user.id) && (
                                <button
                                  onClick={() => handleDeleteColDoc(doc.id)}
                                  disabled={deletingDoc === doc.id}
                                  className="text-xs text-red-500 hover:underline disabled:opacity-40"
                                >
                                  Delete
                                </button>
                              )}
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
        </div>
      )}

      {/* ── Create collection dialog ─────────────────────────────────── */}
      {showCreateCol && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-sm rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h3 className="text-sm font-semibold text-slate-800">New Collection</h3>
              <button onClick={() => setShowCreateCol(false)} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>
            <form onSubmit={handleCreateCol} className="space-y-4 px-5 py-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Name</label>
                <input
                  type="text"
                  value={colName}
                  onChange={(e) => setColName(e.target.value)}
                  required
                  autoFocus
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Description (optional)</label>
                <textarea
                  value={colDesc}
                  onChange={(e) => setColDesc(e.target.value)}
                  rows={3}
                  className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100"
                />
              </div>
              {colError && <p className="text-xs text-red-600">{colError}</p>}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setShowCreateCol(false)}
                  className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100">
                  Cancel
                </button>
                <button type="submit" disabled={colCreating}
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-40">
                  {colCreating ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>

    {/* ── Document Slide-in Preview Panel ───────────────────────────── */}
    {viewingDoc && (
      <div className="flex w-[600px] max-w-[45vw] shrink-0 flex-col border-l border-slate-200 bg-white shadow-xl transition-all duration-200">
        {/* Panel header */}
        <div className="flex shrink-0 items-center justify-between border-b border-slate-200 px-5 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <FileTypeIcon type={viewingDoc.file_type} />
            <span className="truncate text-sm font-semibold text-slate-800" title={viewingDoc.filename}>
              {viewingDoc.filename}
            </span>
            <span className="shrink-0 text-xs text-slate-400">{formatBytes(viewingDoc.file_size)}</span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              onClick={() => handleDownload(viewingDoc)}
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 transition-colors"
            >
              Download
            </button>
            <button onClick={closeViewer}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4">
                <path d="M18 6L6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Panel body */}
        <div className="relative flex-1 overflow-hidden">
          {viewLoading && (
            <div className="flex h-full items-center justify-center">
              <svg className="h-6 w-6 animate-spin text-blue-500" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
            </div>
          )}

          {/* Text / Markdown preview */}
          {!viewLoading && isTextPreview && viewTextContent !== null && (
            <div className="h-full overflow-y-auto p-5">
              {viewingDoc.file_type === ".md" ? (
                <MarkdownMessage content={viewTextContent} />
              ) : (
                <pre className="whitespace-pre-wrap text-sm text-slate-700 font-mono leading-relaxed">
                  {viewTextContent}
                </pre>
              )}
            </div>
          )}

          {/* PDF / HTML iframe preview */}
          {!viewLoading && isIframePreview && viewBlobUrl && (
            <iframe
              src={viewBlobUrl}
              className="h-full w-full border-0"
              title={viewingDoc.filename}
            />
          )}

          {/* No preview available (DOCX, XLSX, etc.) */}
          {!viewLoading && isNoPreview && (
            <div className="flex h-full flex-col items-center justify-center gap-4 text-slate-500">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-14 w-14 text-slate-300">
                <path strokeLinecap="round" strokeLinejoin="round" d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>
                <path d="M14 2v6h6" />
              </svg>
              <p className="text-sm font-medium text-slate-600">Preview not available</p>
              <p className="text-xs text-slate-400">
                {viewingDoc.file_type} files cannot be previewed in the browser.
              </p>
              <button
                onClick={() => handleDownload(viewingDoc)}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
              >
                Download to view
              </button>
            </div>
          )}
        </div>
      </div>
    )}
    </div>
    </>
  );
}
