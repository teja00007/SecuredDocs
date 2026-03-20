"use client";

import { useState, FormEvent } from "react";
import { api } from "@/lib/api";

interface SQLResult {
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  error: string | null;
  row_count: number;
}

export default function DataPage() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<SQLResult | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setResult(null);
    try {
      const data = await api.post<SQLResult>("/api/v1/query/sql", { question });
      setResult(data);
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? "Request failed.";
      setResult({ sql: null, columns: [], rows: [], error: msg, row_count: 0 });
    } finally {
      setLoading(false);
    }
  }

  const examples = [
    "How many documents were uploaded this month?",
    "List the top 10 users by number of documents uploaded.",
    "Show all teams and their member counts.",
    "Which collections have more than 5 documents?",
    "List audit log entries from the last 7 days.",
  ];

  return (
    <div className="flex-1 overflow-y-auto bg-slate-950 text-slate-100 p-6">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-white">Data Explorer</h1>
          <p className="text-slate-400 mt-1 text-sm">
            Ask questions in plain English — Nexus generates and runs a read-only SQL query on your data.
          </p>
        </div>

        {/* Query form */}
        <form onSubmit={handleSubmit} className="mb-6">
          <div className="flex gap-3">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="e.g. How many documents does each team have?"
              className="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-4 py-3 text-sm text-white
                         placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="px-6 py-3 rounded-xl bg-indigo-600 text-white font-medium text-sm
                         hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? "Running…" : "Run"}
            </button>
          </div>
        </form>

        {/* Example questions */}
        {!result && !loading && (
          <div className="mb-8">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-wider mb-3">Example questions</p>
            <div className="flex flex-wrap gap-2">
              {examples.map((ex) => (
                <button
                  key={ex}
                  onClick={() => setQuestion(ex)}
                  className="text-xs px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700
                             text-slate-300 hover:bg-slate-700 hover:text-white transition-colors"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center gap-3 text-slate-400 text-sm py-8">
            <svg className="animate-spin w-4 h-4 text-indigo-400" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
            </svg>
            Generating and running SQL…
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-4">
            {/* Generated SQL */}
            {result.sql && (
              <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700">
                  <span className="text-xs font-mono text-slate-400 uppercase tracking-wider">Generated SQL</span>
                  <button
                    onClick={() => navigator.clipboard.writeText(result.sql!)}
                    className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                  >
                    Copy
                  </button>
                </div>
                <pre className="px-4 py-3 text-xs font-mono text-emerald-400 overflow-x-auto whitespace-pre-wrap">
                  {result.sql}
                </pre>
              </div>
            )}

            {/* Error */}
            {result.error && (
              <div className="bg-red-950 border border-red-800 rounded-xl px-4 py-3 text-sm text-red-300">
                <span className="font-semibold">Error: </span>{result.error}
              </div>
            )}

            {/* Table results */}
            {result.columns.length > 0 && (
              <div className="bg-slate-900 border border-slate-700 rounded-xl overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700">
                  <span className="text-xs text-slate-400">
                    {result.row_count} row{result.row_count !== 1 ? "s" : ""}
                    {result.row_count >= 500 ? " (capped at 500)" : ""}
                  </span>
                  <button
                    onClick={() => {
                      const csv = [result.columns.join(","), ...result.rows.map((r) => r.map(String).join(","))].join("\n");
                      const blob = new Blob([csv], { type: "text/csv" });
                      const a = document.createElement("a");
                      a.href = URL.createObjectURL(blob);
                      a.download = "nexus_query.csv";
                      a.click();
                    }}
                    className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
                  >
                    Export CSV
                  </button>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-slate-800">
                        {result.columns.map((col) => (
                          <th
                            key={col}
                            className="px-4 py-2 text-left text-xs font-medium text-slate-400 uppercase tracking-wider whitespace-nowrap"
                          >
                            {col}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800">
                      {result.rows.map((row, ri) => (
                        <tr key={ri} className="hover:bg-slate-800/50 transition-colors">
                          {row.map((cell, ci) => (
                            <td key={ci} className="px-4 py-2.5 text-slate-300 text-xs whitespace-nowrap max-w-xs truncate">
                              {cell == null ? (
                                <span className="text-slate-600 italic">null</span>
                              ) : String(cell)}
                            </td>
                          ))}
                        </tr>
                      ))}
                      {result.rows.length === 0 && !result.error && (
                        <tr>
                          <td
                            colSpan={result.columns.length}
                            className="px-4 py-6 text-center text-slate-500 text-sm"
                          >
                            No rows returned.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Safety notice */}
        <p className="mt-8 text-xs text-slate-600">
          Only SELECT queries are executed. INSERT, UPDATE, DELETE, and DDL statements are blocked.
          Results are capped at 500 rows.
        </p>
      </div>
    </div>
  );
}
