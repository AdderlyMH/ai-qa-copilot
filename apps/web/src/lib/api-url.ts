const API_PREFIX = /^\/api(?=\/|$)/;

// With a build-time base URL, call the API directly; the API has no "/api"
// prefix. Without one, keep the path for the development server rewrite.
export function apiUrl(path: string): string {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  return baseUrl ? `${baseUrl}${path.replace(API_PREFIX, "")}` : path;
}
