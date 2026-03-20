"use client";

import { useState, FormEvent, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

function ResetPasswordForm() {
  const router       = useRouter();
  const searchParams = useSearchParams();
  const token        = searchParams.get("token") ?? "";

  const [newPw,      setNewPw]      = useState("");
  const [confirmPw,  setConfirmPw]  = useState("");
  const [showPw,     setShowPw]     = useState(false);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState("");
  const [success,    setSuccess]    = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (newPw.length < 8) { setError("Password must be at least 8 characters"); return; }
    if (newPw !== confirmPw) { setError("Passwords do not match"); return; }
    if (!token) { setError("Invalid or missing reset token. Please request a new link."); return; }
    setLoading(true);
    try {
      await api.post("/api/v1/auth/reset-password", { token, new_password: newPw });
      setSuccess(true);
      setTimeout(() => router.push("/login"), 2000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to reset password";
      setError(
        msg.toLowerCase().includes("expired") || msg.toLowerCase().includes("invalid")
          ? "This reset link has expired or is invalid. Please request a new one."
          : msg
      );
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-100 px-6 py-8 text-center space-y-4">
        <div className="flex items-start gap-2 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-600">
          <span className="shrink-0 mt-0.5">⚠</span>
          Invalid reset link. No token provided.
        </div>
        <Link href="/forgot-password" className="text-sm font-medium text-indigo-600 hover:text-indigo-800 transition-colors">
          Request a new reset link
        </Link>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-100">
      {success ? (
        <div className="px-6 py-8 text-center space-y-4">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-6 w-6 text-green-600">
              <path d="M20 6L9 17l-5-5" />
            </svg>
          </div>
          <p className="text-sm font-medium text-slate-800">Password reset!</p>
          <p className="text-sm text-slate-500">Redirecting to login…</p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4 px-6 py-6">
          {/* New password */}
          <div>
            <label htmlFor="new-password" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              New Password
            </label>
            <div className="relative">
              <input
                id="new-password"
                type={showPw ? "text" : "password"}
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                required
                minLength={8}
                autoFocus
                autoComplete="new-password"
                placeholder="Min 8 characters"
                className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 pr-11 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400"
              />
              <button
                type="button"
                onClick={() => setShowPw(v => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                tabIndex={-1}
                aria-label={showPw ? "Hide password" : "Show password"}
              >
                {showPw ? (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4">
                    <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" />
                    <line x1="1" y1="1" x2="23" y2="23" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                )}
              </button>
            </div>
          </div>

          {/* Confirm password */}
          <div>
            <label htmlFor="confirm-password" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
              Confirm New Password
            </label>
            <input
              id="confirm-password"
              type={showPw ? "text" : "password"}
              value={confirmPw}
              onChange={(e) => setConfirmPw(e.target.value)}
              required
              autoComplete="new-password"
              placeholder="Repeat your new password"
              className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-600">
              <span className="shrink-0 mt-0.5">⚠</span>
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !newPw || !confirmPw}
            className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-md shadow-indigo-200 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
                </svg>
                Resetting…
              </>
            ) : (
              "Reset Password"
            )}
          </button>

          <p className="text-center text-sm">
            <Link href="/login" className="text-slate-500 hover:text-indigo-600 transition-colors">
              Back to login
            </Link>
          </p>
        </form>
      )}
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 via-white to-slate-100 p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 shadow-lg shadow-indigo-200">
            <span className="text-xl font-bold text-white">N</span>
          </div>
          <h1 className="mt-3 text-2xl font-bold text-slate-900">Reset Password</h1>
          <p className="mt-1 text-sm text-slate-500">Choose a new password for your account</p>
        </div>

        <Suspense fallback={
          <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-100 px-6 py-8 flex items-center justify-center">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
          </div>
        }>
          <ResetPasswordForm />
        </Suspense>

        <p className="mt-6 text-center text-xs text-slate-400">
          Nexus · Enterprise AI Platform
        </p>
      </div>
    </div>
  );
}
