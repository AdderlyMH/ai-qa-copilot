import { authConfig, type AuthConfig } from "./config";
import { decodeJwtExp } from "./jwt";
import { createVerifier, s256Challenge } from "./pkce";
import { createState, statesMatch } from "./state";
import {
  clearAuthStorage,
  readStoredToken,
  storeAccessToken,
  storePendingSignIn,
  takePendingSignIn,
} from "./storage";
import { exchangeCode } from "./token-exchange";
import { buildAuthorizeUrl, buildLogoutUrl } from "./urls";

export type AuthStatus =
  "disabled" | "pending" | "signed-out" | "signed-in" | "expired" | "error";

let status: AuthStatus = getServerAuthStatus();
let initialized = false;
const listeners = new Set<() => void>();

function setStatus(next: AuthStatus): void {
  status = next;
  listeners.forEach((listener) => listener());
}

function nowInSeconds(): number {
  return Date.now() / 1000;
}

export function subscribeAuth(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAuthStatus(): AuthStatus {
  return status;
}

export function getServerAuthStatus(): AuthStatus {
  return authConfig() ? "pending" : "disabled";
}

async function completeCallback(
  config: AuthConfig,
  params: URLSearchParams,
): Promise<void> {
  const pending = takePendingSignIn();
  const code = params.get("code");
  const state = params.get("state");
  let next: AuthStatus = "error";
  try {
    if (
      !params.has("error") &&
      code &&
      state &&
      pending.verifier &&
      pending.state &&
      statesMatch(pending.state, state)
    ) {
      const accessToken = await exchangeCode(config, code, pending.verifier);
      const expiresAt = decodeJwtExp(accessToken);
      if (expiresAt !== null && expiresAt > nowInSeconds()) {
        storeAccessToken(accessToken, expiresAt);
        next = "signed-in";
      }
    }
  } catch {
    next = "error";
  }
  if (next === "error") {
    clearAuthStorage();
  }
  window.history.replaceState(null, "", window.location.pathname);
  setStatus(next);
}

export async function initializeAuth(): Promise<void> {
  const config = authConfig();
  if (!config || initialized) {
    return;
  }
  initialized = true;
  const params = new URLSearchParams(window.location.search);
  if (params.has("code") || params.has("state") || params.has("error")) {
    await completeCallback(config, params);
    return;
  }
  const stored = readStoredToken();
  if (!stored) {
    setStatus("signed-out");
  } else if (stored.expiresAt <= nowInSeconds()) {
    expireSession();
  } else {
    setStatus("signed-in");
  }
}

export async function startSignIn(): Promise<void> {
  const config = authConfig();
  if (!config) {
    return;
  }
  try {
    const verifier = createVerifier();
    const state = createState();
    const challenge = await s256Challenge(verifier);
    storePendingSignIn(verifier, state);
    window.location.assign(buildAuthorizeUrl(config, challenge, state));
  } catch {
    setStatus("error");
  }
}

export function signOut(): void {
  const config = authConfig();
  if (!config) {
    return;
  }
  clearAuthStorage();
  window.location.assign(buildLogoutUrl(config));
}

export function expireSession(): void {
  clearAuthStorage();
  setStatus("expired");
}

// Null when auth is disabled, when no token is stored, or once the token has
// expired, which also ends the session.
export function currentAccessToken(): string | null {
  if (!authConfig()) {
    return null;
  }
  const stored = readStoredToken();
  if (!stored) {
    return null;
  }
  if (stored.expiresAt <= nowInSeconds()) {
    expireSession();
    return null;
  }
  return stored.accessToken;
}
