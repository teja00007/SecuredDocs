"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";

interface Props {
  content: string;
  /** Invert colors for user messages (blue bg) */
  inverted?: boolean;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }
  return (
    <button
      onClick={copy}
      className="absolute right-2 top-2 rounded px-2 py-0.5 text-[10px] font-medium transition-colors"
      style={{ background: "rgba(255,255,255,0.1)", color: copied ? "#86efac" : "#a1a1aa" }}
    >
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

export default function MarkdownMessage({ content, inverted = false }: Props) {
  const prose = inverted
    ? "text-white"
    : "text-slate-800";

  const components: Components = {
    // Headings
    h1: ({ children }) => <h1 className="mb-2 mt-3 text-base font-bold">{children}</h1>,
    h2: ({ children }) => <h2 className="mb-1.5 mt-3 text-sm font-bold">{children}</h2>,
    h3: ({ children }) => <h3 className="mb-1 mt-2 text-sm font-semibold">{children}</h3>,

    // Paragraph
    p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,

    // Bold / italic
    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,

    // Inline code
    code: ({ children, className }) => {
      const isBlock = className?.startsWith("language-");
      if (isBlock) return <>{children}</>;
      return (
        <code className={`rounded px-1 py-0.5 font-mono text-[0.8em] ${
          inverted
            ? "bg-white/20 text-white"
            : "bg-slate-100 text-rose-600"
        }`}>
          {children}
        </code>
      );
    },

    // Code block
    pre: ({ children }) => {
      // Extract text from children for copy button
      const codeEl = (children as React.ReactElement)?.props;
      const codeText: string = typeof codeEl?.children === "string" ? codeEl.children : "";
      const lang = (codeEl?.className as string | undefined)?.replace("language-", "") ?? "";
      return (
        <div className="relative my-3 overflow-hidden rounded-xl">
          {lang && (
            <div className="flex items-center justify-between bg-[#1e1e2e] px-4 py-1.5">
              <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wide">{lang}</span>
            </div>
          )}
          <div className="relative">
            <CopyButton text={codeText} />
            <pre className="overflow-x-auto bg-[#1e1e2e] px-4 py-3 text-[0.8em] leading-relaxed text-slate-200 font-mono whitespace-pre">
              {children}
            </pre>
          </div>
        </div>
      );
    },

    // Lists
    ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-0.5">{children}</ul>,
    ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-0.5">{children}</ol>,
    li: ({ children }) => <li className="leading-relaxed">{children}</li>,

    // Blockquote
    blockquote: ({ children }) => (
      <blockquote className={`my-2 border-l-4 pl-3 italic ${
        inverted ? "border-white/40 text-white/80" : "border-slate-300 text-slate-500"
      }`}>
        {children}
      </blockquote>
    ),

    // Horizontal rule
    hr: () => <hr className={`my-3 ${inverted ? "border-white/20" : "border-slate-200"}`} />,

    // Links
    a: ({ href, children }) => (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={`underline underline-offset-2 ${
          inverted ? "text-white hover:text-white/80" : "text-blue-600 hover:text-blue-800"
        }`}
      >
        {children}
      </a>
    ),

    // Table
    table: ({ children }) => (
      <div className="my-2 overflow-x-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="bg-slate-50">{children}</thead>,
    th: ({ children }) => <th className="border-b border-slate-200 px-3 py-2 text-left text-xs font-semibold text-slate-600">{children}</th>,
    td: ({ children }) => <td className="border-b border-slate-100 px-3 py-2 text-slate-700">{children}</td>,
  };

  return (
    <div className={`text-sm ${prose}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
