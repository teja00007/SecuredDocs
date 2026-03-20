"use client";

/**
 * ResponseFeedback — thumbs-up / thumbs-down widget for RAG responses.
 *
 * Usage:
 *   <ResponseFeedback
 *     query="What is RAG?"
 *     answer="Retrieval-Augmented Generation..."
 *     modelName="phi4-mini"
 *   />
 *
 * On submit it calls POST /api/v1/training/feedback and shows a confirmation.
 */

import { useState } from "react";

// Inline SVG icon helpers to avoid external icon library dependency
function ThumbsUp({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14z" />
      <path d="M7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3" />
    </svg>
  );
}

function ThumbsDown({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M10 15v4a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10z" />
      <path d="M17 2h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17" />
    </svg>
  );
}

function Check({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function X({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

interface ResponseFeedbackProps {
  query: string;
  answer: string;
  modelName?: string;
  confidenceScore?: number;
  context?: string;
  className?: string;
}

type FeedbackState = "idle" | "correcting" | "submitting" | "done" | "error";
type FeedbackValue = "thumbs_up" | "thumbs_down" | null;

export function ResponseFeedback({
  query,
  answer,
  modelName,
  confidenceScore,
  context,
  className = "",
}: ResponseFeedbackProps) {
  const [feedback, setFeedback] = useState<FeedbackValue>(null);
  const [state, setState] = useState<FeedbackState>("idle");
  const [correction, setCorrection] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  async function submitFeedback(value: FeedbackValue, correctedAnswer?: string) {
    if (!value) return;
    setState("submitting");
    setErrorMsg("");

    try {
      const token = localStorage.getItem("access_token") ?? "";
      const res = await fetch("/api/v1/training/feedback", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          query,
          answer,
          feedback: value,
          model_name: modelName ?? null,
          confidence_score: confidenceScore ?? null,
          context: context ?? null,
          corrected_answer: correctedAnswer ?? null,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      setState("done");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setErrorMsg(`Failed to submit feedback: ${msg}`);
      setState("error");
    }
  }

  function handleThumbsUp() {
    setFeedback("thumbs_up");
    submitFeedback("thumbs_up");
  }

  function handleThumbsDown() {
    setFeedback("thumbs_down");
    setState("correcting");
  }

  function handleCorrectionSubmit() {
    submitFeedback("thumbs_down", correction.trim() || undefined);
    setState("submitting");
  }

  function handleCorrectionSkip() {
    submitFeedback("thumbs_down");
  }

  if (state === "done") {
    return (
      <div className={`flex items-center gap-2 text-sm text-green-600 dark:text-green-400 ${className}`}>
        <Check className="h-4 w-4" />
        <span>Thanks for your feedback!</span>
      </div>
    );
  }

  if (state === "correcting") {
    return (
      <div className={`flex flex-col gap-2 ${className}`}>
        <p className="text-sm text-gray-600 dark:text-gray-400">
          What would a better answer look like? (optional)
        </p>
        <textarea
          value={correction}
          onChange={(e) => setCorrection(e.target.value)}
          placeholder="Type a corrected answer, or skip..."
          rows={3}
          className="w-full rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <div className="flex gap-2">
          <button
            onClick={handleCorrectionSubmit}
            className="px-3 py-1.5 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
          >
            Submit
          </button>
          <button
            onClick={handleCorrectionSkip}
            className="px-3 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 text-sm text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          >
            Skip
          </button>
          <button
            onClick={() => { setFeedback(null); setState("idle"); }}
            className="ml-auto p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 text-gray-400 transition-colors"
            aria-label="Cancel"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-1 ${className}`}>
      <span className="text-xs text-gray-400 mr-1 select-none">Was this helpful?</span>

      <button
        onClick={handleThumbsUp}
        disabled={state === "submitting"}
        aria-label="Thumbs up"
        className={`p-1.5 rounded-md transition-colors ${
          feedback === "thumbs_up"
            ? "bg-green-100 dark:bg-green-900 text-green-600 dark:text-green-400"
            : "text-gray-400 hover:text-green-600 dark:hover:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/30"
        } disabled:opacity-50`}
      >
        <ThumbsUp className="h-4 w-4" />
      </button>

      <button
        onClick={handleThumbsDown}
        disabled={state === "submitting"}
        aria-label="Thumbs down"
        className={`p-1.5 rounded-md transition-colors ${
          feedback === "thumbs_down"
            ? "bg-red-100 dark:bg-red-900 text-red-600 dark:text-red-400"
            : "text-gray-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30"
        } disabled:opacity-50`}
      >
        <ThumbsDown className="h-4 w-4" />
      </button>

      {state === "error" && (
        <span className="text-xs text-red-500 ml-2">{errorMsg}</span>
      )}
    </div>
  );
}

export default ResponseFeedback;
