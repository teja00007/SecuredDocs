"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { logout } from "@/lib/auth";
import type { Collection, Team } from "@/types";

interface Props {
  collections: Collection[];
  teams: Team[];
  activeCollectionId?: string | null;
  onSelectCollection: (id: string | null) => void;
  username?: string;
  isAdmin?: boolean;
}

export default function Sidebar({
  collections,
  teams,
  activeCollectionId,
  onSelectCollection,
  username,
  isAdmin,
}: Props) {
  const pathname = usePathname();

  const navLinks = [
    { href: "/", label: "RAG Chat", icon: "🤖" },
    { href: "/chat", label: "Messaging", icon: "💬" },
    { href: "/calendar", label: "Calendar", icon: "📅" },
    { href: "/documents", label: "Documents", icon: "📄" },
    { href: "/shared", label: "Shared with me", icon: "📂" },
    { href: "/collections", label: "Collections", icon: "🗂️" },
    { href: "/teams", label: "Teams", icon: "👥" },
    ...(isAdmin ? [
      { href: "/admin", label: "Admin", icon: "⚙️" },
      { href: "/admin/compliance", label: "Compliance", icon: "🛡️" },
      { href: "/admin/analytics", label: "Analytics", icon: "📊" },
    ] : []),
  ];

  return (
    <aside className="flex h-screen w-60 flex-col border-r border-slate-200 bg-white">
      {/* Logo */}
      <div className="border-b border-slate-200 px-4 py-4">
        <h1 className="text-lg font-bold text-blue-700">Enterprise RAG</h1>
        {username && (
          <p className="mt-0.5 truncate text-xs text-slate-500">{username}</p>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="space-y-0.5">
          {navLinks.map((link) => (
            <li key={link.href}>
              <Link
                href={link.href}
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  pathname === link.href
                    ? "bg-blue-50 text-blue-700"
                    : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                <span>{link.icon}</span>
                {link.label}
              </Link>
            </li>
          ))}
        </ul>

        {/* Collections scope */}
        {collections.length > 0 && pathname === "/" && (
          <div className="mt-4">
            <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
              Collections
            </p>
            <ul className="space-y-0.5">
              <li>
                <button
                  onClick={() => onSelectCollection(null)}
                  className={`w-full rounded-lg px-3 py-1.5 text-left text-sm transition-colors ${
                    activeCollectionId == null
                      ? "bg-blue-50 text-blue-700"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                >
                  All collections
                </button>
              </li>
              {collections.map((c) => (
                <li key={c.id}>
                  <button
                    onClick={() => onSelectCollection(c.id)}
                    className={`w-full truncate rounded-lg px-3 py-1.5 text-left text-sm transition-colors ${
                      activeCollectionId === c.id
                        ? "bg-blue-50 text-blue-700"
                        : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {c.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Teams */}
        {teams.length > 0 && (
          <div className="mt-4">
            <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
              My Teams
            </p>
            <ul className="space-y-0.5">
              {teams.map((t) => (
                <li
                  key={t.id}
                  className="truncate rounded-lg px-3 py-1.5 text-sm text-slate-500"
                  title={t.name}
                >
                  {t.name}
                </li>
              ))}
            </ul>
          </div>
        )}
      </nav>

      {/* Logout */}
      <div className="border-t border-slate-200 p-3">
        <button
          onClick={logout}
          className="w-full rounded-lg px-3 py-2 text-left text-sm text-slate-600 hover:bg-slate-100"
        >
          Sign out
        </button>
      </div>
    </aside>
  );
}
