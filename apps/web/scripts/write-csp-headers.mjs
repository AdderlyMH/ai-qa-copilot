// Writes out/_headers for the owner-app export. Hosts come from the build
// environment. Inline scripts and prerendered styles are allowed by SHA-256 hash
// only, so this must read the finished HTML: a nonce needs a server, and the
// export has none. Demo-mode builds do not export and get no file.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// VERIFIED: 2000 characters per line and 100 header rules, as stated in the
// Cloudflare Pages "Headers" docs, checked 2026-11-05:
// https://developers.cloudflare.com/pages/configuration/headers/
const MAX_LINE_LENGTH = 2000;
const MAX_HEADER_RULES = 100;
const OUT_DIR = "out";

const ENTITIES = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#x27;": "'",
  "&#39;": "'",
};

function sha256Source(text) {
  const digest = createHash("sha256").update(text, "utf8").digest("base64");
  return `'sha256-${digest}'`;
}

// CSP hashes a style attribute's parsed value, not its HTML source.
function decodeAttribute(value) {
  return value.replace(
    /&(?:amp|lt|gt|quot|#x27|#39);/g,
    (entity) => ENTITIES[entity],
  );
}

function collectHashes(html, scripts, styles) {
  for (const [, attributes, body] of html.matchAll(
    /<script\b([^>]*)>([\s\S]*?)<\/script>/g,
  )) {
    if (!/\ssrc=/.test(attributes)) {
      scripts.add(sha256Source(body));
    }
  }
  const markup = html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "");
  for (const [, body] of markup.matchAll(
    /<style\b[^>]*>([\s\S]*?)<\/style>/g,
  )) {
    styles.add(sha256Source(body));
  }
  for (const [, value] of markup.matchAll(/\sstyle="([^"]*)"/g)) {
    styles.add(sha256Source(decodeAttribute(value)));
  }
}

function requiredOrigin(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} must be set to generate the CSP.`);
  }
  return new URL(value).origin;
}

function main() {
  if (process.env.PUBLIC_DEMO_MODE === "true") {
    return;
  }
  const htmlFiles = readdirSync(OUT_DIR, { recursive: true })
    .map(String)
    .filter((file) => file.endsWith(".html"));
  if (htmlFiles.length === 0) {
    throw new Error("No exported HTML found; cannot generate the CSP.");
  }

  const scripts = new Set();
  const styles = new Set();
  for (const file of htmlFiles) {
    collectHashes(readFileSync(join(OUT_DIR, file), "utf8"), scripts, styles);
  }

  const policy = [
    "default-src 'self'",
    `script-src 'self' ${[...scripts].join(" ")}`,
    `style-src 'self' 'unsafe-hashes' ${[...styles].join(" ")}`,
    `connect-src 'self' ${requiredOrigin("NEXT_PUBLIC_API_BASE_URL")} ${requiredOrigin("NEXT_PUBLIC_COGNITO_DOMAIN")}`,
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");

  const line = `  Content-Security-Policy: ${policy}`;
  if (line.length > MAX_LINE_LENGTH) {
    throw new Error(
      `The CSP line is ${line.length} characters; the _headers limit is ${MAX_LINE_LENGTH}.`,
    );
  }
  const headersFile = `/*\n${line}\n`;
  // A rule starts at an unindented line; headers under it are indented.
  const ruleCount = headersFile
    .split("\n")
    .filter((text) => text !== "" && !/^\s/.test(text)).length;
  if (ruleCount > MAX_HEADER_RULES) {
    throw new Error(
      `The _headers file has ${ruleCount} rules; the limit is ${MAX_HEADER_RULES}.`,
    );
  }
  writeFileSync(join(OUT_DIR, "_headers"), headersFile);
  console.log(
    `Wrote ${OUT_DIR}/_headers: ${scripts.size} script and ${styles.size} style hashes, ${line.length} characters.`,
  );
}

main();
