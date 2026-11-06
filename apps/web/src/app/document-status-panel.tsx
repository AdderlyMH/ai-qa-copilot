"use client";

import type { DocumentStatusItem, PollingPhase } from "./use-document-polling";

const PHASE_NOTES: Partial<Record<PollingPhase, string>> = {
  retrying: "Status is temporarily unavailable. Retrying more slowly.",
  capped: "Still processing; reload to check.",
  failed: "Document status could not be loaded.",
  unauthorized: "Sign in to see document status.",
};

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
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
