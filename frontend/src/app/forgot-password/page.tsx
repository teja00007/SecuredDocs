"use client";

import { useState, FormEvent } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email,     setEmail]     = useState("");
  const [loading,   setLoading]   = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error,     setError]     = useState("");

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setError(""); setLoading(true);
    try {
      await api.post("/api/v1/auth/forgot-password", { email });
      setSubmitted(true);
    } catch (err: unknown) {
      // Only show a generic error for actual server/network failures
      // never reveal whether the email exists
      const msg = err instanceof Error ? err.message : "Something went wrong";
      if (msg.includes("connect") || msg.includes("Network") || msg.includes("0")) {
        setError("Cannot connect to server. Please try again.");
      } else {
        // Treat any other error as a silent success to avoid email enumeration
        setSubmitted(true);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 via-white to-slate-100 p-4">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="mb-8 flex flex-col items-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 shadow-lg shadow-indigo-200">
            <span className="text-xl font-bold text-white">N</span>
          </div>
          <h1 className="mt-3 text-2xl font-bold text-slate-900">Forgot Password</h1>
          <p className="mt-1 text-sm text-slate-500">Enter your email to receive a reset link</p>
        </div>

        <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-100">
          {submitted ? (
            <div className="px-6 py-8 text-center space-y-4">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-6 w-6 text-green-600">
                  <path d="M20 6L9 17l-5-5" />
                </svg>
              </div>
              <p className="text-sm font-medium text-slate-800">Check your inbox</p>
              <p className="text-sm text-slate-500">
                If that email exists in our system, a reset link has been sent. Check your inbox (and spam folder).
              </p>
              <Link
                href="/login"
                className="mt-2 inline-block text-sm font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
              >
                Back to login
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4 px-6 py-6">
              <div>
                <label htmlFor="email" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  Email address
                </label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  autoComplete="email"
                  placeholder="you@company.com"
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
                disabled={loading || !email.trim()}
                className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-md shadow-indigo-200 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
                    </svg>
                    Sending…
                  </>
                ) : (
                  "Send Reset Link"
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

        <p className="mt-6 text-center text-xs text-slate-400">
          Nexus · Enterprise AI Platform
        </p>
      </div>
    </div>
  );
}
