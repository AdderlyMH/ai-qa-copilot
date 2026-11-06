import type { NextConfig } from "next";
import {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
} from "next/constants";

// A trailing slash is rejected rather than normalized, so apiUrl() can append
// paths to the exact value the build was given.
function requireExportApiBaseUrl(): void {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!baseUrl || !baseUrl.startsWith("https://") || baseUrl.endsWith("/")) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL must be set for a production build, start with https:// and have no trailing slash.",
    );
  }
}

export default function nextConfig(phase: string): NextConfig {
  if (process.env.PUBLIC_DEMO_MODE === "true") {
    return {
      async redirects() {
        return [
          {
            source: "/",
            destination: "/demo",
            permanent: false,
          },
        ];
      },
    };
  }

  if (phase === PHASE_PRODUCTION_BUILD) {
    requireExportApiBaseUrl();
    return { output: "export" };
  }

  if (phase === PHASE_DEVELOPMENT_SERVER) {
    const apiBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
    return {
      async rewrites() {
        return [
          {
            source: "/api/:path*",
            destination: `${apiBaseUrl}/:path*`,
          },
        ];
      },
    };
  }

  return {};
}
