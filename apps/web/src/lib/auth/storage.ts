const ACCESS_TOKEN_KEY = "auth.accessToken";
const EXPIRES_AT_KEY = "auth.expiresAt";
const VERIFIER_KEY = "auth.pkceVerifier";
const STATE_KEY = "auth.state";

export type StoredToken = { accessToken: string; expiresAt: number };

export function storeAccessToken(accessToken: string, expiresAt: number): void {
  sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  sessionStorage.setItem(EXPIRES_AT_KEY, String(expiresAt));
}

export function readStoredToken(): StoredToken | null {
  const accessToken = sessionStorage.getItem(ACCESS_TOKEN_KEY);
  const expiresAt = Number(sessionStorage.getItem(EXPIRES_AT_KEY));
  if (!accessToken || !Number.isFinite(expiresAt) || expiresAt <= 0) {
    return null;
  }
  return { accessToken, expiresAt };
}

export function storePendingSignIn(verifier: string, state: string): void {
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);
}

// Single use: a pending sign-in is gone as soon as a callback reads it.
export function takePendingSignIn(): {
  verifier: string | null;
  state: string | null;
} {
  const pending = {
    verifier: sessionStorage.getItem(VERIFIER_KEY),
    state: sessionStorage.getItem(STATE_KEY),
  };
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
  return pending;
}

export function clearAuthStorage(): void {
  sessionStorage.removeItem(ACCESS_TOKEN_KEY);
  sessionStorage.removeItem(EXPIRES_AT_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);
}
