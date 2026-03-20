"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";

// ── Types ─────────────────────────────────────────────────────────────────────

type WebhookEvent =
  | "document.uploaded"
  | "document.ingested"
  | "query.completed"
  | "user.created"
  | "message.sent"
  | "calendar.event.created";

interface Webhook {
  id: string;
  name: string;
  url: string;
  events: WebhookEvent[];
  is_active: boolean;
  last_triggered_at: string | null;
  created_at: string;
}

interface CreateWebhookResponse {
  id: string;
  name: string;
  url: string;
  events: WebhookEvent[];
  is_active: boolean;
  secret: string;
  created_at: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ALL_EVENTS: WebhookEvent[] = [
  "document.uploaded",
  "document.ingested",
  "query.completed",
  "user.created",
  "message.sent",
  "calendar.event.created",
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return "Never";
  const delta = Date.now() - new Date(iso).getTime();
  const m = Math.floor(delta / 60000);
  if (m < 1) return "Just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function truncateUrl(url: string, max = 42): string {
  return url.length > max ? `${url.slice(0, max)}…` : url;
}

// ── Secret Banner (shown once after creation) ─────────────────────────────────

function SecretBanner({
  secret,
  name,
  onDismiss,
}: {
  secret: string;
  name: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);

  function copy() {
    navigator.clipboard.writeText(secret).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  }

  return (
    <div className="mb-5 rounded-xl border border-yellow-200 bg-yellow-50 p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="font-semibold text-yellow-800">
            Webhook &quot;{name}&quot; created
          </p>
          <p className="mt-0.5 text-xs text-yellow-600">
            Copy the signing secret now — it will never be shown again.
          </p>
        </div>
        <button
          onClick={onDismiss}
          className="ml-4 text-lg font-bold leading-none text-yellow-500 hover:text-yellow-700"
          aria-label="Dismiss"
        >
          ×
        </button>
      </div>
      <div className="mt-3 flex gap-2">
        <input
          readOnly
          value={secret}
          className="flex-1 rounded-lg border border-gray-200 bg-white px-3 py-2 font-mono text-sm text-gray-800 outline-none"
          onFocus={(e) => e.target.select()}
        />
        <button
          onClick={copy}
          className="rounded-lg bg-yellow-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-yellow-700"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
    </div>
  );
}

// ── Add Webhook Modal ─────────────────────────────────────────────────────────

interface AddModalProps {
  onClose: () => void;
  onCreated: (wh: CreateWebhookResponse) => void;
}

function AddWebhookModal({ onClose, onCreated }: AddModalProps) {
  const { error: toastError } = useToast();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [selectedEvents, setSelectedEvents] = useState<WebhookEvent[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  function toggleEvent(ev: WebhookEvent) {
    setSelectedEvents((prev) =>
      prev.includes(ev) ? prev.filter((e) => e !== ev) : [...prev, ev]
    );
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    if (!name.trim()) { setFormError("Name is required."); return; }
    if (!url.trim()) { setFormError("URL is required."); return; }
    if (selectedEvents.length === 0) {
      setFormError("Select at least one event.");
      return;
    }
    setSubmitting(true);
    try {
      const created = await api.post<CreateWebhookResponse>("/api/v1/webhooks", {
        name: name.trim(),
        url: url.trim(),
        events: selectedEvents,
      });
      onCreated(created);
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Failed to create webhook");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h3 className="font-semibold text-gray-900">Add Webhook</h3>
          <button
            onClick={onClose}
            className="text-gray-400 transition-colors hover:text-gray-600"
            aria-label="Close"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              className="h-4 w-4"
            >
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
          {/* Name */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700">
              Name
            </label>
            <input
              type="text"
              required
              autoFocus
              maxLength={128}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Slack notifications"
              className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
            />
          </div>

          {/* URL */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-gray-700">
              Endpoint URL
            </label>
            <input
              type="url"
              required
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://hooks.example.com/nexus"
              className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
            />
          </div>

          {/* Events checkboxes */}
          <div>
            <p className="mb-2 text-sm font-medium text-gray-700">Events</p>
            <div className="space-y-2.5">
              {ALL_EVENTS.map((ev) => (
                <label
                  key={ev}
                  className="flex cursor-pointer items-center gap-2.5"
                >
                  <input
                    type="checkbox"
                    checked={selectedEvents.includes(ev)}
                    onChange={() => toggleEvent(ev)}
                    className="h-4 w-4 rounded border-gray-300 bg-white text-gray-900 focus:ring-gray-400"
                  />
                  <span className="font-mono text-sm text-gray-700">{ev}</span>
                </label>
              ))}
            </div>
          </div>

          {formError && (
            <p className="flex items-center gap-1 text-xs text-red-500">
              <span>⚠</span> {formError}
            </p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm text-gray-600 transition-colors hover:bg-gray-100"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800 disabled:opacity-40"
            >
              {submitting ? "Creating…" : "Create Webhook"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WebhooksPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();

  const [webhooks, setWebhooks] = useState<Webhook[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddModal, setShowAddModal] = useState(false);
  const [newSecret, setNewSecret] = useState<{
    secret: string;
    name: string;
  } | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);

  // Auth guard
  useEffect(() => {
    if (!isAuthenticated()) {
      router.replace("/login");
      return;
    }
    fetchWebhooks();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function fetchWebhooks() {
    setLoading(true);
    try {
      const data = await api.get<Webhook[]>("/api/v1/webhooks");
      setWebhooks(data);
    } catch (err: unknown) {
      toastError(
        err instanceof Error ? err.message : "Failed to load webhooks"
      );
    } finally {
      setLoading(false);
    }
  }

  function handleCreated(wh: CreateWebhookResponse) {
    setShowAddModal(false);
    setNewSecret({ secret: wh.secret, name: wh.name });
    // Add to list without the secret
    const { secret: _s, ...listItem } = wh;
    setWebhooks((prev) => [listItem as Webhook, ...prev]);
  }

  async function handleToggle(id: string, currentlyActive: boolean) {
    setToggling(id);
    try {
      const updated = await api.patch<Webhook>(`/api/v1/webhooks/${id}`, {
        is_active: !currentlyActive,
      });
      setWebhooks((prev) => prev.map((w) => (w.id === id ? updated : w)));
    } catch (err: unknown) {
      toastError(
        err instanceof Error ? err.message : "Failed to update webhook"
      );
    } finally {
      setToggling(null);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete webhook "${name}"? This cannot be undone.`)) return;
    setDeleting(id);
    try {
      await api.delete(`/api/v1/webhooks/${id}`);
      setWebhooks((prev) => prev.filter((w) => w.id !== id));
      success("Webhook deleted");
    } catch (err: unknown) {
      toastError(
        err instanceof Error ? err.message : "Failed to delete webhook"
      );
    } finally {
      setDeleting(null);
    }
  }

  async function handleTest(id: string) {
    setTesting(id);
    try {
      const res = await api.post<{ status: number; ok: boolean; message?: string }>(
        `/api/v1/webhooks/${id}/test`,
        {}
      );
      if (res.ok) {
        success(`Test delivered — HTTP ${res.status}`);
      } else {
        toastError(
          `Test failed — HTTP ${res.status}${res.message ? `: ${res.message}` : ""}`
        );
      }
    } catch (err: unknown) {
      toastError(
        err instanceof Error ? err.message : "Test delivery failed"
      );
    } finally {
      setTesting(null);
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
            <span className="text-gray-300">/</span>
            <div>
              <h1 className="font-semibold text-gray-900">Outbound Webhooks</h1>
              <p className="text-xs text-gray-400 mt-0.5">Receive real-time event notifications at your endpoints</p>
            </div>
          </div>
          <button
            onClick={() => setShowAddModal(true)}
            className="rounded-lg bg-black px-3.5 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
          >
            + Add Webhook
          </button>
        </div>
      </div>

      <div className="mx-auto w-full max-w-6xl p-6">
        {/* Secret banner — shown once after creation */}
        {newSecret && (
          <SecretBanner
            secret={newSecret.secret}
            name={newSecret.name}
            onDismiss={() => setNewSecret(null)}
          />
        )}

        {loading ? (
          <div className="flex items-center justify-center py-20">
            <div className="h-7 w-7 animate-spin rounded-full border-2 border-gray-900 border-t-transparent" />
          </div>
        ) : webhooks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <p className="text-lg font-medium text-gray-700">No webhooks yet</p>
            <p className="mt-1 text-sm text-gray-400">
              Add an endpoint to start receiving Nexus event notifications.
            </p>
            <button
              onClick={() => setShowAddModal(true)}
              className="mt-4 rounded-lg bg-black px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-800"
            >
              + Add Webhook
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-100 bg-gray-50 text-xs font-semibold uppercase tracking-wide text-gray-500">
                <tr>
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-left">URL</th>
                  <th className="px-4 py-3 text-left">Events</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Last Triggered</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {webhooks.map((wh) => (
                  <tr
                    key={wh.id}
                    className="transition-colors hover:bg-gray-50"
                  >
                    {/* Name */}
                    <td className="px-4 py-3 font-medium text-gray-800">
                      {wh.name}
                    </td>

                    {/* URL (truncated) */}
                    <td className="px-4 py-3">
                      <span
                        className="font-mono text-xs text-gray-500"
                        title={wh.url}
                      >
                        {truncateUrl(wh.url)}
                      </span>
                    </td>

                    {/* Events (badges) */}
                    <td className="px-4 py-3">
                      <div className="flex max-w-[240px] flex-wrap gap-1">
                        {wh.events.map((ev) => (
                          <span
                            key={ev}
                            className="rounded-full border border-gray-200 bg-gray-100 px-1.5 py-0.5 text-[10px] font-medium text-gray-600"
                          >
                            {ev}
                          </span>
                        ))}
                      </div>
                    </td>

                    {/* Active / inactive toggle */}
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleToggle(wh.id, wh.is_active)}
                          disabled={toggling === wh.id}
                          aria-label={
                            wh.is_active ? "Deactivate webhook" : "Activate webhook"
                          }
                          className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none disabled:opacity-50 ${
                            wh.is_active ? "bg-black" : "bg-gray-200"
                          }`}
                        >
                          <span
                            className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform duration-200 ${
                              wh.is_active ? "translate-x-4" : "translate-x-0"
                            }`}
                          />
                        </button>
                        <span
                          className={`text-xs ${
                            wh.is_active ? "text-emerald-600" : "text-gray-400"
                          }`}
                        >
                          {wh.is_active ? "Active" : "Inactive"}
                        </span>
                      </div>
                    </td>

                    {/* Last triggered */}
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {timeAgo(wh.last_triggered_at)}
                    </td>

                    {/* Actions: send test + delete */}
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleTest(wh.id)}
                          disabled={testing === wh.id}
                          className="rounded-lg border border-gray-200 px-2.5 py-1 text-xs text-gray-600 transition-colors hover:bg-gray-50 disabled:opacity-40"
                        >
                          {testing === wh.id ? "Sending…" : "Send Test"}
                        </button>
                        <button
                          onClick={() => handleDelete(wh.id, wh.name)}
                          disabled={deleting === wh.id}
                          className="rounded-lg px-2.5 py-1 text-xs text-red-500 transition-colors hover:bg-red-50 disabled:opacity-40"
                        >
                          {deleting === wh.id ? "Deleting…" : "Delete"}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add Webhook Modal */}
      {showAddModal && (
        <AddWebhookModal
          onClose={() => setShowAddModal(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
