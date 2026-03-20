"use client";

import { useEffect, useState, FormEvent, useRef } from "react";
import { useRouter } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface APIKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  last_used_at: string | null;
  expires_at: string | null;
  is_active: boolean;
  created_at: string;
}

interface CreateAPIKeyResponse {
  id: string;
  name: string;
  key: string; // full key — shown once
  key_prefix: string;
  scopes: string[];
  expires_at: string | null;
  created_at: string;
}

const AVAILABLE_SCOPES = [
  { value: "query", label: "Query (run RAG queries)" },
  { value: "documents:read", label: "Documents: Read" },
  { value: "documents:write", label: "Documents: Write / Upload" },
];

const EXPIRY_OPTIONS = [
  { label: "Never", value: null },
  { label: "30 days", value: 30 },
  { label: "90 days", value: 90 },
  { label: "1 year", value: 365 },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function relDate(iso: string | null): string {
  if (!iso) return "Never";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const delta = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  return new Date(expiresAt) < new Date();
}

// ---------------------------------------------------------------------------
// Copyable key box
// ---------------------------------------------------------------------------

function NewKeyBox({ rawKey }: { rawKey: string }) {
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleCopy = () => {
    navigator.clipboard.writeText(rawKey).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  };

  return (
    <div className="mt-4 rounded-lg border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 dark:border-yellow-600 p-4">
      <p className="text-sm font-semibold text-yellow-800 dark:text-yellow-300 mb-2">
        Copy this key now — it will never be shown again.
      </p>
      <div className="flex gap-2">
        <input
          ref={inputRef}
          readOnly
          value={rawKey}
          className="flex-1 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 font-mono text-sm text-gray-900 dark:text-gray-100 focus:outline-none"
          onFocus={(e) => e.target.select()}
        />
        <button
          type="button"
          onClick={handleCopy}
          className="rounded bg-yellow-500 hover:bg-yellow-600 text-white px-4 py-2 text-sm font-medium transition-colors"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create Key Modal
// ---------------------------------------------------------------------------

interface CreateModalProps {
  onClose: () => void;
  onCreated: (newKey: CreateAPIKeyResponse) => void;
}

function CreateKeyModal({ onClose, onCreated }: CreateModalProps) {
  const { error: toastError } = useToast();
  const [name, setName] = useState("");
  const [selectedScopes, setSelectedScopes] = useState<string[]>(["query"]);
  const [expiresInDays, setExpiresInDays] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const toggleScope = (scope: string) => {
    setSelectedScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope]
    );
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    if (selectedScopes.length === 0) {
      toastError("Select at least one scope.");
      return;
    }
    setSubmitting(true);
    try {
      const data = await api.post<CreateAPIKeyResponse>("/api/v1/api-keys", {
        name: name.trim(),
        scopes: selectedScopes,
        expires_in_days: expiresInDays,
      });
      onCreated(data);
    } catch (err: any) {
      toastError(err.message || "Failed to create API key");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-2xl bg-white dark:bg-gray-900 shadow-2xl p-6">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-white mb-4">
          Create API Key
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Key name
            </label>
            <input
              type="text"
              required
              maxLength={128}
              placeholder="e.g. CI pipeline key"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Scopes */}
          <div>
            <p className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
              Scopes
            </p>
            <div className="space-y-2">
              {AVAILABLE_SCOPES.map((s) => (
                <label key={s.value} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selectedScopes.includes(s.value)}
                    onChange={() => toggleScope(s.value)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-sm text-gray-700 dark:text-gray-300">{s.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Expiry */}
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Expires
            </label>
            <select
              value={expiresInDays === null ? "" : String(expiresInDays)}
              onChange={(e) =>
                setExpiresInDays(e.target.value === "" ? null : Number(e.target.value))
              }
              className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {EXPIRY_OPTIONS.map((opt) => (
                <option key={String(opt.value)} value={opt.value === null ? "" : String(opt.value)}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white px-5 py-2 text-sm font-medium transition-colors"
            >
              {submitting ? "Creating…" : "Create Key"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function APIKeysPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();

  const [keys, setKeys] = useState<APIKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newlyCreated, setNewlyCreated] = useState<CreateAPIKeyResponse | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);

  // Auth guard
  useEffect(() => {
    if (!isAuthenticated()) router.replace("/login");
  }, [router]);

  // Fetch keys
  const fetchKeys = async () => {
    setLoading(true);
    try {
      const data = await api.get<APIKey[]>("/api/v1/api-keys");
      setKeys(data);
    } catch (err: any) {
      toastError(err.message || "Failed to load API keys");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchKeys();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCreated = (created: CreateAPIKeyResponse) => {
    setNewlyCreated(created);
    setShowCreateModal(false);
    fetchKeys();
  };

  const handleRevoke = async (keyId: string, keyName: string) => {
    if (!confirm(`Revoke API key "${keyName}"? This cannot be undone.`)) return;
    setRevoking(keyId);
    try {
      await api.delete(`/api/v1/api-keys/${keyId}`);
      success("API key revoked");
      setKeys((prev) =>
        prev.map((k) => (k.id === keyId ? { ...k, is_active: false } : k))
      );
    } catch (err: any) {
      toastError(err.message || "Failed to revoke API key");
    } finally {
      setRevoking(null);
    }
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">API Keys</h1>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            API keys let you authenticate with the Nexus API from scripts and CI pipelines.
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="rounded-lg bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 text-sm font-medium transition-colors"
        >
          + Create API Key
        </button>
      </div>

      {/* Newly created key — shown once */}
      {newlyCreated && (
        <div className="mb-6 rounded-xl border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/20 dark:border-yellow-600 p-5">
          <div className="flex items-start justify-between">
            <div>
              <p className="font-semibold text-yellow-800 dark:text-yellow-300">
                API key created: <span className="font-mono">{newlyCreated.name}</span>
              </p>
              <p className="text-xs text-yellow-700 dark:text-yellow-400 mt-1">
                Copy the key below. It will never be shown again after you dismiss this banner.
              </p>
            </div>
            <button
              onClick={() => setNewlyCreated(null)}
              className="text-yellow-600 hover:text-yellow-900 dark:text-yellow-400 dark:hover:text-yellow-100 ml-4 text-lg font-bold leading-none"
              aria-label="Dismiss"
            >
              ×
            </button>
          </div>
          <NewKeyBox rawKey={newlyCreated.key} />
          <p className="mt-2 text-xs text-yellow-700 dark:text-yellow-400">
            Scopes: {newlyCreated.scopes.join(", ")} &nbsp;·&nbsp;
            Expires: {relDate(newlyCreated.expires_at)}
          </p>
        </div>
      )}

      {/* Keys table */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-gray-400">
          Loading…
        </div>
      ) : keys.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 dark:border-gray-700 py-16 text-center text-gray-500 dark:text-gray-400">
          <p className="text-lg font-medium mb-1">No API keys yet</p>
          <p className="text-sm">Create your first key to get started.</p>
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
              <tr>
                <th className="px-4 py-3">Name / Prefix</th>
                <th className="px-4 py-3">Scopes</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Last used</th>
                <th className="px-4 py-3">Expires</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {keys.map((k) => {
                const expired = isExpired(k.expires_at);
                const active = k.is_active && !expired;
                return (
                  <tr
                    key={k.id}
                    className="bg-white dark:bg-gray-900 hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-900 dark:text-white">{k.name}</p>
                      <p className="font-mono text-xs text-gray-400">{k.key_prefix}…</p>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {k.scopes.map((scope) => (
                          <span
                            key={scope}
                            className="inline-flex items-center rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 px-2 py-0.5 text-xs font-medium"
                          >
                            {scope}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                      {relDate(k.created_at)}
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                      {timeAgo(k.last_used_at)}
                    </td>
                    <td className="px-4 py-3 text-gray-500 dark:text-gray-400">
                      {k.expires_at ? (
                        <span className={expired ? "text-red-500" : ""}>
                          {relDate(k.expires_at)}
                        </span>
                      ) : (
                        "Never"
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                          active
                            ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                            : "bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"
                        }`}
                      >
                        {active ? "Active" : expired ? "Expired" : "Revoked"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {k.is_active && !expired && (
                        <button
                          onClick={() => handleRevoke(k.id, k.name)}
                          disabled={revoking === k.id}
                          className="rounded-lg border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 px-3 py-1 text-xs font-medium transition-colors disabled:opacity-50"
                        >
                          {revoking === k.id ? "Revoking…" : "Revoke"}
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Create modal */}
      {showCreateModal && (
        <CreateKeyModal
          onClose={() => setShowCreateModal(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
