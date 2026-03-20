import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
// No timeout cap — LLM generation can be slow; let the client disconnect naturally.
export const maxDuration = 300;

const BACKEND =
  process.env.BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

/**
 * SSE streaming proxy — mounted at /sse/[id] instead of /api/v1/conversations/[id]/stream
 * so that the /api/:path* catch-all rewrite in next.config.js does NOT intercept it.
 * The rewrite proxy does not support long-lived SSE connections (ECONNRESET); this
 * App Router handler uses Node fetch with half-duplex streaming, which does.
 */
export async function POST(
  req: NextRequest,
  { params }: { params: { id: string } },
) {
  const body = await req.text();

  const forwardHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const auth = req.headers.get("authorization");
  if (auth) forwardHeaders["Authorization"] = auth;

  const abort = new AbortController();
  req.signal.addEventListener("abort", () => abort.abort());

  let backendRes: Response;
  try {
    backendRes = await fetch(
      `${BACKEND}/api/v1/conversations/${params.id}/stream`,
      {
        method: "POST",
        headers: forwardHeaders,
        body,
        signal: abort.signal,
        // @ts-ignore — Node.js fetch supports duplex for streaming bodies
        duplex: "half",
      },
    );
  } catch (err: any) {
    if (err?.name === "AbortError") {
      return new Response(null, { status: 499 });
    }
    return new Response(JSON.stringify({ detail: String(err) }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!backendRes.ok || !backendRes.body) {
    return new Response(await backendRes.text(), { status: backendRes.status });
  }

  return new Response(backendRes.body, {
    status: 200,
    headers: {
      "Content-Type":      "text/event-stream",
      "Cache-Control":     "no-cache, no-transform",
      "Connection":        "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
