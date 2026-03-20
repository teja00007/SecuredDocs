"use client";

import { useState, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

function VerifyEmailContent() {
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [status, setStatus] = useState<"loading" | "success" | "error" | "no-token">("loading");
  const [error, setError] = useState("");
  const [resendEmail, setResendEmail] = useState("");
  const [resendSent, setResendSent] = useState(false);
  const [resendLoading, setResendLoading] = useState(false);

  useEffect(() => {
    if (!token) {
      setStatus("no-token");
      return;
    }
    api.post("/api/v1/auth/verify-email", { token })
      .then(() => setStatus("success"))
      .catch((err: unknown) => {
        setStatus("error");
        setError(err instanceof Error ? err.message : "Verification failed");
      });
  }, [token]);

  async function handleResend(e: React.FormEvent) {
    e.preventDefault();
    if (!resendEmail.trim()) return;
    setResendLoading(true);
    try {
      await api.post("/api/v1/auth/resend-verification", { email: resendEmail });
      setResendSent(true);
    } catch {
      setResendSent(true); // Show success regardless (backend always returns 200)
    } finally {
      setResendLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 via-white to-slate-100 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 shadow-lg shadow-indigo-200">
            <span className="text-xl font-bold text-white">N</span>
          </div>
          <h1 className="mt-3 text-2xl font-bold text-slate-900">Email Verification</h1>
        </div>

        <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-100 px-6 py-8 text-center">

          {/* Loading */}
          {status === "loading" && (
            <div className="space-y-4">
              <div className="w-12 h-12 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin mx-auto" />
              <p className="text-sm text-slate-500">Verifying your email address...</p>
            </div>
          )}

          {/* Success */}
          {status === "success" && (
            <div className="space-y-4">
              <div className="w-14 h-14 rounded-full bg-emerald-50 border-2 border-emerald-200 flex items-center justify-center mx-auto">
                <svg className="w-7 h-7 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900 mb-1">Email verified!</h2>
                <p className="text-sm text-slate-500">
                  Your email address has been confirmed. You can now use all features.
                </p>
              </div>
              <Link
                href="/login"
                className="block w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 transition-colors"
              >
                Continue to Sign In
              </Link>
            </div>
          )}

          {/* No token */}
          {status === "no-token" && (
            <div className="space-y-5">
              <div className="w-14 h-14 rounded-full bg-amber-50 border-2 border-amber-200 flex items-center justify-center mx-auto">
                <svg className="w-7 h-7 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900 mb-1">Resend verification</h2>
                <p className="text-sm text-slate-500">
                  Enter your email and we&apos;ll send a new verification link.
                </p>
              </div>
              {resendSent ? (
                <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-700">
                  If that email exists and is unverified, a link has been sent. Check your inbox.
                </div>
              ) : (
                <form onSubmit={handleResend} className="space-y-3 text-left">
                  <input
                    type="email"
                    required
                    value={resendEmail}
                    onChange={(e) => setResendEmail(e.target.value)}
                    placeholder="your@email.com"
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400"
                  />
                  <button
                    type="submit"
                    disabled={resendLoading}
                    className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                  >
                    {resendLoading ? "Sending..." : "Send Verification Email"}
                  </button>
                </form>
              )}
            </div>
          )}

          {/* Error */}
          {status === "error" && (
            <div className="space-y-5">
              <div className="w-14 h-14 rounded-full bg-red-50 border-2 border-red-200 flex items-center justify-center mx-auto">
                <svg className="w-7 h-7 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900 mb-1">Link expired or invalid</h2>
                <p className="text-sm text-slate-500">
                  {error || "This verification link has expired. Request a new one below."}
                </p>
              </div>
              {resendSent ? (
                <div className="rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-700">
                  A new verification link has been sent. Check your inbox.
                </div>
              ) : (
                <form onSubmit={handleResend} className="space-y-3 text-left">
                  <input
                    type="email"
                    required
                    value={resendEmail}
                    onChange={(e) => setResendEmail(e.target.value)}
                    placeholder="your@email.com"
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400"
                  />
                  <button
                    type="submit"
                    disabled={resendLoading}
                    className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                  >
                    {resendLoading ? "Sending..." : "Resend Verification Email"}
                  </button>
                </form>
              )}
            </div>
          )}

        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          <Link href="/login" className="hover:text-slate-600 transition-colors">
            ← Back to sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 via-white to-slate-100">
        <div className="w-6 h-6 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
      </div>
    }>
      <VerifyEmailContent />
    </Suspense>
  );
}
