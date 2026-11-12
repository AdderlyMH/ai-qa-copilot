// Reads the exp claim for the UI only. This is not verification: the signature is
// not checked here, and the API remains the only judge of a token.
export function decodeJwtExp(token: string): number | null {
  const payload = token.split(".")[1];
  if (!payload) {
    return null;
  }
  try {
    const padded = payload
      .replace(/-/g, "+")
      .replace(/_/g, "/")
      .padEnd(Math.ceil(payload.length / 4) * 4, "=");
    const claims: unknown = JSON.parse(atob(padded));
    if (
      typeof claims === "object" &&
      claims !== null &&
      "exp" in claims &&
      typeof claims.exp === "number" &&
      Number.isFinite(claims.exp)
    ) {
      return claims.exp;
    }
  } catch {
    return null;
  }
  return null;
}
