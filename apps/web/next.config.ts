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

// Terraform's Cognito callback and logout URLs are the site root, exactly.
function isHttpsSiteRoot(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && value === `${url.origin}/`;
  } catch {
    return false;
  }
}

function isHttpsOrigin(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && value === url.origin;
  } catch {
    return false;
  }
}

function requireExportAuthConfig(): void {
  if (!isHttpsOrigin(process.env.NEXT_PUBLIC_COGNITO_DOMAIN ?? "")) {
    throw new Error(
      "NEXT_PUBLIC_COGNITO_DOMAIN must be set for a production build, as the https:// Cognito prefix-domain base URL with no path and no trailing slash.",
    );
  }
  if (!process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID?.trim()) {
    throw new Error(
      "NEXT_PUBLIC_COGNITO_CLIENT_ID must be set for a production build and must not be empty.",
    );
  }
  if (!isHttpsSiteRoot(process.env.NEXT_PUBLIC_AUTH_REDIRECT_URI ?? "")) {
    throw new Error(
      "NEXT_PUBLIC_AUTH_REDIRECT_URI must be set for a production build, as the https:// site root with a trailing slash, matching the Terraform callback URL.",
    );
  }
  if (!isHttpsSiteRoot(process.env.NEXT_PUBLIC_AUTH_LOGOUT_URI ?? "")) {
    throw new Error(
      "NEXT_PUBLIC_AUTH_LOGOUT_URI must be set for a production build, as the https:// site root with a trailing slash, matching the Terraform logout URL.",
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
    requireExportAuthConfig();
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
