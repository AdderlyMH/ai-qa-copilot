import { base64UrlEncode } from "./pkce";

export function createState(): string {
  return base64UrlEncode(crypto.getRandomValues(new Uint8Array(32)));
}

export function statesMatch(expected: string, received: string): boolean {
  return expected.length > 0 && expected === received;
}
