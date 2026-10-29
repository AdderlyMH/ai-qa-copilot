import type { NextConfig } from "next";

const apiBaseUrl = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";
const publicDemoMode = process.env.PUBLIC_DEMO_MODE === "true";

const nextConfig: NextConfig = publicDemoMode
  ? {
      async redirects() {
        return [
          {
            source: "/",
            destination: "/demo",
            permanent: false,
          },
        ];
      },
    }
  : {
      async rewrites() {
        return [
          {
            source: "/api/:path*",
            destination: `${apiBaseUrl}/:path*`,
          },
        ];
      },
    };

export default nextConfig;
