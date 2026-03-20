"use client";

import { useEffect, useState, FormEvent, useRef } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { Collection, User } from "@/types";

interface Connector {
  id: string;
  name: string;
  type: "web" | "google_drive" | "confluence" | "aws_s3" | "azure_data_lake" | "gcs" | "sharepoint";
  status: "active" | "syncing" | "error" | "idle";
  last_synced_at: string | null;
  last_error: string | null;
  total_docs_synced: number;
  collection_id: string | null;
  config: Record<string, unknown>;
  created_at: string;
}

type ConnectorType = "web" | "google_drive" | "confluence" | "aws_s3" | "azure_data_lake" | "gcs" | "sharepoint";
type WizardStep = 1 | 2 | 3;

const TYPE_ICON: Record<ConnectorType, string> = {
  web: "🌐",
  google_drive: "📁",
  confluence: "🔵",
  aws_s3: "🪣",
  azure_data_lake: "☁️",
  gcs: "🟡",
  sharepoint: "📋",
};

const TYPE_LABEL: Record<ConnectorType, string> = {
  web: "Web URL",
  google_drive: "Google Drive",
  confluence: "Confluence",
  aws_s3: "AWS S3",
  azure_data_lake: "Azure Data Lake",
  gcs: "Google Cloud Storage",
  sharepoint: "SharePoint",
};

const STATUS_CONFIG: Record<Connector["status"], { label: string; cls: string }> = {
  active:  { label: "Active",   cls: "bg-green-100 text-green-700" },
  syncing: { label: "Syncing",  cls: "bg-yellow-100 text-yellow-700" },
  error:   { label: "Error",    cls: "bg-red-100 text-red-600" },
  idle:    { label: "Idle",     cls: "bg-slate-100 text-slate-500" },
};

function relTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  return `${Math.floor(h / 24)} day${Math.floor(h / 24) === 1 ? "" : "s"} ago`;
}

export default function ConnectorsPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [step, setStep] = useState<WizardStep>(1);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  // Step 1: connector type
  const [selectedType, setSelectedType] = useState<ConnectorType>("web");

  // Step 2: type-specific config
  const [webUrls, setWebUrls] = useState("");
  const [webDepth, setWebDepth] = useState(1);
  const [gdriveFolderId, setGdriveFolderId] = useState("");
  const [gdriveServiceAccount, setGdriveServiceAccount] = useState("");
  const [confBaseUrl, setConfBaseUrl] = useState("");
  const [confUsername, setConfUsername] = useState("");
  const [confApiToken, setConfApiToken] = useState("");
  const [confSpaceKeys, setConfSpaceKeys] = useState("");
  // AWS S3
  const [s3Bucket, setS3Bucket] = useState("");
  const [s3Region, setS3Region] = useState("us-east-1");
  const [s3AccessKey, setS3AccessKey] = useState("");
  const [s3SecretKey, setS3SecretKey] = useState("");
  const [s3Prefix, setS3Prefix] = useState("");
  // Azure Data Lake
  const [azAccount, setAzAccount] = useState("");
  const [azContainer, setAzContainer] = useState("");
  const [azSasToken, setAzSasToken] = useState("");
  const [azPrefix, setAzPrefix] = useState("");
  // Google Cloud Storage
  const [gcsBucket, setGcsBucket] = useState("");
  const [gcsCredentials, setGcsCredentials] = useState("");
  const [gcsPrefix, setGcsPrefix] = useState("");
  // SharePoint
  const [spSiteUrl, setSpSiteUrl] = useState("");
  const [spClientId, setSpClientId] = useState("");
  const [spClientSecret, setSpClientSecret] = useState("");

  // Step 3: name + collection
  const [connName, setConnName] = useState("");
  const [connCollection, setConnCollection] = useState("");

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    loadData();
    pollRef.current = setInterval(loadConnectors, 30000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function loadData() {
    try {
      const [conns, cols] = await Promise.all([
        api.get<Connector[]>("/api/v1/connectors").catch(() => [] as Connector[]),
        api.get<Collection[]>("/api/v1/collections").catch(() => [] as Collection[]),
      ]);
      setConnectors(conns);
      setCollections(cols);
    } finally {
      setLoading(false);
    }
  }

  async function loadConnectors() {
    try {
      const conns = await api.get<Connector[]>("/api/v1/connectors");
      setConnectors(conns);
    } catch { /* ignore */ }
  }

  function openModal() {
    setShowModal(true);
    setStep(1);
    setSelectedType("web");
    setWebUrls("");
    setWebDepth(1);
    setGdriveFolderId("");
    setGdriveServiceAccount("");
    setConfBaseUrl("");
    setConfUsername("");
    setConfApiToken("");
    setConfSpaceKeys("");
    setS3Bucket(""); setS3Region("us-east-1"); setS3AccessKey(""); setS3SecretKey(""); setS3Prefix("");
    setAzAccount(""); setAzContainer(""); setAzSasToken(""); setAzPrefix("");
    setGcsBucket(""); setGcsCredentials(""); setGcsPrefix("");
    setSpSiteUrl(""); setSpClientId(""); setSpClientSecret("");
    setConnName("");
    setConnCollection("");
    setFormError("");
  }

  function closeModal() {
    setShowModal(false);
    setFormError("");
  }

  function buildConfig(): Record<string, unknown> {
    if (selectedType === "web") {
      return { urls: webUrls.split("\n").map(u => u.trim()).filter(Boolean), crawl_depth: webDepth };
    }
    if (selectedType === "google_drive") {
      return {
        service_account_json: gdriveServiceAccount,
        folder_ids: gdriveFolderId ? [gdriveFolderId] : [],
      };
    }
    if (selectedType === "confluence") {
      return { base_url: confBaseUrl, username: confUsername, api_token: confApiToken, space_keys: confSpaceKeys.split(",").map(s => s.trim()).filter(Boolean) };
    }
    if (selectedType === "aws_s3") {
      return { bucket: s3Bucket, region: s3Region, access_key_id: s3AccessKey, secret_access_key: s3SecretKey, prefix: s3Prefix || undefined };
    }
    if (selectedType === "azure_data_lake") {
      return { account_name: azAccount, container: azContainer, sas_token: azSasToken, prefix: azPrefix || undefined };
    }
    if (selectedType === "gcs") {
      return { bucket: gcsBucket, credentials_json: gcsCredentials, prefix: gcsPrefix || undefined };
    }
    if (selectedType === "sharepoint") {
      return { site_url: spSiteUrl, client_id: spClientId, client_secret: spClientSecret };
    }
    return {};
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!connName.trim()) { setFormError("Connector name is required"); return; }
    setSubmitting(true);
    setFormError("");
    try {
      const created = await api.post<Connector>("/api/v1/connectors", {
        name: connName.trim(),
        type: selectedType,
        collection_id: connCollection || null,
        config: buildConfig(),
      });
      setConnectors(prev => [created, ...prev]);
      closeModal();
      success("Connector created");
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to create connector");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSync(id: string) {
    setSyncing(id);
    try {
      await api.post(`/api/v1/connectors/${id}/sync`, {});
      setConnectors(prev => prev.map(c => c.id === id ? { ...c, status: "syncing" } : c));
      success("Sync started");
    } catch {
      toastError("Failed to start sync");
    } finally {
      setSyncing(null);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete connector "${name}"? This cannot be undone.`)) return;
    setDeleting(id);
    try {
      await api.delete(`/api/v1/connectors/${id}`);
      setConnectors(prev => prev.filter(c => c.id !== id));
      success("Connector deleted");
    } catch {
      toastError("Failed to delete connector");
    } finally {
      setDeleting(null);
    }
  }

  function nextStep() {
    setFormError("");
    if (step === 2) {
      if (selectedType === "web" && !webUrls.trim()) {
        setFormError("Please enter at least one URL"); return;
      }
      if (selectedType === "google_drive" && !gdriveServiceAccount.trim()) {
        setFormError("Service account JSON is required"); return;
      }
      if (selectedType === "google_drive" && !gdriveFolderId.trim()) {
        setFormError("Folder ID is required — share the folder with the service account email first"); return;
      }
      if (selectedType === "confluence" && (!confBaseUrl.trim() || !confUsername.trim() || !confApiToken.trim())) {
        setFormError("Please fill in all Confluence fields"); return;
      }
      if (selectedType === "aws_s3" && (!s3Bucket.trim() || !s3AccessKey.trim() || !s3SecretKey.trim())) {
        setFormError("Bucket, Access Key ID and Secret Access Key are required"); return;
      }
      if (selectedType === "azure_data_lake" && (!azAccount.trim() || !azContainer.trim() || !azSasToken.trim())) {
        setFormError("Account name, container and SAS token are required"); return;
      }
      if (selectedType === "gcs" && (!gcsBucket.trim() || !gcsCredentials.trim())) {
        setFormError("Bucket name and service account credentials are required"); return;
      }
      if (selectedType === "sharepoint" && (!spSiteUrl.trim() || !spClientId.trim() || !spClientSecret.trim())) {
        setFormError("Site URL, Client ID and Client Secret are required"); return;
      }
    }
    setStep(prev => (prev < 3 ? (prev + 1) as WizardStep : prev));
  }

  return (
    <main className="flex flex-1 flex-col overflow-hidden">
      <div className="border-b border-slate-200 bg-white px-5 py-3 flex items-center justify-between shrink-0">
        <div>
          <h2 className="font-semibold text-slate-800">Data Connectors</h2>
          <p className="text-xs text-slate-400 mt-0.5">Connect external sources to sync content automatically</p>
        </div>
        <button
          onClick={openModal}
          className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 transition-colors"
        >
          + Add Connector
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        {loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : connectors.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400">
            <div className="text-4xl mb-3">🔌</div>
            <p className="text-sm font-medium text-slate-600">No connectors yet</p>
            <p className="text-xs mt-1 text-slate-400">Add a connector to sync external content into your knowledge base.</p>
            <button
              onClick={openModal}
              className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
            >
              + Add Connector
            </button>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {connectors.map(conn => {
              const statusCfg = STATUS_CONFIG[conn.status] ?? STATUS_CONFIG.idle;
              const col = collections.find(c => c.id === conn.collection_id);
              return (
                <div key={conn.id} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm flex flex-col gap-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-xl">{TYPE_ICON[conn.type]}</span>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-slate-800 truncate">{conn.name}</p>
                        <p className="text-xs text-slate-400">{TYPE_LABEL[conn.type]}</p>
                      </div>
                    </div>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${statusCfg.cls}`}>
                      {statusCfg.label}
                    </span>
                  </div>

                  <div className="space-y-1 text-xs text-slate-500">
                    <div className="flex items-center justify-between">
                      <span>Last synced</span>
                      <span className="text-slate-700">{conn.last_synced_at ? relTime(conn.last_synced_at) : "Never"}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Documents</span>
                      <span className="text-slate-700">{conn.total_docs_synced} documents</span>
                    </div>
                    {col && (
                      <div className="flex items-center justify-between">
                        <span>Collection</span>
                        <span className="text-slate-700 truncate max-w-[120px]">{col.name}</span>
                      </div>
                    )}
                  </div>

                  {conn.last_error && (
                    <p className="rounded-lg bg-red-50 px-3 py-2 text-[11px] text-red-600 leading-relaxed">
                      {conn.last_error}
                    </p>
                  )}

                  <div className="flex items-center gap-2 pt-1 border-t border-slate-100">
                    <button
                      onClick={() => handleSync(conn.id)}
                      disabled={syncing === conn.id || conn.status === "syncing"}
                      className="rounded-lg bg-slate-100 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200 disabled:opacity-40 transition-colors"
                    >
                      {syncing === conn.id || conn.status === "syncing" ? "Syncing…" : "Sync Now"}
                    </button>
                    <button className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 transition-colors">
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(conn.id, conn.name)}
                      disabled={deleting === conn.id}
                      className="ml-auto rounded-lg px-3 py-1.5 text-xs text-red-500 hover:bg-red-50 disabled:opacity-40 transition-colors"
                    >
                      {deleting === conn.id ? "Deleting…" : "Delete"}
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Add Connector Modal ── */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white shadow-xl flex flex-col max-h-[90vh]">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 shrink-0">
              <div>
                <h3 className="font-semibold text-slate-800">Add Connector</h3>
                <p className="text-xs text-slate-400 mt-0.5">Step {step} of 3 — {step === 1 ? "Choose type" : step === 2 ? "Configure" : "Name & assign"}</p>
              </div>
              <button onClick={closeModal} className="text-slate-400 hover:text-slate-600 transition-colors">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-4 h-4">
                  <path d="M18 6L6 18M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Step indicator */}
            <div className="flex gap-0 shrink-0 px-5 pt-3">
              {([1, 2, 3] as const).map(n => (
                <div key={n} className="flex-1 flex items-center gap-1">
                  <div className={`h-1.5 flex-1 rounded-full transition-colors ${n <= step ? "bg-blue-500" : "bg-slate-200"}`} />
                </div>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="flex flex-col flex-1 overflow-hidden">
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">

                {/* ── Step 1: Choose type ── */}
                {step === 1 && (
                  <div className="space-y-2.5">
                    <p className="text-sm font-medium text-slate-700">Select connector type</p>
                    {([
                      { type: "web",              desc: "Crawl web pages and extract content" },
                      { type: "google_drive",     desc: "Sync documents from Google Drive folders" },
                      { type: "confluence",       desc: "Import pages from Confluence spaces" },
                      { type: "aws_s3",           desc: "Retrieve files from an Amazon S3 bucket" },
                      { type: "azure_data_lake",  desc: "Sync files from Azure Data Lake Storage" },
                      { type: "gcs",              desc: "Retrieve files from Google Cloud Storage" },
                      { type: "sharepoint",       desc: "Import documents from SharePoint sites" },
                    ] as Array<{ type: ConnectorType; desc: string }>).map(({ type, desc }) => (
                      <label key={type} className={`flex items-center gap-3 rounded-xl border-2 p-3.5 cursor-pointer transition-all ${
                        selectedType === type ? "border-blue-500 bg-blue-50" : "border-slate-200 hover:border-slate-300"
                      }`}>
                        <input type="radio" name="connector_type" value={type}
                          checked={selectedType === type} onChange={() => setSelectedType(type)}
                          className="accent-blue-600" />
                        <span className="text-lg">{TYPE_ICON[type]}</span>
                        <div>
                          <p className="text-sm font-medium text-slate-800">{TYPE_LABEL[type]}</p>
                          <p className="text-xs text-slate-400">{desc}</p>
                        </div>
                      </label>
                    ))}
                  </div>
                )}

                {/* ── Step 2: Configure ── */}
                {step === 2 && (
                  <div className="space-y-4">
                    {selectedType === "web" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">URLs to crawl (one per line)</label>
                          <textarea
                            value={webUrls}
                            onChange={e => setWebUrls(e.target.value)}
                            rows={5}
                            placeholder={"https://docs.example.com\nhttps://wiki.example.com/page"}
                            className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                          />
                        </div>
                        <div>
                          <label className="mb-2 flex items-center justify-between text-xs font-medium text-slate-600">
                            <span>Crawl depth</span>
                            <span className="text-blue-600 font-semibold">{webDepth}</span>
                          </label>
                          <input
                            type="range"
                            min={0}
                            max={3}
                            value={webDepth}
                            onChange={e => setWebDepth(Number(e.target.value))}
                            className="w-full accent-blue-600"
                          />
                          <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                            <span>0 (page only)</span>
                            <span>3 (deep crawl)</span>
                          </div>
                        </div>
                      </>
                    )}

                    {selectedType === "google_drive" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Service Account JSON <span className="text-red-500">*</span></label>
                          <textarea
                            value={gdriveServiceAccount}
                            onChange={e => setGdriveServiceAccount(e.target.value)}
                            placeholder='Paste the contents of your Google service account .json key file here'
                            rows={6}
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 resize-none"
                          />
                          <p className="mt-1 text-[11px] text-slate-400">
                            Create a service account in Google Cloud Console → IAM → Service Accounts, grant it Drive read access, and paste the JSON key here.
                          </p>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Folder ID <span className="text-red-500">*</span></label>
                          <input
                            type="text"
                            value={gdriveFolderId}
                            onChange={e => setGdriveFolderId(e.target.value)}
                            placeholder="e.g. 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                          />
                          <p className="mt-1 text-[11px] text-slate-400">Share your Drive folder with the service account email, then paste the folder ID from the URL (drive.google.com/drive/folders/<strong>THIS_PART</strong>).</p>
                        </div>
                      </>
                    )}

                    {selectedType === "confluence" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Base URL</label>
                          <input type="url" value={confBaseUrl} onChange={e => setConfBaseUrl(e.target.value)}
                            placeholder="https://your-org.atlassian.net"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Username / Email</label>
                          <input type="email" value={confUsername} onChange={e => setConfUsername(e.target.value)}
                            placeholder="you@company.com"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">API Token</label>
                          <input type="password" value={confApiToken} onChange={e => setConfApiToken(e.target.value)}
                            placeholder="••••••••••••••••"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                          <p className="mt-1 text-[11px] text-slate-400">Generate an API token from your Atlassian account settings.</p>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Space Keys (comma-separated)</label>
                          <input type="text" value={confSpaceKeys} onChange={e => setConfSpaceKeys(e.target.value)}
                            placeholder="ENG, PROD, DOC"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                      </>
                    )}

                    {selectedType === "aws_s3" && (
                      <>
                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="mb-1 block text-xs font-medium text-slate-600">Bucket Name *</label>
                            <input type="text" value={s3Bucket} onChange={e => setS3Bucket(e.target.value)}
                              placeholder="my-company-docs"
                              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                          </div>
                          <div>
                            <label className="mb-1 block text-xs font-medium text-slate-600">Region *</label>
                            <input type="text" value={s3Region} onChange={e => setS3Region(e.target.value)}
                              placeholder="us-east-1"
                              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                          </div>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Access Key ID *</label>
                          <input type="text" value={s3AccessKey} onChange={e => setS3AccessKey(e.target.value)}
                            placeholder="AKIAIOSFODNN7EXAMPLE"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Secret Access Key *</label>
                          <input type="password" value={s3SecretKey} onChange={e => setS3SecretKey(e.target.value)}
                            placeholder="••••••••••••••••••••••••••••••••••••••••"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Prefix / Folder (optional)</label>
                          <input type="text" value={s3Prefix} onChange={e => setS3Prefix(e.target.value)}
                            placeholder="documents/2025/"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                          <p className="mt-1 text-[11px] text-slate-400">Limit sync to files under this prefix. Leave blank to sync all files.</p>
                        </div>
                      </>
                    )}

                    {selectedType === "azure_data_lake" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Storage Account Name *</label>
                          <input type="text" value={azAccount} onChange={e => setAzAccount(e.target.value)}
                            placeholder="mycompanystorage"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Container Name *</label>
                          <input type="text" value={azContainer} onChange={e => setAzContainer(e.target.value)}
                            placeholder="documents"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">SAS Token *</label>
                          <input type="password" value={azSasToken} onChange={e => setAzSasToken(e.target.value)}
                            placeholder="sv=2020-08-04&ss=b&srt=co&sp=r..."
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                          <p className="mt-1 text-[11px] text-slate-400">Generate a SAS token from the Azure portal with read/list permissions.</p>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Path Prefix (optional)</label>
                          <input type="text" value={azPrefix} onChange={e => setAzPrefix(e.target.value)}
                            placeholder="data/raw/"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                      </>
                    )}

                    {selectedType === "gcs" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Bucket Name *</label>
                          <input type="text" value={gcsBucket} onChange={e => setGcsBucket(e.target.value)}
                            placeholder="my-company-docs"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Service Account JSON *</label>
                          <textarea value={gcsCredentials} onChange={e => setGcsCredentials(e.target.value)}
                            rows={5} placeholder={'{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}'}
                            className="w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                          <p className="mt-1 text-[11px] text-slate-400">Paste the full contents of your service account key JSON file. Grant it Storage Object Viewer role.</p>
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Prefix / Folder (optional)</label>
                          <input type="text" value={gcsPrefix} onChange={e => setGcsPrefix(e.target.value)}
                            placeholder="documents/"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                      </>
                    )}

                    {selectedType === "sharepoint" && (
                      <>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Site URL *</label>
                          <input type="url" value={spSiteUrl} onChange={e => setSpSiteUrl(e.target.value)}
                            placeholder="https://mycompany.sharepoint.com/sites/Docs"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Client ID (App ID) *</label>
                          <input type="text" value={spClientId} onChange={e => setSpClientId(e.target.value)}
                            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                        </div>
                        <div>
                          <label className="mb-1 block text-xs font-medium text-slate-600">Client Secret *</label>
                          <input type="password" value={spClientSecret} onChange={e => setSpClientSecret(e.target.value)}
                            placeholder="••••••••••••••••"
                            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" />
                          <p className="mt-1 text-[11px] text-slate-400">Register an app in Azure AD with Sites.Read.All permission and generate a client secret.</p>
                        </div>
                      </>
                    )}
                  </div>
                )}

                {/* ── Step 3: Name + collection ── */}
                {step === 3 && (
                  <div className="space-y-4">
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-600">Connector Name</label>
                      <input
                        type="text"
                        value={connName}
                        onChange={e => setConnName(e.target.value)}
                        required
                        autoFocus
                        placeholder="e.g. Product Docs, Marketing Site"
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                      />
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-slate-600">Assign to Collection (optional)</label>
                      <select
                        value={connCollection}
                        onChange={e => setConnCollection(e.target.value)}
                        className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                      >
                        <option value="">— No collection —</option>
                        {collections.map(c => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-500 space-y-1">
                      <p className="font-medium text-slate-700">Summary</p>
                      <p>Type: <span className="font-medium">{TYPE_ICON[selectedType]} {TYPE_LABEL[selectedType]}</span></p>
                      {selectedType === "web" && <p>URLs: <span className="font-medium">{webUrls.split("\n").filter(Boolean).length}</span> | Depth: <span className="font-medium">{webDepth}</span></p>}
                      {selectedType === "google_drive" && <p>Folder ID: <span className="font-medium font-mono">{gdriveFolderId}</span></p>}
                      {selectedType === "confluence" && <p>Spaces: <span className="font-medium">{confSpaceKeys || "All spaces"}</span></p>}
                      {selectedType === "aws_s3" && <p>Bucket: <span className="font-medium font-mono">{s3Bucket}</span> ({s3Region}){s3Prefix ? ` / ${s3Prefix}` : ""}</p>}
                      {selectedType === "azure_data_lake" && <p>Account: <span className="font-medium font-mono">{azAccount}</span> / Container: <span className="font-medium">{azContainer}</span></p>}
                      {selectedType === "gcs" && <p>Bucket: <span className="font-medium font-mono">{gcsBucket}</span>{gcsPrefix ? ` / ${gcsPrefix}` : ""}</p>}
                      {selectedType === "sharepoint" && <p>Site: <span className="font-medium truncate max-w-[200px] inline-block">{spSiteUrl}</span></p>}
                    </div>
                  </div>
                )}

                {formError && (
                  <p className="text-xs text-red-600 flex items-center gap-1">
                    <span>⚠</span> {formError}
                  </p>
                )}
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between border-t border-slate-200 px-5 py-4 shrink-0">
                <button
                  type="button"
                  onClick={step === 1 ? closeModal : () => setStep(prev => (prev > 1 ? (prev - 1) as WizardStep : prev))}
                  className="rounded-lg px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 transition-colors"
                >
                  {step === 1 ? "Cancel" : "Back"}
                </button>
                {step < 3 ? (
                  <button
                    type="button"
                    onClick={nextStep}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors"
                  >
                    Next
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={submitting || !connName.trim()}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40 transition-colors"
                  >
                    {submitting ? "Creating…" : "Create Connector"}
                  </button>
                )}
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
