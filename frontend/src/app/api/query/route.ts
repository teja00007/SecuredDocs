/**
 * Next.js API Route Proxy — /api/query
 *
 * Proxies POST requests to the FastAPI backend /api/v1/query endpoint and
 * streams the SSE response back to the browser.  Having this as a Next.js
 * route handler avoids CORS issues when the frontend and backend run on
 * different ports, and ensures the Authorization header is forwarded correctly.
 *
 * Usage (from the browser):
 *   const res = await fetch("/api/query", {
 *     method: "POST",
 *     headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
 *     body: JSON.stringify({ query: "...", collection_id: "..." }),
 *   });
 *   // consume SSE stream or JSON response
 */

import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
// Allow long-running LLM generation — client disconnects cleanly via AbortController.
export const maxDuration = 300;

const BACKEND =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.text();

  const forwardHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const auth = req.headers.get("authorization");
  if (auth) forwardHeaders["Authorization"] = auth;

  // Abort upstream fetch when the client disconnects early
  const abort = new AbortController();
  req.signal.addEventListener("abort", () => abort.abort());

  let backendRes: Response;
  try {
    backendRes = await fetch(`${BACKEND}/api/v1/query`, {
      method: "POST",
      headers: forwardHeaders,
      body,
      signal: abort.signal,
      // @ts-ignore — Node.js fetch supports duplex for streaming request bodies
      duplex: "half",
    });
  } catch (err: any) {
    if (err?.name === "AbortError") {
      return new Response(null, { status: 499 }); // client disconnected
    }
    return new Response(JSON.stringify({ detail: String(err) }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!backendRes.ok || !backendRes.body) {
    return new Response(await backendRes.text(), {
      status: backendRes.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  const contentType = backendRes.headers.get("content-type") || "";

  // Stream SSE directly to the browser
  if (contentType.includes("text/event-stream")) {
    return new Response(backendRes.body, {
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
        "X-Accel-Buffering": "no",
      },
    });
  }

  // Non-streaming JSON response (e.g. when stream=false)
  return new Response(backendRes.body, {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
