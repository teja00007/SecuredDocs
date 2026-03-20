"use client";

import { useEffect, useState, FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SettingEntry {
  key: string;
  value: string;
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function BrandingPage() {
  const router = useRouter();
  const { success, error: toastError } = useToast();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Form state
  const [orgName, setOrgName] = useState("");
  const [primaryColor, setPrimaryColor] = useState("#4f46e5");
  const [logoUrl, setLogoUrl] = useState("");
  const [welcomeMessage, setWelcomeMessage] = useState("");
  const [supportEmail, setSupportEmail] = useState("");

  // Auth guard + load on mount
  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    loadSettings();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  async function loadSettings() {
    try {
      const data = await api.get<Record<string, string>>("/api/v1/admin/branding");
      setOrgName(data["org_name"] ?? "");
      setPrimaryColor(data["primary_color"] ?? "#4f46e5");
      setLogoUrl(data["logo_url"] ?? "");
      setWelcomeMessage(data["login_message"] ?? "");
      setSupportEmail(data["support_email"] ?? "");
    } catch {
      // Ignore — fields remain at defaults
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/api/v1/admin/branding", {
        org_name: orgName,
        primary_color: primaryColor || undefined,
        logo_url: logoUrl || undefined,
        login_message: welcomeMessage || undefined,
      });
      success("Branding settings saved");
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex flex-1 flex-col overflow-hidden bg-gray-50">
        <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
          <div className="flex items-center gap-3">
            <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
            <span className="text-gray-300">/</span>
            <h1 className="font-semibold text-gray-900">Branding &amp; Organization</h1>
          </div>
        </div>
        <div className="flex flex-1 items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-900 border-t-transparent" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto bg-gray-50">
      {/* Header */}
      <div className="border-b border-gray-200 bg-white px-6 py-4 shrink-0">
        <div className="flex items-center gap-3">
          <Link href="/admin" className="text-sm text-gray-400 hover:text-gray-700 transition-colors">← Admin</Link>
          <span className="text-gray-300">/</span>
          <div>
            <h1 className="font-semibold text-gray-900">Branding &amp; Organization</h1>
            <p className="text-xs text-gray-400 mt-0.5">Customize how Nexus appears to your users</p>
          </div>
        </div>
      </div>

      <div className="flex-1 p-6">
        <form onSubmit={handleSubmit} className="mx-auto max-w-2xl space-y-6">

          {/* ── Settings card ── */}
          <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="border-b border-gray-100 px-5 py-4">
              <h3 className="text-sm font-semibold text-gray-700">Organization Settings</h3>
            </div>
            <div className="px-5 py-5 space-y-5">

              {/* Organization Name */}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  Organization Name
                </label>
                <input
                  type="text"
                  value={orgName}
                  onChange={e => setOrgName(e.target.value)}
                  placeholder="Acme Corp"
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
                />
              </div>

              {/* Primary Color */}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  Primary Color
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="color"
                    value={primaryColor}
                    onChange={e => setPrimaryColor(e.target.value)}
                    className="h-10 w-16 cursor-pointer rounded-lg border border-gray-200 bg-white p-0.5"
                  />
                  <span className="font-mono text-sm text-gray-700">{primaryColor.toUpperCase()}</span>
                  {/* Live swatch */}
                  <div
                    className="h-8 w-24 rounded-lg shadow-inner border border-gray-100"
                    style={{ backgroundColor: primaryColor }}
                  />
                </div>
              </div>

              {/* Logo URL */}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  Logo URL
                </label>
                <input
                  type="url"
                  value={logoUrl}
                  onChange={e => setLogoUrl(e.target.value)}
                  placeholder="https://example.com/logo.png"
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
                />
                {/* Live preview */}
                {logoUrl && (
                  <div className="mt-3 flex items-center gap-3">
                    <div className="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-gray-200 bg-gray-50">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={logoUrl}
                        alt="Logo preview"
                        className="h-full w-full object-contain"
                        onError={e => { (e.target as HTMLImageElement).style.display = "none"; }}
                      />
                    </div>
                    <span className="text-xs text-gray-400">Logo preview</span>
                  </div>
                )}
              </div>

              {/* Welcome Message */}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  Welcome Message
                </label>
                <textarea
                  value={welcomeMessage}
                  onChange={e => setWelcomeMessage(e.target.value)}
                  rows={3}
                  placeholder="Welcome to your knowledge base. Sign in to continue."
                  className="w-full resize-none rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
                />
              </div>

              {/* Support Email */}
              <div>
                <label className="mb-1.5 block text-sm font-medium text-gray-700">
                  Support Email
                </label>
                <input
                  type="email"
                  value={supportEmail}
                  onChange={e => setSupportEmail(e.target.value)}
                  placeholder="support@example.com"
                  className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-gray-400 focus:ring-2 focus:ring-gray-100"
                />
              </div>
            </div>
          </div>

          {/* ── Save button ── */}
          <div className="flex justify-end">
            <button
              type="submit"
              disabled={saving}
              className="rounded-lg bg-black px-5 py-2.5 text-sm font-medium text-white hover:bg-gray-800 disabled:opacity-40 transition-colors"
            >
              {saving ? "Saving…" : "Save Settings"}
            </button>
          </div>

        </form>
      </div>
    </div>
  );
}
