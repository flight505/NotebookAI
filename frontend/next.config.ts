import type { NextConfig } from "next";

const isTauriBuild = process.env.TAURI_BUILD === "true";

// Tauri ships the static export from frontend/out; everything else uses the
// default Next.js dev/serve flow. The previous `output: "standalone"` branch
// was never consumed (no `node .next/standalone/server.js` invocation
// anywhere in the repo), so leave it unset to keep the build graph minimal.
const nextConfig: NextConfig = {
  ...(isTauriBuild
    ? { output: "export", images: { unoptimized: true } }
    : {}),
  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
