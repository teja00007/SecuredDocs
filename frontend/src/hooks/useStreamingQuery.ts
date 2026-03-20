"use client";

/**
 * useStreamingQuery — React hook for SSE streaming RAG queries.
 *
 * Connects to the backend SSE endpoint, streams tokens in real-time,
 * and returns the accumulated answer + final metadata.
 *
 * Usage:
 *   const { query, answer, sources, isStreaming, error } = useStreamingQuery();
 *   await query({ text: "What is...", conversationId: "abc" });
 */

import { useState, useCallback, useRef } from "react";

interface Source {
  document_id: string;
  filename: string;
  chunk_text: string;
  page_number?: number;
  score: number;
}

interface StreamingQueryResult {
  answer: string;
  sources: Source[];
  confidence_score: number;
  confidence_label: string;
  follow_up_questions: string[];
}

interface UseStreamingQueryReturn {
  query: (params: { text: string; conversationId: string; token?: string }) => Promise<void>;
  answer: string;
  sources: Source[];
  confidenceScore: number;
  confidenceLabel: string;
  followUpQuestions: string[];
  isStreaming: boolean;
  error: string | null;
  reset: () => void;
}

export function useStreamingQuery(): UseStreamingQueryReturn {
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [confidenceScore, setConfidenceScore] = useState(0);
  const [confidenceLabel, setConfidenceLabel] = useState("");
  const [followUpQuestions, setFollowUpQuestions] = useState<string[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setAnswer("");
    setSources([]);
    setConfidenceScore(0);
    setConfidenceLabel("");
    setFollowUpQuestions([]);
    setIsStreaming(false);
    setError(null);
  }, []);

  const query = useCallback(
    async ({
      text,
      conversationId,
      token,
    }: {
      text: string;
      conversationId: string;
      token?: string;
    }) => {
      abortRef.current?.abort();
      const abort = new AbortController();
      abortRef.current = abort;

      reset();
      setIsStreaming(true);

      const authToken =
        token ?? (typeof window !== "undefined"
          ? localStorage.getItem("access_token") ?? ""
          : "");

      try {
        const res = await fetch(
          `/api/v1/conversations/${conversationId}/stream`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
            },
            body: JSON.stringify({ query: text }),
            signal: abort.signal,
          }
        );

        if (!res.ok) {
          const detail = await res.text();
          throw new Error(`Query failed (${res.status}): ${detail}`);
        }

        if (!res.body) throw new Error("No response body");

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const data = line.slice(6).trim();
            if (!data || data === "[DONE]") continue;

            try {
              const parsed = JSON.parse(data);

              if (parsed.type === "done") {
                setSources(parsed.sources ?? []);
                setConfidenceScore(parsed.confidence_score ?? 0);
                setConfidenceLabel(parsed.confidence_label ?? "");
                setFollowUpQuestions(parsed.follow_up_questions ?? []);
              } else if (typeof parsed === "string") {
                setAnswer((prev) => prev + parsed);
              } else if (parsed.token) {
                setAnswer((prev) => prev + parsed.token);
              }
            } catch {
              // Raw text token (non-JSON SSE line)
              setAnswer((prev) => prev + data);
            }
          }
        }
      } catch (err: any) {
        if (err?.name !== "AbortError") {
          setError(err?.message ?? "Streaming query failed");
        }
      } finally {
        setIsStreaming(false);
      }
    },
    [reset]
  );

  return {
    query,
    answer,
    sources,
    confidenceScore,
    confidenceLabel,
    followUpQuestions,
    isStreaming,
    error,
    reset,
  };
}
