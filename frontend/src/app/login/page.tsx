"use client";

import { useState, FormEvent, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { storeTokens } from "@/lib/auth";
import type { TokenResponse } from "@/types";

const GOOGLE_ENABLED    = process.env.NEXT_PUBLIC_GOOGLE_SSO_ENABLED    === "true";
const MICROSOFT_ENABLED = process.env.NEXT_PUBLIC_MICROSOFT_SSO_ENABLED === "true";
const LDAP_ENABLED      = process.env.NEXT_PUBLIC_LDAP_ENABLED           === "true";

function LoginPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isWelcome = searchParams.get("welcome") === "1";
  const welcomePlan = searchParams.get("plan") || "";
  const usernameRef = useRef<HTMLInputElement>(null);
  const tfaRef      = useRef<HTMLInputElement>(null);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPw,   setShowPw]   = useState(false);
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  // 2FA step state
  const [tfaStep,    setTfaStep]    = useState(false);
  const [tempToken,  setTempToken]  = useState("");
  const [tfaCode,    setTfaCode]    = useState("");
  const [useBackup,  setUseBackup]  = useState(false);
  const [tfaLoading, setTfaLoading] = useState(false);

  // LDAP login
  const [loginMode,     setLoginMode]     = useState<"password" | "ldap">("password");
  const [ldapUsername,  setLdapUsername]  = useState("");
  const [ldapPassword,  setLdapPassword]  = useState("");
  const [ldapLoading,   setLdapLoading]   = useState(false);

  useEffect(() => { usernameRef.current?.focus(); }, []);
  useEffect(() => { if (tfaStep) tfaRef.current?.focus(); }, [tfaStep]);

  async function handleLogin(e: FormEvent) {
    e.preventDefault();
    if (!username.trim() || !password) return;
    setError(""); setLoading(true);
    try {
      const res = await api.post<TokenResponse & { requires_2fa?: boolean; temp_token?: string }>(
        "/api/v1/auth/login",
        { username_or_email: username, password }
      );
      if (res.requires_2fa && res.temp_token) {
        setTempToken(res.temp_token);
        setTfaStep(true);
      } else {
        storeTokens(res.access_token, res.refresh_token);
        router.push("/");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Login failed";
      setError(msg.includes("401") || msg.toLowerCase().includes("invalid")
        ? "Incorrect username or password"
        : msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleLdapLogin(e: FormEvent) {
    e.preventDefault();
    if (!ldapUsername.trim() || !ldapPassword) return;
    setError(""); setLdapLoading(true);
    try {
      const res = await api.post<TokenResponse>("/api/v1/auth/ldap/login", {
        username: ldapUsername,
        password: ldapPassword,
      });
      storeTokens(res.access_token, res.refresh_token);
      router.push("/");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "LDAP login failed";
      setError(msg.includes("401") || msg.toLowerCase().includes("invalid")
        ? "Invalid LDAP credentials"
        : msg);
    } finally {
      setLdapLoading(false);
    }
  }

  async function handle2FA(e: FormEvent) {
    e.preventDefault();
    if (!tfaCode.trim()) return;
    setError(""); setTfaLoading(true);
    try {
      const tokens = await api.post<TokenResponse>("/api/v1/auth/2fa/complete", {
        temp_token: tempToken,
        code: tfaCode,
      });
      storeTokens(tokens.access_token, tokens.refresh_token);
      router.push("/");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Verification failed";
      setError(msg.toLowerCase().includes("invalid") ? "Invalid code. Please try again." : msg);
    } finally {
      setTfaLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 via-white to-slate-100 p-4">
      <div className="w-full max-w-sm">
        {/* Welcome banner after checkout */}
        {isWelcome && (
          <div className="mb-5 rounded-xl bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-emerald-700">
            <p className="font-semibold mb-0.5">
              🎉 {welcomePlan ? `${welcomePlan.charAt(0).toUpperCase() + welcomePlan.slice(1)} plan` : "Account"} activated!
            </p>
            <p className="text-xs text-emerald-600">
              Check your email to verify your address, then sign in below.
            </p>
          </div>
        )}

        {/* Logo */}
        <div className="mb-8 flex flex-col items-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-indigo-600 shadow-lg shadow-indigo-200">
            <span className="text-xl font-bold text-white">N</span>
          </div>
          <h1 className="mt-3 text-2xl font-bold text-slate-900">Welcome to Nexus</h1>
          <p className="mt-1 text-sm text-slate-500">Enterprise AI — built for your team</p>
        </div>

        <div className="rounded-2xl bg-white shadow-xl ring-1 ring-slate-100">

          {/* ── 2FA Step ── */}
          {tfaStep ? (
            <form onSubmit={handle2FA} className="space-y-4 px-6 py-6">
              <div className="text-center mb-2">
                <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-indigo-50">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="h-5 w-5 text-indigo-600">
                    <rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0110 0v4" />
                  </svg>
                </div>
                <p className="text-sm font-semibold text-slate-800">Two-factor authentication</p>
                <p className="mt-1 text-xs text-slate-500">
                  {useBackup
                    ? "Enter one of your backup codes"
                    : "Enter the 6-digit code from your authenticator app"}
                </p>
              </div>

              <div>
                <label htmlFor="tfa-code" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                  {useBackup ? "Backup Code" : "Authenticator Code"}
                </label>
                <input
                  id="tfa-code"
                  ref={tfaRef}
                  type="text"
                  inputMode="numeric"
                  value={tfaCode}
                  onChange={(e) => setTfaCode(e.target.value.replace(/\s/g, ""))}
                  required
                  autoComplete="one-time-code"
                  placeholder={useBackup ? "xxxxxxxx" : "000000"}
                  maxLength={useBackup ? 20 : 6}
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-center text-lg font-mono tracking-widest text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400 placeholder:font-sans placeholder:text-sm placeholder:tracking-normal"
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
                disabled={tfaLoading || !tfaCode.trim()}
                className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-md shadow-indigo-200 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
              >
                {tfaLoading ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
                    </svg>
                    Verifying…
                  </>
                ) : (
                  "Verify"
                )}
              </button>

              <div className="flex items-center justify-between text-xs">
                <button
                  type="button"
                  onClick={() => { setUseBackup(v => !v); setTfaCode(""); }}
                  className="text-indigo-600 hover:text-indigo-800 transition-colors"
                >
                  {useBackup ? "Use authenticator app instead" : "Use a backup code instead"}
                </button>
                <button
                  type="button"
                  onClick={() => { setTfaStep(false); setTfaCode(""); setError(""); }}
                  className="text-slate-400 hover:text-slate-600 transition-colors"
                >
                  Go back
                </button>
              </div>
            </form>
          ) : (
            <>
              {/* ── SSO Buttons ── */}
              {(GOOGLE_ENABLED || MICROSOFT_ENABLED) && (
                <div className="px-6 pt-6 pb-0 space-y-2.5">
                  {GOOGLE_ENABLED && (
                    <button
                      type="button"
                      onClick={() => { window.location.href = "/api/auth/oauth/google"; }}
                      className="w-full flex items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
                    >
                      <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
                        <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
                        <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
                        <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
                        <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
                      </svg>
                      Continue with Google
                    </button>
                  )}
                  {MICROSOFT_ENABLED && (
                    <button
                      type="button"
                      onClick={() => { window.location.href = "/api/auth/oauth/microsoft"; }}
                      className="w-full flex items-center justify-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors shadow-sm"
                    >
                      <svg width="18" height="18" viewBox="0 0 21 21" aria-hidden="true">
                        <rect x="1"  y="1"  width="9" height="9" fill="#F25022"/>
                        <rect x="11" y="1"  width="9" height="9" fill="#7FBA00"/>
                        <rect x="1"  y="11" width="9" height="9" fill="#00A4EF"/>
                        <rect x="11" y="11" width="9" height="9" fill="#FFB900"/>
                      </svg>
                      Continue with Microsoft
                    </button>
                  )}

                  <div className="flex items-center gap-3 py-1">
                    <div className="flex-1 h-px bg-slate-100" />
                    <span className="text-xs text-slate-400">or sign in with password</span>
                    <div className="flex-1 h-px bg-slate-100" />
                  </div>
                </div>
              )}

              {/* ── Login mode tabs (shown when LDAP is enabled) ── */}
              {LDAP_ENABLED && (
                <div className="flex gap-0.5 rounded-lg border border-slate-200 bg-slate-100 p-0.5 mx-6 mt-4">
                  {(["password", "ldap"] as const).map(mode => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => { setLoginMode(mode); setError(""); }}
                      className={`flex-1 py-1.5 rounded-md text-xs font-medium transition-colors ${
                        loginMode === mode
                          ? "bg-white text-slate-800 shadow-sm"
                          : "text-slate-500 hover:text-slate-700"
                      }`}
                    >
                      {mode === "password" ? "Password" : "LDAP / AD"}
                    </button>
                  ))}
                </div>
              )}

              {/* ── LDAP Form ── */}
              {LDAP_ENABLED && loginMode === "ldap" ? (
                <form onSubmit={handleLdapLogin} className="space-y-4 px-6 py-6">
                  <div>
                    <label htmlFor="ldap-username" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                      AD Username
                    </label>
                    <input
                      id="ldap-username"
                      type="text"
                      value={ldapUsername}
                      onChange={(e) => setLdapUsername(e.target.value)}
                      required
                      autoComplete="username"
                      spellCheck={false}
                      placeholder="DOMAIN\\username or sAMAccountName"
                      className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400"
                    />
                  </div>
                  <div>
                    <label htmlFor="ldap-password" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                      Password
                    </label>
                    <input
                      id="ldap-password"
                      type="password"
                      value={ldapPassword}
                      onChange={(e) => setLdapPassword(e.target.value)}
                      required
                      autoComplete="current-password"
                      placeholder="••••••••"
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
                    disabled={ldapLoading || !ldapUsername.trim() || !ldapPassword}
                    className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-md shadow-indigo-200 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
                  >
                    {ldapLoading ? (
                      <>
                        <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
                        </svg>
                        Signing in…
                      </>
                    ) : (
                      "Sign in with LDAP"
                    )}
                  </button>
                </form>
              ) : (
              <>
              {/* ── Sign-in Form ── */}
              <form onSubmit={handleLogin} className="space-y-4 px-6 py-6">
                <div>
                  <label htmlFor="username" className="mb-1.5 block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                    Username or Email
                  </label>
                  <input
                    id="username"
                    ref={usernameRef}
                    type="text"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    required
                    autoComplete="username"
                    spellCheck={false}
                    placeholder="your@email.com or username"
                    className="w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-2.5 text-sm text-slate-800 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100 placeholder:text-slate-400"
                  />
                </div>

                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <label htmlFor="password" className="block text-xs font-semibold text-slate-600 uppercase tracking-wide">
                      Password
                    </label>
                    <Link
                      href="/forgot-password"
                      className="text-xs text-indigo-600 hover:text-indigo-800 transition-colors"
                      tabIndex={-1}
                    >
                      Forgot password?
                    </Link>
                  </div>
                  <div className="relative">
                    <input
                      id="password"
                      type={showPw ? "text" : "password"}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      autoComplete="current-password"
                      placeholder="••••••••"
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

                {error && (
                  <div className="flex items-start gap-2 rounded-xl bg-red-50 px-3 py-2.5 text-sm text-red-600">
                    <span className="shrink-0 mt-0.5">⚠</span>
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading || !username.trim() || !password}
                  className="w-full rounded-xl bg-indigo-600 py-2.5 text-sm font-semibold text-white shadow-md shadow-indigo-200 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
                >
                  {loading ? (
                    <>
                      <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3v4a8 8 0 00-8 8h4z" />
                      </svg>
                      Signing in…
                    </>
                  ) : (
                    "Sign in"
                  )}
                </button>
              </form>
              </>
              )}
            </>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          Nexus · Enterprise AI Platform
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-indigo-50 via-white to-slate-100">
        <div className="w-6 h-6 border-2 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
      </div>
    }>
      <LoginPageInner />
    </Suspense>
  );
}
