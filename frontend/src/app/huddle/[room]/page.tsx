"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import { LiveKitRoom, VideoConference } from "@livekit/components-react";
import "@livekit/components-styles";
import { isAuthenticated } from "@/lib/auth";
import { api } from "@/lib/api";

interface IceServer { urls: string; username?: string; credential?: string }
interface JoinToken {
  room_name: string; token: string; ws_url: string;
  ice_servers: IceServer[];
  ice_transport_policy: "all" | "relay";
}
interface Me        { username: string }

function friendlyName(roomName: string) {
  if (roomName.startsWith("huddle-")) return "Instant Huddle";
  if (roomName.startsWith("call-"))   return "Video Call";
  if (roomName.startsWith("meet-"))   return roomName.replace(/^meet-/, "").replace(/-/g, " ");
  return roomName.replace(/-/g, " ");
}

// If the page is accessed via a LAN IP but ws_url still says localhost,
// swap in the page's hostname so the browser reaches the right LiveKit server.
function resolveWsUrl(wsUrl: string): string {
  if (typeof window === "undefined") return wsUrl;
  const pageHost = window.location.hostname;
  if (pageHost !== "localhost" && pageHost !== "127.0.0.1") {
    return wsUrl.replace(/localhost|127\.0\.0\.1/, pageHost);
  }
  return wsUrl;
}

// ── Custom pre-join lobby ─────────────────────────────────────────────────────
function Lobby({
  username,
  roomName,
  onJoin,
  onCancel,
  warning,
}: {
  username: string;
  roomName: string;
  onJoin: () => void;
  onCancel: () => void;
  warning?: string;
}) {
  const videoRef  = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [videoOn, setVideoOn] = useState(true);
  const [audioOn, setAudioOn] = useState(true);
  const [copied,  setCopied]  = useState(false);

  useEffect(() => {
    navigator.mediaDevices
      .getUserMedia({ video: true, audio: false })
      .then(stream => {
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
      })
      .catch(() => setVideoOn(false));
    return () => { streamRef.current?.getTracks().forEach(t => t.stop()); };
  }, []);

  function toggleVideo() {
    const next = !videoOn;
    setVideoOn(next);
    streamRef.current?.getVideoTracks().forEach(t => { t.enabled = next; });
  }

  function copyLink() {
    navigator.clipboard.writeText(window.location.href).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  function join() {
    // Stop preview — LiveKit will re-acquire devices.
    // Brief delay lets the browser fully release camera hardware
    // before LiveKit tries to claim it (avoids black/frozen frames).
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    setTimeout(() => onJoin(), 250);
  }

  const initials = username.split(".").map(p => p[0]?.toUpperCase() ?? "").join("").slice(0, 2) || username[0]?.toUpperCase() || "?";

  return (
    <div className="flex h-screen flex-col bg-slate-900">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-slate-700/50 px-6 py-3 shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white select-none">N</div>
          <span className="text-sm font-semibold text-white">Nexus Meet</span>
        </div>
        <button onClick={onCancel} className="text-sm text-slate-400 hover:text-white transition-colors">✕ Cancel</button>
      </div>

      {/* Body */}
      <div className="flex flex-1 items-center justify-center p-6 overflow-y-auto">
        <div className="w-full max-w-md space-y-5">

          {/* Room title */}
          <div className="text-center">
            <p className="text-xs text-slate-500 uppercase tracking-wider">You're joining</p>
            <h1 className="text-2xl font-bold text-white mt-1 capitalize">{friendlyName(roomName)}</h1>
            <div className="flex items-center justify-center gap-2 mt-1.5">
              <code className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded font-mono">{roomName}</code>
              <button onClick={copyLink} className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
                {copied ? "✓ Copied" : "Copy link"}
              </button>
            </div>
          </div>

          {/* Camera preview */}
          <div className="relative aspect-video w-full rounded-2xl overflow-hidden bg-slate-800 border border-slate-700">
            {videoOn ? (
              <video
                ref={videoRef}
                autoPlay
                muted
                playsInline
                className="absolute inset-0 w-full h-full object-cover"
                style={{ transform: "scaleX(-1)" }}
              />
            ) : (
              <div className="flex h-full items-center justify-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-slate-700 text-2xl font-bold text-white select-none">
                  {initials}
                </div>
              </div>
            )}
            {/* Name tag */}
            <div className="absolute bottom-3 left-3 rounded-lg bg-black/50 px-2.5 py-1 text-xs font-medium text-white backdrop-blur-sm">
              {username}
            </div>
          </div>

          {/* Mic / Camera toggles */}
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={() => setAudioOn(v => !v)}
              title={audioOn ? "Mute microphone" : "Unmute microphone"}
              className={`flex h-11 w-11 items-center justify-center rounded-full border transition-colors ${
                audioOn
                  ? "border-slate-600 bg-slate-800 text-white hover:bg-slate-700"
                  : "border-red-500/60 bg-red-500/20 text-red-400 hover:bg-red-500/30"
              }`}
            >
              {audioOn ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5">
                  <path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3zM19 10v2a7 7 0 01-14 0v-2M12 19v4M8 23h8" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5">
                  <line x1="1" y1="1" x2="23" y2="23" />
                  <path d="M9 9v3a3 3 0 005.12 2.12M15 9.34V4a3 3 0 00-5.94-.6M17 16.95A7 7 0 015 12v-2M19 10v2a7 7 0 01-.11 1.23M12 19v4M8 23h8" />
                </svg>
              )}
            </button>

            <button
              onClick={toggleVideo}
              title={videoOn ? "Turn off camera" : "Turn on camera"}
              className={`flex h-11 w-11 items-center justify-center rounded-full border transition-colors ${
                videoOn
                  ? "border-slate-600 bg-slate-800 text-white hover:bg-slate-700"
                  : "border-red-500/60 bg-red-500/20 text-red-400 hover:bg-red-500/30"
              }`}
            >
              {videoOn ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5">
                  <polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" className="w-5 h-5">
                  <path d="M16 16v1a2 2 0 01-2 2H3a2 2 0 01-2-2V7a2 2 0 012-2h2M20 12l3-5v10l-3-5zM7 7h.01" />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
              )}
            </button>
          </div>

          {/* Disconnect warning (shown when bounced back from a failed connection) */}
          {warning && (
            <div className="flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-sm text-amber-300">
              <span className="shrink-0">⚠</span>
              <span>{warning}</span>
            </div>
          )}

          {/* Join button */}
          <button
            onClick={join}
            className="w-full rounded-xl bg-indigo-600 py-3.5 text-base font-semibold text-white hover:bg-indigo-700 active:bg-indigo-800 transition-colors shadow-lg shadow-indigo-900/30"
          >
            {warning ? "Rejoin" : "Join now"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function HuddlePage() {
  const router   = useRouter();
  const params   = useParams();
  const roomName = params.room as string;

  const [joinToken, setJoinToken] = useState<JoinToken | null>(null);
  const [username,  setUsername]  = useState<string | null>(null);
  const [error,     setError]     = useState("");
  const [joined,    setJoined]    = useState(false);
  const [copied,    setCopied]    = useState(false);
  const [roomError, setRoomError] = useState("");

  // Track intentional leave so onDisconnected doesn't fight with router.back()
  const leavingRef = useRef(false);

  function load() {
    if (!isAuthenticated()) { router.replace("/login"); return; }
    Promise.all([
      api.get<Me>("/api/v1/auth/me"),
      api.post<JoinToken>(`/api/v1/huddle/rooms/${roomName}/join`, {}),
    ]).then(([me, tok]) => {
      setUsername(me.username);
      setJoinToken(tok);
    }).catch(e => setError(e?.message ?? "Could not connect to room"));
  }

  useEffect(() => { load(); }, [roomName]); // eslint-disable-line react-hooks/exhaustive-deps

  function copyLink() {
    navigator.clipboard.writeText(window.location.href).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  // ── States ────────────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-900">
        <div className="text-center space-y-4 px-6 max-w-sm">
          <div className="flex justify-center">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-red-500/20 text-3xl">⚠️</div>
          </div>
          <p className="text-lg font-semibold text-white">{error}</p>
          <p className="text-sm text-slate-400">Make sure the Livekit server is running on port 7880.</p>
          <div className="flex items-center justify-center gap-3">
            <button onClick={() => router.back()} className="text-sm text-slate-400 hover:text-white transition-colors">← Go back</button>
            <button onClick={() => { setError(""); setJoinToken(null); setUsername(null); load(); }} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 transition-colors">Retry</button>
          </div>
        </div>
      </div>
    );
  }

  if (!joinToken || username === null) {
    return (
      <div className="flex h-screen items-center justify-center bg-slate-900">
        <div className="text-center space-y-4">
          <div className="h-10 w-10 animate-spin rounded-full border-4 border-indigo-500 border-t-transparent mx-auto" />
          <p className="text-sm text-slate-400">Connecting…</p>
        </div>
      </div>
    );
  }

  // ── Pre-join lobby ────────────────────────────────────────────────────────
  if (!joined) {
    return (
      <Lobby
        username={username}
        roomName={roomName}
        onJoin={() => {
          setRoomError(""); leavingRef.current = false; setJoined(true);
          // Notify backend that caller is joining — triggers pending call notifications
          api.post(`/api/v1/huddle/rooms/${roomName}/started`, {}).catch(() => {});
        }}
        onCancel={() => router.back()}
        warning={roomError || undefined}
      />
    );
  }

  // ── Live room ─────────────────────────────────────────────────────────────
  return (
    <div className="flex h-screen flex-col bg-slate-900">
      <div className="flex items-center gap-3 border-b border-slate-700/50 px-5 py-2.5 shrink-0">
        <button onClick={() => { leavingRef.current = true; router.back(); }} className="rounded-lg px-3 py-1.5 text-sm text-slate-400 hover:bg-slate-800 hover:text-white transition-colors">
          ← Leave
        </button>
        <div className="h-4 w-px bg-slate-700" />
        <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse shrink-0" />
        <span className="text-sm font-medium text-white truncate capitalize flex-1">{friendlyName(roomName)}</span>
        <button onClick={copyLink} className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-slate-400 hover:bg-slate-800 hover:text-white transition-colors shrink-0">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="w-3.5 h-3.5">
            <rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
          {copied ? "Copied!" : "Share link"}
        </button>
      </div>

      {roomError && (
        <div className="shrink-0 flex items-center gap-3 border-b border-red-900/50 bg-red-950/60 px-5 py-2.5">
          <span className="text-xs text-red-300 flex-1">
            ⚠ Connection error: {roomError} — Is the LiveKit server running? (<code className="font-mono">livekit-server --config livekit.yaml</code>)
          </span>
          <button onClick={() => setRoomError("")} className="text-red-400 hover:text-red-200 text-xs shrink-0">✕</button>
        </div>
      )}
      <div className="flex-1 overflow-hidden" data-lk-theme="default">
        <LiveKitRoom
          video
          audio
          token={joinToken.token}
          serverUrl={resolveWsUrl(joinToken.ws_url)}
          connect
          style={{ height: "100%" }}
          connectOptions={joinToken.ice_servers.length ? {
            rtcConfig: {
              iceServers: joinToken.ice_servers,
              iceTransportPolicy: joinToken.ice_transport_policy,
            },
          } : undefined}
          onDisconnected={() => {
            // Intentional leave (user clicked Leave) — already navigating away
            if (leavingRef.current) return;
            // Unexpected disconnect (ICE failure, server restart, network drop, etc.)
            // Return to lobby so user can retry instead of crashing out of the page
            setJoined(false);
            setRoomError("Connection lost — click Join now to reconnect");
          }}
          onError={(e) => setRoomError(e.message)}
        >
          <VideoConference />
        </LiveKitRoom>
      </div>
    </div>
  );
}
