import type { AuthConfig } from "./config";

export function buildAuthorizeUrl(
  config: AuthConfig,
  challenge: string,
  state: string,
): string {
  const query = new URLSearchParams({
    response_type: "code",
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    scope: "openid",
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });
  return `${config.cognitoDomain}/oauth2/authorize?${query.toString()}`;
}

export function buildLogoutUrl(config: AuthConfig): string {
  const query = new URLSearchParams({
    client_id: config.clientId,
    logout_uri: config.logoutUri,
  });
  return `${config.cognitoDomain}/logout?${query.toString()}`;
}
