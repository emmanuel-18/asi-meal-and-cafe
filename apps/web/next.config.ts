import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const origin = new URL(process.env.ASI_API_ORIGIN ?? "http://127.0.0.1:8000");
    if (!['http:', 'https:'].includes(origin.protocol) || origin.username || origin.password ||
        origin.search || origin.hash || origin.pathname !== '/') {
      throw new Error("ASI_API_ORIGIN must be an HTTP(S) origin without credentials or a path");
    }
    return ["auth", "api"].map((prefix) => ({
      source: `/${prefix}/:path*`,
      destination: `${origin.origin}/${prefix}/:path*`,
    }));
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
