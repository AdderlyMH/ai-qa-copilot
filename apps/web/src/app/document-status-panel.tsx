"use client";

import type { DocumentStatusItem, PollingPhase } from "./use-document-polling";

const PHASE_NOTES: Partial<Record<PollingPhase, string>> = {
  retrying: "Status is temporarily unavailable. Retrying more slowly.",
  capped: "Still processing; reload to check.",
  failed: "Document status could not be loaded.",
  unauthorized: "Sign in to see document status.",
};

// The API returns no parser rejection reason: rejection_code is set only for
// upload-time rejections, so it is null for parse_failed. An empty result (no
// "- REQ-ID: text" lines) is the case seen in production, but other parser
// failures also end as parse_failed, so the hint names a likely reason only.
export const PARSE_FAILED_HINT =
  "Likely reason: No requirement lines were found. Use lines like - REQ-ORDER-001: text. See the accepted format in the docs.";

function showsParseFailedHint(item: DocumentStatusItem): boolean {
  return item.status === "parse_failed" && item.parser_stage === "rejected";
}

function newestFirst(documents: DocumentStatusItem[]): DocumentStatusItem[] {
  return [...documents].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
}

export function DocumentStatusPanel({
  documents,
  phase,
}: {
  documents: DocumentStatusItem[];
  phase: PollingPhase;
}) {
  return (
    <section aria-labelledby="document-status">
      <h3 id="document-status">Documents</h3>
      <p aria-live="polite">{PHASE_NOTES[phase]}</p>
      {documents.length === 0 ? (
        <p>No documents uploaded.</p>
      ) : (
        <ul>
          {newestFirst(documents).map((item) => (
            <li key={item.id} style={{ marginBottom: "0.75rem" }}>
              <strong>{item.filename}</strong> · {item.byte_size} bytes ·{" "}
              {item.status}
              {item.parser_stage ? ` · parser: ${item.parser_stage}` : null}
              {item.rejection_code ? ` · ${item.rejection_code}` : null} ·{" "}
              {item.created_at}
              {showsParseFailedHint(item) ? (
                <div>{PARSE_FAILED_HINT}</div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
