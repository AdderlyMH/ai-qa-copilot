import { apiUrl } from "./api-url";
import { currentAccessToken, expireSession } from "./auth/session";

function isConfiguredApi(url: string): boolean {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  return Boolean(baseUrl) && (url === baseUrl || url.startsWith(`${baseUrl}/`));
}

// The only way the app calls the API. There is no retry and no refresh: a 401 on
// an authenticated request ends the session and the sign-in prompt takes over.
export async function apiFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const token = isConfiguredApi(apiUrl(path)) ? currentAccessToken() : null;
  if (!token) {
    return fetch(apiUrl(path), init);
  }
  const headers = new Headers(init?.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(apiUrl(path), { ...init, headers });
  if (response.status === 401) {
    expireSession();
  }
  return response;
}
