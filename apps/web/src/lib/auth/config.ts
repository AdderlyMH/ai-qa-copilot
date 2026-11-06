export type AuthConfig = {
  apiBaseUrl: string;
  cognitoDomain: string;
  clientId: string;
  redirectUri: string;
  logoutUri: string;
};

// Literal property accesses are what Next inlines at build time. next.config.ts
// validates these for the export; anywhere else, a missing value disables auth.
export function authConfig(): AuthConfig | null {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  const cognitoDomain = process.env.NEXT_PUBLIC_COGNITO_DOMAIN;
  const clientId = process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID;
  const redirectUri = process.env.NEXT_PUBLIC_AUTH_REDIRECT_URI;
  const logoutUri = process.env.NEXT_PUBLIC_AUTH_LOGOUT_URI;
  if (
    !apiBaseUrl ||
    !cognitoDomain ||
    !clientId ||
    !redirectUri ||
    !logoutUri
  ) {
    return null;
  }
  return { apiBaseUrl, cognitoDomain, clientId, redirectUri, logoutUri };
}
