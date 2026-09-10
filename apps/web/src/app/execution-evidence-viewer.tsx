"use client";

import { FormEvent, useState } from "react";

type ExecutionEvidence = {
  id: string;
  execution_job_id: string;
  outcome: string;
  failure_code: string | null;
  assertion_results: Record<string, unknown>[];
  request_evidence: Record<string, unknown> | null;
  response_evidence: Record<string, unknown> | null;
  response_status_code: number | null;
  response_elapsed_ms: number | null;
  transport_send_count: number;
  recorded_at: string;
};

type FailureAnalysisItem = {
  code: string;
  statement: string;
};

type ExecutionFailureAnalysis = {
  execution_job_id: string;
  outcome: string;
  failure_code: string;
  evidence_sufficiency: string;
  root_cause: null;
  observations: FailureAnalysisItem[];
  hypotheses: FailureAnalysisItem[];
  alternatives: FailureAnalysisItem[];
  next_checks: FailureAnalysisItem[];
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

function evidenceJson(value: Record<string, unknown> | null): string {
  return value === null
    ? "No evidence was recorded."
    : JSON.stringify(value, null, 2);
}

function isFailureOutcome(outcome: string): boolean {
  return outcome === "failed" || outcome === "cancelled";
}

function FailureAnalysisList({
  title,
  items,
}: {
  title: string;
  items: FailureAnalysisItem[];
}) {
  return (
    <section aria-label={title}>
      <h5>{title}</h5>
      <ul>
        {items.map((item) => (
          <li key={item.code}>{item.statement}</li>
        ))}
      </ul>
    </section>
  );
}

export function ExecutionEvidenceViewer({ projectId }: { projectId: string }) {
  const [jobId, setJobId] = useState("");
  const [evidence, setEvidence] = useState<ExecutionEvidence | null>(null);
  const [failureAnalysis, setFailureAnalysis] =
    useState<ExecutionFailureAnalysis | null>(null);
  const [message, setMessage] = useState(
    "Enter an execution job ID to view its redacted evidence.",
  );
  const [busy, setBusy] = useState(false);

  async function viewEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const candidate = jobId.trim();
    if (!candidate) {
      return;
    }

    setBusy(true);
    setEvidence(null);
    setFailureAnalysis(null);

    try {
      const evidenceResponse = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/execution-jobs/${encodeURIComponent(candidate)}/evidence`,
      );
      if (!evidenceResponse.ok) {
        throw new Error(await responseError(evidenceResponse));
      }

      const loadedEvidence =
        (await evidenceResponse.json()) as ExecutionEvidence;
      setEvidence(loadedEvidence);

      if (!isFailureOutcome(loadedEvidence.outcome)) {
        setMessage(
          "Redacted execution evidence loaded. Failure analysis is not applicable to a successful result.",
        );
        return;
      }

      const analysisResponse = await fetch(
        `/api/projects/${encodeURIComponent(projectId)}/execution-jobs/${encodeURIComponent(candidate)}/failure-analysis`,
      );
      if (!analysisResponse.ok) {
        setMessage(
          `Redacted execution evidence loaded. Failure analysis is unavailable: ${await responseError(analysisResponse)}`,
        );
        return;
      }

      const loadedAnalysis =
        (await analysisResponse.json()) as ExecutionFailureAnalysis;
      setFailureAnalysis(loadedAnalysis);
      setMessage(
        "Redacted execution evidence and evidence-grounded failure analysis loaded.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to load execution evidence.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="execution-evidence-viewer"
      style={{ marginTop: "1.5rem" }}
    >
      <h3 id="execution-evidence-viewer">Execution evidence</h3>
      <p>
        This view displays durable, redacted evidence for one completed
        execution job. Failure analysis separates observed facts from hypotheses
        and never asserts a root cause from one result.
      </p>

      <form onSubmit={viewEvidence} style={{ display: "grid", gap: "0.5rem" }}>
        <label>
          Execution job ID
          <input
            aria-describedby="execution-evidence-message"
            required
            value={jobId}
            onChange={(event) => setJobId(event.target.value)}
            style={{ display: "block", width: "100%" }}
          />
        </label>
        <button disabled={busy} type="submit">
          View redacted evidence
        </button>
      </form>

      <p aria-live="polite" id="execution-evidence-message">
        {message}
      </p>

      {evidence ? (
        <article aria-label="Redacted execution evidence">
          <p>
            <strong>Outcome:</strong> {evidence.outcome}
          </p>
          <p>
            <strong>Failure code:</strong> {evidence.failure_code || "None"}
          </p>
          <p>
            <strong>Transport sends:</strong> {evidence.transport_send_count}
          </p>
          <p>
            <strong>Response status:</strong>{" "}
            {evidence.response_status_code ?? "No response received"}
          </p>
          <p>
            <strong>Response time:</strong>{" "}
            {evidence.response_elapsed_ms === null
              ? "No response received"
              : `${evidence.response_elapsed_ms} ms`}
          </p>
          <p>
            <strong>Recorded at:</strong> {evidence.recorded_at}
          </p>

          {failureAnalysis ? (
            <section aria-labelledby="execution-failure-analysis">
              <h4 id="execution-failure-analysis">Failure analysis</h4>
              <p>
                <strong>Root cause:</strong> Not asserted.
              </p>
              <p>
                <strong>Evidence sufficiency:</strong>{" "}
                {failureAnalysis.evidence_sufficiency.replaceAll("_", " ")}
              </p>
              <FailureAnalysisList
                title="Observed facts"
                items={failureAnalysis.observations}
              />
              <FailureAnalysisList
                title="Hypotheses"
                items={failureAnalysis.hypotheses}
              />
              <FailureAnalysisList
                title="Alternative explanations"
                items={failureAnalysis.alternatives}
              />
              <FailureAnalysisList
                title="Recommended next checks"
                items={failureAnalysis.next_checks}
              />
            </section>
          ) : null}

          <section aria-labelledby="execution-assertions">
            <h4 id="execution-assertions">Assertions</h4>
            {evidence.assertion_results.length === 0 ? (
              <p>No assertions were evaluated.</p>
            ) : (
              <pre style={{ overflowX: "auto", whiteSpace: "pre-wrap" }}>
                {JSON.stringify(evidence.assertion_results, null, 2)}
              </pre>
            )}
          </section>

          <section aria-labelledby="execution-request-evidence">
            <h4 id="execution-request-evidence">Request evidence</h4>
            <pre style={{ overflowX: "auto", whiteSpace: "pre-wrap" }}>
              {evidenceJson(evidence.request_evidence)}
            </pre>
          </section>

          <section aria-labelledby="execution-response-evidence">
            <h4 id="execution-response-evidence">Response evidence</h4>
            <pre style={{ overflowX: "auto", whiteSpace: "pre-wrap" }}>
              {evidenceJson(evidence.response_evidence)}
            </pre>
          </section>
        </article>
      ) : null}
    </section>
  );
}
