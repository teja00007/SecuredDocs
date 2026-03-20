"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getAccessToken } from "@/lib/auth";

interface TranscriptSegment {
  text: string;
  timestamp: number;
}

interface LiveTranscriptionProps {
  /** Called whenever a new transcript segment arrives. */
  onSegment?: (text: string) => void;
  /** Optional CSS class for the container. */
  className?: string;
}

type RecordingState = "idle" | "recording" | "stopping";

const WS_BASE =
  typeof window !== "undefined"
    ? (process.env.NEXT_PUBLIC_API_URL || "").replace(/^http/, "ws") ||
      `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
    : "";

export default function LiveTranscription({ onSegment, className = "" }: LiveTranscriptionProps) {
  const [state, setState] = useState<RecordingState>("idle");
  const [segments, setSegments] = useState<TranscriptSegment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [permissionDenied, setPermissionDenied] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll transcript
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [segments]);

  const stopRecording = useCallback(() => {
    setState("stopping");
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "stop" }));
    }
  }, []);

  const startRecording = useCallback(async () => {
    setError(null);
    setPermissionDenied(false);

    // Request microphone
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch {
      setPermissionDenied(true);
      setError("Microphone access denied. Please allow microphone access and try again.");
      return;
    }
    streamRef.current = stream;

    // Open WebSocket
    const token = getAccessToken();
    if (!token) {
      setError("Not authenticated.");
      stream.getTracks().forEach((t) => t.stop());
      return;
    }

    const ws = new WebSocket(`${WS_BASE}/api/v1/transcription/ws?token=${encodeURIComponent(token)}`);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;

    ws.onopen = () => {
      // Send config
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      ws.send(JSON.stringify({ type: "config", mime_type: mimeType.split(";")[0] }));

      // Start MediaRecorder — 4-second chunks
      const recorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm",
      });
      recorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) {
          ws.send(e.data);
        }
      };

      recorder.onstop = () => {
        // WS stop message already sent in stopRecording()
      };

      recorder.start(4000);
      setState("recording");
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data as string);
        if (msg.type === "segment" && msg.text) {
          const seg: TranscriptSegment = { text: msg.text, timestamp: Date.now() };
          setSegments((prev) => [...prev, seg]);
          onSegment?.(msg.text);
        } else if (msg.type === "done") {
          setState("idle");
          ws.close();
        } else if (msg.type === "error") {
          setError(msg.detail ?? "Transcription error.");
          setState("idle");
        }
      } catch {}
    };

    ws.onerror = () => {
      setError("WebSocket connection failed. Check your network.");
      setState("idle");
    };

    ws.onclose = () => {
      if (state === "recording") setState("idle");
      stream.getTracks().forEach((t) => t.stop());
    };
  }, [onSegment, state]);

  function copyTranscript() {
    const text = segments.map((s) => s.text).join(" ");
    navigator.clipboard.writeText(text);
  }

  function clearTranscript() {
    setSegments([]);
  }

  const fullText = segments.map((s) => s.text).join(" ").trim();

  return (
    <div className={`flex flex-col gap-3 ${className}`}>
      {/* Controls */}
      <div className="flex items-center gap-2">
        {state === "idle" ? (
          <button
            onClick={startRecording}
            disabled={permissionDenied}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-red-600 hover:bg-red-500
                       text-white text-sm font-medium transition-colors disabled:opacity-40"
          >
            <span className="w-2 h-2 rounded-full bg-white" />
            Start Recording
          </button>
        ) : state === "recording" ? (
          <button
            onClick={stopRecording}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-700 hover:bg-slate-600
                       text-white text-sm font-medium transition-colors"
          >
            {/* Pulsing red dot */}
            <span className="relative w-2 h-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-red-500" />
            </span>
            Stop Recording
          </button>
        ) : (
          <button disabled className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-700
                                      text-white text-sm font-medium opacity-50 cursor-default">
            <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            Processing…
          </button>
        )}

        {segments.length > 0 && (
          <>
            <button
              onClick={copyTranscript}
              className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs transition-colors"
            >
              Copy
            </button>
            <button
              onClick={clearTranscript}
              className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-400 text-xs transition-colors"
            >
              Clear
            </button>
          </>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="text-xs text-red-400 bg-red-950 border border-red-800 rounded-lg px-3 py-2">
          {error}
        </div>
      )}

      {/* Transcript */}
      {(segments.length > 0 || state === "recording") && (
        <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 max-h-56 overflow-y-auto text-sm text-slate-200 leading-relaxed">
          {fullText || (
            <span className="text-slate-500 italic">Listening… speak now.</span>
          )}
          {state === "recording" && (
            <span className="inline-flex items-center ml-1">
              <span className="animate-bounce text-indigo-400">▍</span>
            </span>
          )}
          <div ref={bottomRef} />
        </div>
      )}

      {/* Empty state prompt */}
      {state === "idle" && segments.length === 0 && !error && (
        <p className="text-xs text-slate-500">
          Click <strong>Start Recording</strong> to begin live transcription.
          Requires microphone access. Transcription runs every ~5 seconds.
        </p>
      )}
    </div>
  );
}
