"use client";

import { FormEvent, useState } from "react";

type Citation = {
  id: string;
  document_type: string;
  display_name: string;
  passage: string;
  source_location: {
    location_kind: string;
    heading: string | null;
    line_start: number | null;
    line_end: number | null;
    page_start: number | null;
    page_end: number | null;
    json_pointer: string | null;
  };
};

async function responseError(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => undefined);
  if (
    typeof body === "object" &&
    body !== null &&
    "detail" in body &&
    typeof body.detail === "string"
  ) {
    return body.detail;
  }
  return `Request failed (${response.status})`;
}

function sourceCoordinate(citation: Citation): string {
  const location = citation.source_location;
  const lines =
    location.line_start === null
      ? null
      : location.line_end === null || location.line_end === location.line_start
        ? `line ${location.line_start}`
        : `lines ${location.line_start}-${location.line_end}`;
  const pages =
    location.page_start === null
      ? null
      : location.page_end === null || location.page_end === location.page_start
        ? `page ${location.page_start}`
        : `pages ${location.page_start}-${location.page_end}`;
  return [location.heading, lines, pages, location.json_pointer]
    .filter((item): item is string => item !== null)
    .join(" · ");
}

export function SourcePassageViewer({ projectId }: { projectId: string }) {
  const [citationId, setCitationId] = useState("");
  const [citation, setCitation] = useState<Citation | null>(null);
  const [message, setMessage] = useState(
    "Enter a validated citation ID to view its immutable source passage.",
  );
  const [busy, setBusy] = useState(false);

  async function viewCitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const candidate = citationId.trim();
    if (!candidate) {
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(
        `/api/projects/${projectId}/citations/${candidate}`,
      );
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const loaded = (await response.json()) as Citation;
      setCitation(loaded);
      setMessage("Validated citation loaded.");
    } catch (error) {
      setCitation(null);
      setMessage(
        error instanceof Error ? error.message : "Unable to load the citation.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="source-passage-viewer">
      <h3 id="source-passage-viewer">Source passage</h3>
      <form onSubmit={viewCitation} style={{ display: "grid", gap: "0.5rem" }}>
        <label>
          Citation ID
          <input
            aria-describedby="citation-viewer-message"
            required
            value={citationId}
            onChange={(event) => setCitationId(event.target.value)}
            style={{ display: "block", width: "100%" }}
          />
        </label>
        <button disabled={busy} type="submit">
          View source passage
        </button>
      </form>
      <p aria-live="polite" id="citation-viewer-message">
        {message}
      </p>
      {citation ? (
        <article aria-label="Validated citation source">
          <p>
            <strong>{citation.display_name}</strong> · {citation.document_type}
          </p>
          <p>
            {sourceCoordinate(citation) ||
              citation.source_location.location_kind}
          </p>
          <pre style={{ overflowX: "auto", whiteSpace: "pre-wrap" }}>
            {citation.passage}
          </pre>
        </article>
      ) : null}
    </section>
  );
}
