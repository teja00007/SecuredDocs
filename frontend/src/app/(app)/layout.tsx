"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { isAuthenticated, getAccessToken } from "@/lib/auth";
import AppSidebar from "@/components/AppSidebar";
import GlobalSearch from "@/components/GlobalSearch";
import IncomingCallOverlay from "@/components/IncomingCallOverlay";
import NotificationBell from "@/components/NotificationBell";

const PAGE_TITLES: Record<string, string> = {
  "/":                       "AI Chat",
  "/chat":                   "Messages",
  "/calendar":               "Calendar",
  "/documents":              "Documents",
  "/shared":                 "Shared",
  "/collections":            "Collections",
  "/teams":                  "Teams",
  "/meet":                   "Meet",
  "/profile":                "Profile",
  "/admin":                  "Admin",
  "/admin/compliance":       "Compliance",
  "/admin/analytics":        "Analytics",
  "/admin/connectors":       "Data Connectors",
  "/admin/evaluation":       "RAG Evaluation",
  "/admin/branding":         "Branding",
  "/admin/webhooks":         "Webhooks",
  "/admin/widget":           "Embed Widget",
  "/data":                   "Data Explorer",
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router   = useRouter();
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    // Check if JWT is expired by decoding the exp claim
    try {
      const token = getAccessToken();
      if (token) {
        const payload = JSON.parse(atob(token.split(".")[1]));
        if (payload.exp && payload.exp * 1000 < Date.now()) {
          router.replace("/login");
        }
      }
    } catch { /* malformed token — ignore, api interceptor will handle 401 */ }
  }, [router]);

  // Apply organisation branding (primary_color, org_name) from public endpoint
  useEffect(() => {
    const BASE = process.env.NEXT_PUBLIC_API_URL || "";
    fetch(`${BASE}/api/v1/admin/branding`, { method: "GET" })
      .then(r => r.ok ? r.json() : null)
      .then((data: { primary_color?: string; org_name?: string; logo_url?: string } | null) => {
        if (!data) return;
        if (data.primary_color) {
          document.documentElement.style.setProperty("--brand-primary", data.primary_color);
        }
        if (data.org_name) {
          document.title = data.org_name;
        }
      })
      .catch(() => { /* ignore — branding is non-critical */ });
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  const pageTitle =
    Object.entries(PAGE_TITLES).find(([href]) =>
      href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/")
    )?.[1] ?? "Nexus";

  return (
    <div className="flex h-dvh overflow-hidden bg-slate-50">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <div
        className={`fixed inset-y-0 left-0 z-50 w-72 md:w-[296px] shrink-0 transition-transform duration-200 md:static md:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <Suspense fallback={null}><AppSidebar onClose={() => setSidebarOpen(false)} /></Suspense>
      </div>

      {/* Main area */}
      <div className="flex flex-1 min-w-0 flex-col overflow-hidden">

        {/* ── Desktop top bar ── */}
        <header className="hidden md:flex items-center gap-4 border-b border-gray-100 bg-white px-5 py-2 shrink-0">
          {/* Left spacer keeps search centered */}
          <div className="w-24 shrink-0" />

          {/* Centered search */}
          <div className="flex-1 max-w-xl mx-auto">
            <GlobalSearch />
          </div>

          {/* Right: notification bell + profile button */}
          <div className="w-24 shrink-0 flex items-center justify-end gap-1">
            <NotificationBell />
            <Link
              href="/profile"
              className={`flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm transition-colors ${
                pathname === "/profile"
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-gray-500 hover:bg-gray-100 hover:text-gray-900"
              }`}
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinecap="round" className="w-4 h-4 shrink-0">
                <circle cx="12" cy="8" r="4" />
                <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
              </svg>
              <span className="text-xs font-medium">Profile</span>
            </Link>
          </div>
        </header>

        {/* ── Mobile top bar ── */}
        <header className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-2.5 md:hidden shrink-0">
          <button
            onClick={() => setSidebarOpen(true)}
            className="rounded-md p-1.5 text-gray-600 hover:bg-gray-100"
            aria-label="Open menu"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="flex-1 flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-indigo-600 text-xs font-bold text-white">N</div>
            <span className="text-sm font-semibold text-gray-900">{pageTitle}</span>
          </div>
          <NotificationBell />
          <Link href="/profile" className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5">
              <circle cx="12" cy="8" r="4" /><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
            </svg>
          </Link>
        </header>

        {/* Page content */}
        <div className="flex flex-1 min-h-0 overflow-hidden">
          {children}
        </div>
      </div>

      {/* Incoming call ringing overlay — shown on every authenticated page */}
      {/* <IncomingCallOverlay /> */}
    </div>
  );
}
