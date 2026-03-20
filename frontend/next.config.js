/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    const backend = process.env.BACKEND_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    // afterFiles: App Router route handlers (e.g. the SSE stream proxy) are
    // checked FIRST; only unmatched paths fall through to these rewrites.
    return {
      afterFiles: [
        { source: "/api/:path*", destination: `${backend}/api/:path*` },
        { source: "/health",     destination: `${backend}/health` },
        { source: "/ws/:path*",  destination: `${backend}/ws/:path*` },
      ],
    };
  },
};

module.exports = nextConfig;
