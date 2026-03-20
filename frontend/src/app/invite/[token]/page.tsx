"use client";

import { useState, useEffect, FormEvent } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { storeTokens } from "@/lib/auth";
import type { TokenResponse } from "@/types";

interface InviteValidation {
  email: string;
  invited_by?: string;
  expires_at?: string;
}

export default function InviteAcceptPage() {
  const router = useRouter();
  const params = useParams();
  const token  = typeof params.token === "string" ? params.token : Array.isArray(params.token) ? params.token[0] : "";

  const [validating,   setValidating]   = useState(true);
  const [inviteData,   setInviteData]   = useState<InviteValidation | null>(null);
  const [inviteError,  setInviteError]  = useState("");

  const [username,    setUsername]    = useState("");
  const [password,    setPassword]    = useState("");
  const [confirmPw,   setConfirmPw]   = useState("");
  const [showPw,      setShowPw]      = useState(false);
  const [submitting,  setSubmitting]  = useState(false);
  const [formError,   setFormError]   = useState("");

  useEffect(() => {
    if (!token) {
      setInviteError("Invalid invite link.");
      setValidating(false);
      return;
    }
    api.get<InviteValidation>(`/api/v1/invites/validate/${token}`)
      .then(data => {
        setInviteData(data);
        setValidating(false);
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : "Invalid invite";
        setInviteError(
          msg.toLowerCase().includes("expired") ? "This invite link has expired." : "This invite link is invalid or has already been used."
        );
        setValidating(false);
      });
  }, [token]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError("");
    if (!username.trim()) { setFormError("Username is required"); return; }
    if (username.length < 3) { setFormError("Username must be at least 3 characters"); return; }
    if (password.length < 8) { setFormError("Password must be at least 8 characters"); return; }
    if (password !== confirmPw) { setFormError("Passwords do not match"); return; }

    setSubmitting(true);
    try {
      await api.post("/api/v1/auth/register", {
        username,
        email: inviteData!.email,
        password,
        invite_token: token,
      });
      // Auto-login after registration
      const tokens = await api.post<TokenResponse>("/api/v1/auth/login", {
        username_or_email: username,
        password,
      });
      storeTokens(tokens.access_token, tokens.refresh_token);
      router.push("/");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      setFormError(
        msg.includes("already") ? "Username is already taken. Please choose another." : msg
      );
    } finally {
      setSubmitting(false);
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
          <h1 className="mt-3 text-2xl font-bold text-slate-900">Join Nexus</h1>
          <p className="mt-1 text-sm text-slate-500">You&apos;ve been invited to join the team</p>
        </div>

        <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-100">
          {validating ? (
            <div className="flex items-center justify-center px-6 py-10">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-600 border-t-transparent" />
            </div>
          ) : inviteError ? (
            <div className="px-6 py-8 text-center space-y-4">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-6 w-6 text-red-500">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M15 9l-6 6M9 9l6 6" />
                </svg>
              </div>
              <p className="text-sm font-semibold text-slate-800">{inviteError}</p>
              <p className="text-sm text-slate-500">Please contact your administrator for a new invite link.</p>
              <Link
                href="/login"
                className="inline-block text-sm font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
              >
                Back to login
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4 px-6 py-6">
              {/* Invite details */}
              <div className="rounded-xl bg-indigo-50 border border-indigo-100 px-3 py-2.5">
                <p className="text-xs text-indigo-600 font-medium">Invited email</p>
                <p className="text-sm font-semibold text-indigo-900 mt-0.5">{inviteData?.email}</p>
              </div>

              {/* Username */}
              <div>
                <label htmlFor="username" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  Username
                </label>
                <input
                  id="username"
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  autoFocus
                  autoComplete="username"
                  spellCheck={false}
                  minLength={3}
                  placeholder="johndoe"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400"
                />
              </div>

              {/* Password */}
              <div>
                <label htmlFor="password" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  Password
                </label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPw ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
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

              {/* Confirm Password */}
              <div>
                <label htmlFor="confirm-password" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  Confirm Password
                </label>
                <input
                  id="confirm-password"
                  type={showPw ? "text" : "password"}
                  value={confirmPw}
                  onChange={(e) => setConfirmPw(e.target.value)}
                  required
                  autoComplete="new-password"
                  placeholder="Repeat your password"
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400"
                />
              </div>

              {/* Error */}
              {formError && (
                <div className="flex items-start gap-2 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-600">
                  <span className="shrink-0 mt-0.5">⚠</span>
                  {formError}
                </div>
              )}

              {/* Submit */}
              <button
                type="submit"
                disabled={submitting || !username.trim() || !password || !confirmPw}
                className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-md shadow-indigo-200 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
              >
                {submitting ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
                    </svg>
                    Creating account…
                  </>
                ) : (
                  "Create Account"
                )}
              </button>

              <p className="text-center text-sm">
                <Link href="/login" className="text-slate-500 hover:text-indigo-600 transition-colors">
                  Already have an account? Sign in
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
