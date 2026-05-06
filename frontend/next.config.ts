import type { NextConfig } from "next";

const isTauriBuild = process.env.TAURI_BUILD === "true";

const nextConfig: NextConfig = {
  output: isTauriBuild ? "export" : "standalone",
  images: isTauriBuild ? { unoptimized: true } : undefined,
  experimental: {
    typedRoutes: true,
  },
};

export default nextConfig;
