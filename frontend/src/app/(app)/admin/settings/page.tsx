"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { User } from "@/types";

interface SystemSettings {
  llm_provider: string;
  llm_model: string;
  ollama_base_url: string;
  openai_api_key_set: boolean;
  anthropic_api_key_set: boolean;
  openai_api_key_hint: string;
  anthropic_api_key_hint: string;
  invite_only: boolean;
  allowed_signup_domains: string;
  max_upload_size_mb: number;
  smtp_configured: boolean;
  redis_configured: boolean;
  smtp_host: string;
  smtp_port: string;
  smtp_user: string;
  smtp_from: string;
  redis_url: string;
}

const LLM_PROVIDERS = ["openai", "anthropic", "ollama"] as const;

const DEFAULT_MODELS: Record<string, string[]> = {
  openai:    ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
  anthropic: ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
  ollama:    ["llama3.2", "mistral", "gemma2", "llama3.1", "phi3", "deepseek-r1"],
};

function Field({
  label, hint, type = "text", value, onChange, placeholder, mono,
}: {
  label: string; hint?: string; type?: string;
  value: string; onChange: (v: string) => void;
  placeholder?: string; mono?: boolean;
}) {
  const [show, setShow] = useState(false);
  const isPassword = type === "password";
  return (
    <div>
      <label className="mb-1.5 block text-sm font-medium text-gray-700">{label}</label>
      <div className="relative">
        <input
          type={isPassword && !show ? "password" : "text"}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className={`w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100 ${mono ? "font-mono" : ""} ${isPassword ? "pr-10" : ""}`}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShow(v => !v)}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
          >
            {show ? "Hide" : "Show"}
          </button>
        )}
      </div>
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [settings, setSettings] = useState<SystemSettings | null>(null);

  // LLM form state
  const [llmProvider, setLlmProvider] = useState("openai");
  const [llmModel, setLlmModel] = useState("gpt-4o");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [customModel, setCustomModel] = useState("");
  const [useCustomModel, setUseCustomModel] = useState(false);

  // API keys state
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");

  // SMTP state
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState("587");
  const [smtpUser, setSmtpUser] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [smtpFrom, setSmtpFrom] = useState("");

  // Redis state
  const [redisUrl, setRedisUrl] = useState("");

  // System settings form state
  const [inviteOnly, setInviteOnly] = useState(false);
  const [allowedDomains, setAllowedDomains] = useState("");
  const [maxUploadMb, setMaxUploadMb] = useState(50);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    api.get<User>("/api/v1/auth/me").then(u => {
      if (!u.roles.includes("admin")) { router.replace("/"); return; }
      loadSettings();
    }).catch(() => router.replace("/login"));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function loadSettings() {
    try {
      const data = await api.get<SystemSettings>("/api/v1/admin/settings");
      setSettings(data);
      setLlmProvider(data.llm_provider || "openai");
      const knownModels = DEFAULT_MODELS[data.llm_provider] ?? [];
      if (data.llm_model && !knownModels.includes(data.llm_model)) {
        setUseCustomModel(true);
        setCustomModel(data.llm_model);
        setLlmModel(knownModels[0] ?? "");
      } else {
        setLlmModel(data.llm_model || knownModels[0] || "");
      }
      setOllamaUrl(data.ollama_base_url || "http://localhost:11434");
      setInviteOnly(data.invite_only);
      setAllowedDomains(data.allowed_signup_domains || "");
      setMaxUploadMb(data.max_upload_size_mb || 50);
      setSmtpHost(data.smtp_host || "");
      setSmtpPort(data.smtp_port || "587");
      setSmtpUser(data.smtp_user || "");
      setSmtpFrom(data.smtp_from || "");
      setRedisUrl(data.redis_url || "");
    } catch {
      toastError("Failed to load settings");
    } finally {
      setLoading(false);
    }
  }

  async function saveLlmSettings(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const effectiveModel = useCustomModel ? customModel.trim() : llmModel;
      await api.patch("/api/v1/admin/settings", {
        llm_provider: llmProvider,
        llm_model: effectiveModel,
        ...(llmProvider === "ollama" ? { ollama_base_url: ollamaUrl } : {}),
      });
      success("LLM settings saved");
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Failed to save LLM settings");
    } finally {
      setSaving(false);
    }
  }

  async function saveApiKeys(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload: Record<string, string> = {};
      if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim();
      if (anthropicKey.trim()) payload.anthropic_api_key = anthropicKey.trim();
      if (!Object.keys(payload).length) {
        toastError("Enter at least one API key to save");
        return;
      }
      await api.patch("/api/v1/admin/env", payload);
      success("API keys saved — active immediately");
      setOpenaiKey("");
      setAnthropicKey("");
      await loadSettings();
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Failed to save API keys");
    } finally {
      setSaving(false);
    }
  }

  async function saveSmtp(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/api/v1/admin/env", {
        smtp_host: smtpHost,
        smtp_port: smtpPort,
        smtp_user: smtpUser,
        ...(smtpPassword ? { smtp_password: smtpPassword } : {}),
        smtp_from: smtpFrom,
      });
      success("SMTP settings saved — active immediately");
      setSmtpPassword("");
      await loadSettings();
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Failed to save SMTP settings");
    } finally {
      setSaving(false);
    }
  }

  async function saveRedis(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/api/v1/admin/env", { redis_url: redisUrl });
      success("Redis URL saved — active immediately");
      await loadSettings();
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Failed to save Redis URL");
    } finally {
      setSaving(false);
    }
  }

  async function saveSystemSettings(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/api/v1/admin/settings", {
        invite_only: inviteOnly,
        allowed_signup_domains: allowedDomains,
        max_upload_size_mb: maxUploadMb,
      });
      success("System settings saved");
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  function onProviderChange(p: string) {
    setLlmProvider(p);
    const models = DEFAULT_MODELS[p] ?? [];
    setLlmModel(models[0] ?? "");
    setUseCustomModel(false);
    setCustomModel("");
  }

  if (loading) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden bg-gray-50">
        <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700">← Admin</Link>
            <span className="text-gray-300">/</span>
            <h1 className="font-semibold text-gray-900">Settings</h1>
          </div>
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-900 border-t-transparent" />
        </div>
      </div>
    );
  }

  const modelList = DEFAULT_MODELS[llmProvider] ?? [];

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center gap-3">
          <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
          <span className="text-gray-300">/</span>
          <div>
            <h1 className="font-semibold text-gray-900">System Settings</h1>
            <p className="text-xs text-gray-400 mt-0.5">Configure LLM provider, API keys, SMTP, Redis, and access controls</p>
          </div>
        </div>
      </div>

      <div className="flex-1 p-6">
        <div className="mx-auto max-w-2xl space-y-6">

          {/* ── API Keys ── */}
          <form onSubmit={saveApiKeys} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">API Keys</h3>
              <p className="mt-0.5 text-xs text-gray-400">Saved to .env and applied immediately — no restart needed</p>
            </div>
            <div className="px-5 py-5 space-y-4">
              {/* Status badges */}
              <div className="grid grid-cols-2 gap-3">
                {[
                  { label: "OpenAI", ok: settings?.openai_api_key_set, hint: settings?.openai_api_key_hint },
                  { label: "Anthropic", ok: settings?.anthropic_api_key_set, hint: settings?.anthropic_api_key_hint },
                ].map(item => (
                  <div key={item.label} className={`rounded-lg border px-3 py-2.5 ${item.ok ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-gray-50"}`}>
                    <div className="flex items-center gap-1.5">
                      <span className={`h-1.5 w-1.5 rounded-full ${item.ok ? "bg-emerald-500" : "bg-gray-400"}`} />
                      <span className="text-xs font-medium text-gray-700">{item.label}</span>
                    </div>
                    <p className="mt-0.5 text-xs text-gray-500 font-mono">
                      {item.hint || "Not set"}
                    </p>
                  </div>
                ))}
              </div>

              <Field
                label="OpenAI API Key"
                type="password"
                value={openaiKey}
                onChange={setOpenaiKey}
                placeholder={settings?.openai_api_key_set ? "Enter new key to replace…" : "sk-…"}
                mono
              />
              <Field
                label="Anthropic API Key"
                type="password"
                value={anthropicKey}
                onChange={setAnthropicKey}
                placeholder={settings?.anthropic_api_key_set ? "Enter new key to replace…" : "sk-ant-…"}
                mono
              />
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving || (!openaiKey.trim() && !anthropicKey.trim())}
                className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save API Keys"}
              </button>
            </div>
          </form>

          {/* ── LLM Configuration ── */}
          <form onSubmit={saveLlmSettings} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">LLM Provider</h3>
              <p className="mt-0.5 text-xs text-gray-400">The model used for RAG answer generation</p>
            </div>
            <div className="px-5 py-5 space-y-5">

              {/* Provider */}
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Provider</label>
                <div className="flex gap-2 flex-wrap">
                  {LLM_PROVIDERS.map(p => (
                    <button key={p} type="button" onClick={() => onProviderChange(p)}
                      className={`rounded-lg px-4 py-2 text-sm font-medium border transition-colors capitalize ${
                        llmProvider === p
                          ? "bg-black text-white border-black"
                          : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
                      }`}>
                      {p === "openai" ? "OpenAI" : p === "anthropic" ? "Anthropic" : "Ollama (local)"}
                    </button>
                  ))}
                </div>
              </div>

              {/* Model */}
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <label className="text-sm font-medium text-gray-700">Model</label>
                  <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer">
                    <input type="checkbox" checked={useCustomModel} onChange={e => setUseCustomModel(e.target.checked)}
                      className="accent-black" />
                    Custom model name
                  </label>
                </div>
                {useCustomModel ? (
                  <input type="text" value={customModel} onChange={e => setCustomModel(e.target.value)}
                    placeholder="e.g. gpt-4-vision-preview"
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100" />
                ) : (
                  <select value={llmModel} onChange={e => setLlmModel(e.target.value)}
                    className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-gray-400">
                    {modelList.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                )}
              </div>

              {/* Ollama URL */}
              {llmProvider === "ollama" && (
                <div>
                  <label className="mb-2 block text-sm font-medium text-gray-700">Ollama Base URL</label>
                  <input type="url" value={ollamaUrl} onChange={e => setOllamaUrl(e.target.value)}
                    placeholder="http://localhost:11434"
                    className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100" />
                  <p className="mt-1 text-xs text-gray-400">Make sure Ollama is running and the model is pulled</p>
                </div>
              )}

              {llmProvider === "openai" && !settings?.openai_api_key_set && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3">
                  <p className="text-xs text-amber-700 font-medium">OpenAI API key not configured — set it above</p>
                </div>
              )}
              {llmProvider === "anthropic" && !settings?.anthropic_api_key_set && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3">
                  <p className="text-xs text-amber-700 font-medium">Anthropic API key not configured — set it above</p>
                </div>
              )}
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving}
                className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save LLM Settings"}
              </button>
            </div>
          </form>

          {/* ── SMTP ── */}
          <form onSubmit={saveSmtp} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-gray-700">SMTP Email</h3>
                <p className="mt-0.5 text-xs text-gray-400">Used for invites, notifications, and password resets</p>
              </div>
              <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                settings?.smtp_configured ? "bg-emerald-100 text-emerald-700" : "bg-gray-100 text-gray-500"
              }`}>
                <span className={`h-1.5 w-1.5 rounded-full ${settings?.smtp_configured ? "bg-emerald-500" : "bg-gray-400"}`} />
                {settings?.smtp_configured ? "Configured" : "Not set"}
              </span>
            </div>
            <div className="px-5 py-5 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <Field label="SMTP Host" value={smtpHost} onChange={setSmtpHost} placeholder="smtp.gmail.com" />
                <Field label="Port" value={smtpPort} onChange={setSmtpPort} placeholder="587" />
              </div>
              <Field label="Username / Email" value={smtpUser} onChange={setSmtpUser} placeholder="you@gmail.com" />
              <Field label="Password / App Password" type="password" value={smtpPassword} onChange={setSmtpPassword}
                placeholder="Leave blank to keep current" />
              <Field label="From Address" value={smtpFrom} onChange={setSmtpFrom}
                placeholder="Nexus <no-reply@example.com>"
                hint="Displayed as sender. Defaults to username if blank." />
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving || !smtpHost.trim()}
                className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save SMTP Settings"}
              </button>
            </div>
          </form>

          {/* ── Redis ── */}
          <form onSubmit={saveRedis} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-gray-700">Redis / Celery</h3>
                <p className="mt-0.5 text-xs text-gray-400">Required for background document ingestion jobs</p>
              </div>
              <span className={`flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
                settings?.redis_configured ? "bg-emerald-100 text-emerald-700" : "bg-gray-100 text-gray-500"
              }`}>
                <span className={`h-1.5 w-1.5 rounded-full ${settings?.redis_configured ? "bg-emerald-500" : "bg-gray-400"}`} />
                {settings?.redis_configured ? "Configured" : "Not set"}
              </span>
            </div>
            <div className="px-5 py-5">
              <Field
                label="Redis URL"
                value={redisUrl}
                onChange={setRedisUrl}
                placeholder="redis://localhost:6379/0"
                mono
                hint="Format: redis://[user:pass@]host:port/db"
              />
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving || !redisUrl.trim()}
                className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save Redis URL"}
              </button>
            </div>
          </form>

          {/* ── Access & Upload Settings ── */}
          <form onSubmit={saveSystemSettings} className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">Access & Upload Controls</h3>
            </div>
            <div className="px-5 py-5 space-y-5">

              {/* Invite only */}
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-700">Invite-only registration</p>
                  <p className="text-xs text-gray-400 mt-0.5">When enabled, new users can only join via invite link</p>
                </div>
                <button
                  type="button"
                  onClick={() => setInviteOnly(v => !v)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    inviteOnly ? "bg-black" : "bg-gray-200"
                  }`}
                >
                  <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                    inviteOnly ? "translate-x-6" : "translate-x-1"
                  }`} />
                </button>
              </div>

              {/* Allowed sign-up domains */}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  Allowed sign-up domains
                </label>
                <input
                  type="text"
                  value={allowedDomains}
                  onChange={e => setAllowedDomains(e.target.value)}
                  placeholder="tester.com, corp.io, example.org"
                  className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
                />
                <p className="mt-1 text-xs text-gray-400">
                  Comma-separated. Users with these email domains auto-get a viewer account on first SSO login, even when invite-only is on. Leave blank to allow all domains (when invite-only is off).
                </p>
              </div>

              {/* Max upload size */}
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Max upload size (MB)</label>
                <div className="flex items-center gap-3">
                  <input
                    type="number"
                    min={1}
                    max={2000}
                    value={maxUploadMb}
                    onChange={e => setMaxUploadMb(Number(e.target.value))}
                    className="w-28 rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
                  />
                  <span className="text-sm text-gray-500">MB per file</span>
                </div>
                <p className="mt-1 text-xs text-gray-400">Applies to document uploads. Default: 50 MB</p>
              </div>
            </div>
            <div className="border-t border-gray-100 px-5 py-3 flex justify-end">
              <button type="submit" disabled={saving}
                className="rounded-lg bg-black px-5 py-2 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40 transition-colors">
                {saving ? "Saving…" : "Save Settings"}
              </button>
            </div>
          </form>

        </div>
      </div>
    </div>
  );
}
