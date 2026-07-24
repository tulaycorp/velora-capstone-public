const nextCommand = process.env.npm_lifecycle_event;

const securityHeaders = [
  {
    key: "X-Frame-Options",
    value: "DENY"
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload"
  },
  {
    key: "X-Content-Type-Options",
    value: "nosniff"
  }
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Keep `next dev` output isolated so production builds cannot corrupt a live dev server.
  distDir:
    process.env.VELORA_NEXT_DIST_DIR ||
    (nextCommand === "dev" ? ".next-dev" : ".next"),
  // The development toolbar overlaps the fixed auth panel and can look like app UI.
  devIndicators: false,
  // Clerk middleware buffers protected request bodies before route handlers run.
  // Product artwork can exceed Next.js's 10 MB default, so keep the proxy ceiling
  // above the 95 MiB single-file limit to allow multipart boundaries and fields.
  experimental: {
    middlewareClientMaxBodySize: "100mb"
  },
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders
      }
    ];
  }
};

export default nextConfig;
