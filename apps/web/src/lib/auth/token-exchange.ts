import type { AuthConfig } from "./config";

// Only the access token is read from the response; anything else Cognito returns
// is dropped with it. Errors carry no provider text.
export async function exchangeCode(
  config: AuthConfig,
  code: string,
  verifier: string,
): Promise<string> {
  const response = await fetch(`${config.cognitoDomain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "authorization_code",
      client_id: config.clientId,
      code,
      redirect_uri: config.redirectUri,
      code_verifier: verifier,
    }).toString(),
  });
  if (!response.ok) {
    throw new Error("Token exchange failed");
  }
  const body: unknown = await response.json();
  if (
    typeof body !== "object" ||
    body === null ||
    !("access_token" in body) ||
    typeof body.access_token !== "string" ||
    body.access_token === ""
  ) {
    throw new Error("Token exchange failed");
  }
  return body.access_token;
}
