"use client";

import { useRef, useState, DragEvent, useEffect } from "react";
import { api } from "@/lib/api";
import type { Collection } from "@/types";

const SUPPORTED_TYPES = [".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".html"];
const MAX_MB = 50;

interface Channel { id: string; name: string; type: string }
interface OrgUser { id: string; username: string; email: string }

interface Props {
  onUpload: () => void;
  channels: Channel[];
  collections: Collection[];
  defaultCollectionId?: string;
}

type Visibility = "public" | "internal" | "channel" | "users" | "confidential";

export default function DocumentUpload({ onUpload, channels, collections, defaultCollectionId }: Props) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [visibility, setVisibility] = useState<Visibility>("public");
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [collectionId, setCollectionId] = useState(defaultCollectionId ?? "");
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [complianceViolations, setComplianceViolations] = useState<{ category: string; label: string; framework: string; occurrences: number }[]>([]);

  // User sharing
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [userSearch, setUserSearch] = useState("");

  const inputRef = useRef<HTMLInputElement>(null);

  const shareableChannels = channels.filter(c => c.type !== "dm");

  // Fetch org users lazily when modal opens
  useEffect(() => {
    if (!open || orgUsers.length > 0) return;
    api.get<OrgUser[]>("/api/v1/admin/users/search").then(setOrgUsers).catch(() => {});
  }, [open, orgUsers.length]);

  const userSuggestions = userSearch.length > 0
    ? orgUsers.filter(u =>
        !selectedUserIds.includes(u.id) &&
        (u.username.toLowerCase().includes(userSearch.toLowerCase()) ||
         u.email.toLowerCase().includes(userSearch.toLowerCase()))
      )
    : [];

  function validateFile(f: File): string {
    const ext = "." + f.name.split(".").pop()?.toLowerCase();
    if (!SUPPORTED_TYPES.includes(ext)) return `Unsupported type. Allowed: ${SUPPORTED_TYPES.join(", ")}`;
    if (f.size > MAX_MB * 1024 * 1024) return `File exceeds ${MAX_MB}MB`;
    return "";
  }

  function pickFile(f: File) {
    const err = validateFile(f);
    if (err) { setError(err); return; }
    setError("");
    setFile(f);
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) pickFile(f);
  }

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setUploadProgress(0);
    setError("");
    try {
      const fd = new FormData();
      fd.append("file", file);
      // "users" maps to confidential + explicit user_ids
      const effectiveVisibility = visibility === "users" ? "confidential" : visibility === "internal" ? "internal" : visibility;
      fd.append("visibility", effectiveVisibility);
      if (collectionId) fd.append("collection_id", collectionId);
      if (visibility === "channel" && selectedChannelId) {
        fd.append("channel_id", selectedChannelId);
      }
      if (visibility === "users" && selectedUserIds.length > 0) {
        fd.append("user_ids", selectedUserIds.join(","));
      }
      const result = await api.uploadWithProgress<{ document_id: string }>(
        "/api/v1/documents/upload",
        fd,
        setUploadProgress,
      );
      resetAndClose();
      if (result?.document_id) {
        pollIngestion(result.document_id);
      } else {
        onUpload();
      }
    } catch (e: unknown) {
      const { ApiError } = await import("@/lib/api");
      if (e instanceof ApiError && typeof e.rawDetail === "object" && e.rawDetail !== null) {
        const detail = e.rawDetail as Record<string, unknown>;
        if (detail.error_code === "PHI_VIOLATION" || detail.error_code === "COMPLIANCE_VIOLATION") {
          setComplianceViolations((detail.violations as { category: string; label: string; framework: string; occurrences: number }[]) ?? []);
          setError(typeof detail.message === "string" ? detail.message : "Upload blocked due to compliance violations.");
        } else {
          setError(typeof detail.message === "string" ? detail.message : "Upload failed");
        }
      } else {
        setError(e instanceof Error ? e.message : "Upload failed");
      }
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  }

  function pollIngestion(documentId: string) {
    const INTERVAL = 2000;
    const MAX_POLLS = 60;
    let count = 0;
    const timer = setInterval(async () => {
      count++;
      try {
        const doc = await api.get<{ status: string }>(`/api/v1/documents/${documentId}`);
        if (doc.status === "ready" || doc.status === "failed" || doc.status === "compliance_blocked" || doc.status === "flagged") {
          clearInterval(timer); onUpload();
        }
      } catch { clearInterval(timer); onUpload(); }
      if (count >= MAX_POLLS) { clearInterval(timer); onUpload(); }
    }, INTERVAL);
  }

  function resetAndClose() {
    setFile(null);
    setVisibility("public");
    setSelectedChannelId("");
    setSelectedUserIds([]);
    setUserSearch("");
    setCollectionId(defaultCollectionId ?? "");
    setError("");
    setComplianceViolations([]);
    setOpen(false);
  }

  const uploadDisabled = !file || uploading
    || (visibility === "channel" && !selectedChannelId)
    || (visibility === "users" && selectedUserIds.length === 0);

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
      >
        Upload Document
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <h2 className="text-base font-semibold">Upload Document</h2>
              <button onClick={resetAndClose} className="text-slate-400 hover:text-slate-600">✕</button>
            </div>

            <div className="space-y-4 px-5 py-4">
              {/* Drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={handleDrop}
                onClick={() => inputRef.current?.click()}
                className={`cursor-pointer rounded-xl border-2 border-dashed p-6 text-center transition ${
                  dragging ? "border-blue-400 bg-blue-50" : "border-slate-300 hover:border-blue-300"
                }`}
              >
                {file ? (
                  <div>
                    <p className="font-medium text-slate-700">{file.name}</p>
                    <p className="text-xs text-slate-400">{(file.size / 1024).toFixed(0)} KB</p>
                  </div>
                ) : (
                  <div>
                    <p className="text-slate-500">Drag & drop a file here, or click to select</p>
                    <p className="mt-1 text-xs text-slate-400">{SUPPORTED_TYPES.join(" · ")} · max {MAX_MB}MB</p>
                  </div>
                )}
              </div>
              <input
                ref={inputRef}
                type="file"
                className="hidden"
                accept={SUPPORTED_TYPES.join(",")}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) pickFile(f); }}
              />

              {/* Collection */}
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Collection (optional)</label>
                <select
                  value={collectionId}
                  onChange={(e) => setCollectionId(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                >
                  <option value="">— None —</option>
                  {collections.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
              </div>

              {/* Visibility */}
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">Visibility</label>
                <div className="space-y-1">
                  {([
                    { v: "public",       desc: "— all authenticated users" },
                    { v: "internal",     desc: "— all users in your organization" },
                    { v: "channel",      desc: "— shared with a channel" },
                    { v: "users",        desc: "— specific people only" },
                    { v: "confidential", desc: "— only you" },
                  ] as { v: Visibility; desc: string }[]).map(({ v, desc }) => (
                    <label key={v} className="flex cursor-pointer items-center gap-2 text-sm">
                      <input
                        type="radio"
                        name="visibility"
                        value={v}
                        checked={visibility === v}
                        onChange={() => setVisibility(v)}
                        className="accent-blue-600"
                      />
                      <span className="capitalize">{v}</span>
                      <span className="text-xs text-slate-400">{desc}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Channel selector */}
              {visibility === "channel" && (
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Share with channel</label>
                  {shareableChannels.length === 0 ? (
                    <p className="text-xs text-slate-400">No channels available. Create a channel first.</p>
                  ) : (
                    <select
                      value={selectedChannelId}
                      onChange={(e) => setSelectedChannelId(e.target.value)}
                      className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    >
                      <option value="">— Select a channel —</option>
                      {shareableChannels.map((ch) => (
                        <option key={ch.id} value={ch.id}># {ch.name}</option>
                      ))}
                    </select>
                  )}
                  <p className="mt-1 text-[11px] text-slate-400">All current members of this channel will be able to access this document.</p>
                </div>
              )}

              {/* User selector */}
              {visibility === "users" && (
                <div>
                  <label className="mb-1 block text-xs font-medium text-slate-600">Share with people</label>
                  <input
                    type="search"
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                    placeholder="Search by name or email…"
                    className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  />
                  {userSuggestions.length > 0 && (
                    <ul className="mt-1 max-h-36 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-sm">
                      {userSuggestions.map(u => (
                        <li key={u.id}>
                          <button
                            type="button"
                            onClick={() => { setSelectedUserIds(prev => [...prev, u.id]); setUserSearch(""); }}
                            className="flex w-full items-center gap-2.5 px-3 py-2 hover:bg-slate-50 text-left"
                          >
                            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-800 text-white text-[10px] font-bold uppercase">
                              {u.username[0]}
                            </span>
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-slate-800 truncate">{u.username}</p>
                              <p className="text-xs text-slate-400 truncate">{u.email}</p>
                            </div>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {selectedUserIds.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {selectedUserIds.map(id => {
                        const u = orgUsers.find(o => o.id === id);
                        if (!u) return null;
                        return (
                          <span key={id} className="flex items-center gap-1 rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700">
                            {u.username}
                            <button
                              type="button"
                              onClick={() => setSelectedUserIds(prev => prev.filter(x => x !== id))}
                              className="ml-0.5 text-blue-400 hover:text-blue-700 leading-none"
                            >×</button>
                          </span>
                        );
                      })}
                    </div>
                  )}
                  <p className="mt-1.5 text-[11px] text-slate-400">Only you and the selected people will be able to access this document.</p>
                </div>
              )}

              {error && complianceViolations.length === 0 && (
                <p className="text-sm text-red-600">{error}</p>
              )}

              {complianceViolations.length > 0 && (
                <div className="rounded-xl border border-red-200 bg-red-50 p-4">
                  <div className="flex items-start gap-2 mb-3">
                    <svg className="mt-0.5 h-5 w-5 shrink-0 text-red-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                    </svg>
                    <div>
                      <p className="text-sm font-semibold text-red-700">Upload Blocked — Compliance Violation</p>
                      <p className="text-xs text-red-600 mt-0.5">{error}</p>
                    </div>
                  </div>
                  <p className="text-xs font-medium text-red-700 mb-2">Detected violations:</p>
                  <ul className="space-y-1">
                    {complianceViolations.map((v) => (
                      <li key={v.category} className="flex items-center justify-between rounded-lg bg-white border border-red-100 px-3 py-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                            v.framework === "HIPAA" ? "bg-red-100 text-red-700" :
                            v.framework === "PCI_DSS" ? "bg-orange-100 text-orange-700" :
                            v.framework === "GDPR" ? "bg-purple-100 text-purple-700" :
                            v.framework === "PII" ? "bg-yellow-100 text-yellow-700" :
                            v.framework === "SOX" ? "bg-blue-100 text-blue-700" :
                            "bg-slate-100 text-slate-700"
                          }`}>{v.framework.replace("_", "-")}</span>
                          <span className="text-xs text-slate-700 truncate">{v.label}</span>
                        </div>
                        <span className="ml-2 shrink-0 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
                          {v.occurrences}×
                        </span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-xs text-slate-500">Remove the sensitive data from the document and try again.</p>
                </div>
              )}
            </div>

            {uploading && (
              <div className="px-5 pb-2">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-slate-500">Uploading…</span>
                  <span className="text-xs font-medium text-blue-600">{uploadProgress}%</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-slate-200 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-blue-500 transition-all duration-300"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              </div>
            )}
            <div className="flex justify-end gap-2 border-t border-slate-200 px-5 py-4">
              <button onClick={resetAndClose} disabled={uploading} className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-40">
                Cancel
              </button>
              <button
                onClick={handleUpload}
                disabled={uploadDisabled}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
              >
                {uploading ? `${uploadProgress}%` : "Upload"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
