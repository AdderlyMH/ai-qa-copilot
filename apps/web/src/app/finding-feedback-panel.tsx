"use client";

import { FormEvent, useState } from "react";

type FindingFeedbackAction = "accept" | "reject" | "annotate";

type FindingFeedback = {
  id: string;
  project_id: string;
  requirement_analysis_run_id: string;
  requirement_finding_id: string;
  citation_ids: string[];
  action: FindingFeedbackAction;
  annotation: string | null;
  reviewer_id: string;
  reviewer_authentication_source: string;
  created_at: string;
};

async function responseError(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => undefined);
  if (
    typeof body === "object" &&
    body !== null &&
    "detail" in body &&
    typeof body.detail === "string"
  ) {
    const correlationId = response.headers.get("X-Correlation-ID");
    return correlationId
      ? `${body.detail} (correlation ID: ${correlationId})`
      : body.detail;
  }
  return `Request failed (${response.status})`;
}

export function FindingFeedbackPanel({ projectId }: { projectId: string }) {
  const [runId, setRunId] = useState("");
  const [findingId, setFindingId] = useState("");
  const [annotation, setAnnotation] = useState("");
  const [history, setHistory] = useState<FindingFeedback[]>([]);
  const [message, setMessage] = useState(
    "Enter an existing requirement-analysis run and finding ID to review it.",
  );
  const [busy, setBusy] = useState(false);

  function feedbackPath() {
    return (
      `/api/projects/${projectId}/requirement-analysis-runs/${runId}/findings/` +
      `${findingId}/feedback`
    );
  }

  async function loadHistory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!runId || !findingId) {
      setMessage("Both the analysis-run ID and finding ID are required.");
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(feedbackPath());
      if (!response.ok) {
        throw new Error(await responseError(response));
      }
      const feedback = (await response.json()) as FindingFeedback[];
      setHistory(feedback);
      setMessage(`${feedback.length} feedback event(s) loaded.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to load feedback.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submitFeedback(action: FindingFeedbackAction) {
    if (!runId || !findingId) {
      setMessage("Both the analysis-run ID and finding ID are required.");
      return;
    }
    if (action === "annotate" && !annotation.trim()) {
      setMessage("Annotate requires a non-empty note.");
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(feedbackPath(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          annotation: action === "annotate" ? annotation : null,
        }),
      });
      if (!response.ok) {
        throw new Error(await responseError(response));
      }

      const feedback = (await response.json()) as FindingFeedback;
      setHistory((current) => [...current, feedback]);
      setAnnotation("");
      setMessage(`Recorded ${action} feedback.`);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Unable to save feedback.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="finding-feedback" style={{ marginTop: "1.5rem" }}>
      <h3 id="finding-feedback">Requirement finding review</h3>
      <p>
        Record an immutable owner decision or annotation for an existing
        requirement-analysis finding.
      </p>

      <form onSubmit={loadHistory} style={{ display: "grid", gap: "0.75rem" }}>
        <label>
          Requirement-analysis run ID
          <input
            required
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            placeholder="UUID"
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <label>
          Finding ID
          <input
            required
            value={findingId}
            onChange={(event) => setFindingId(event.target.value)}
            placeholder="UUID"
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <button disabled={busy} type="submit">
          Load feedback history
        </button>
      </form>

      <div style={{ display: "grid", gap: "0.75rem", marginTop: "1rem" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
          <button
            disabled={busy || !runId || !findingId}
            onClick={() => submitFeedback("accept")}
            type="button"
          >
            Accept
          </button>
          <button
            disabled={busy || !runId || !findingId}
            onClick={() => submitFeedback("reject")}
            type="button"
          >
            Reject
          </button>
        </div>

        <label>
          Annotation
          <textarea
            maxLength={4000}
            value={annotation}
            onChange={(event) => setAnnotation(event.target.value)}
            placeholder="Required only for Annotate."
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <button
          disabled={busy || !runId || !findingId || !annotation.trim()}
          onClick={() => submitFeedback("annotate")}
          type="button"
        >
          Annotate
        </button>
      </div>

      <p aria-live="polite">{message}</p>

      {history.length === 0 ? (
        <p>No feedback events loaded.</p>
      ) : (
        <ol>
          {history.map((feedback) => (
            <li key={feedback.id} style={{ marginBottom: "0.75rem" }}>
              <strong>{feedback.action}</strong> by {feedback.reviewer_id} (
              {feedback.reviewer_authentication_source})
              <br />
              <small>
                {feedback.created_at} · run{" "}
                {feedback.requirement_analysis_run_id} · finding{" "}
                {feedback.requirement_finding_id}
              </small>
              <br />
              <small>Citations: {feedback.citation_ids.join(", ")}</small>
              {feedback.annotation ? <p>{feedback.annotation}</p> : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
