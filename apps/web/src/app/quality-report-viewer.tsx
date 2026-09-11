"use client";

import { useState } from "react";

type EvidenceReference = {
  kind: string;
  id: string;
};

type FindingCount = {
  severity: string;
  category: string;
  count: number;
};

type QualityReportClaim = {
  id: string;
  kind: string;
  statement: string;
  evidence: EvidenceReference[];
  unsupported: boolean;
  unsupported_reason: string | null;
};

type QualityReportSection = {
  name: string;
  state: string;
  state_reason: string | null;
  claims: QualityReportClaim[];
};

type QualityReport = {
  schema_version: string;
  id: string;
  project_id: string;
  created_at: string;
  generator_version: string;
  evidence_catalog: EvidenceReference[];
  provenance: {
    source_document_version_ids: string[];
    requirement_analysis_run_ids: string[];
    generated_test_case_ids: string[];
    execution_job_ids: string[];
  };
  sections: QualityReportSection[];
};

type QualityReportSummary = {
  source_document_version_count: number;
  requirement_analysis_run_count: number;
  finding_count: number;
  finding_counts: FindingCount[];
  generated_test_case_count: number;
  execution_count: number;
  succeeded_execution_count: number;
  failed_execution_count: number;
  cancelled_execution_count: number;
  failure_analysis_count: number;
};

type QualityReportRevision = {
  id: string;
  project_id: string;
  schema_version: string;
  report_sha256: string;
  snapshot_sha256: string;
  created_at: string;
  snapshot: {
    report: QualityReport;
    summary: QualityReportSummary;
  };
};

async function responseError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    const body: unknown = await response.json();

    if (
      typeof body === "object" &&
      body !== null &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  }

  return `${response.status} ${response.statusText}`;
}

function label(value: string): string {
  return value.replaceAll("_", " ");
}

function IdentifierList({
  title,
  identifiers,
}: {
  title: string;
  identifiers: string[];
}) {
  return (
    <li>
      <strong>{title}:</strong>{" "}
      {identifiers.length === 0 ? (
        "None"
      ) : (
        <ul>
          {identifiers.map((identifier) => (
            <li key={identifier}>
              <code>{identifier}</code>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function QualityReportViewer({ projectId }: { projectId: string }) {
  const [revisions, setRevisions] = useState<QualityReportRevision[]>([]);
  const [selectedRevision, setSelectedRevision] =
    useState<QualityReportRevision | null>(null);
  const [message, setMessage] = useState(
    "Load report revisions for this project.",
  );
  const [busy, setBusy] = useState(false);

  const reportsPath = `/api/projects/${encodeURIComponent(
    projectId,
  )}/quality-reports`;

  async function loadReports(): Promise<void> {
    setBusy(true);
    setMessage("Loading immutable quality report revisions...");

    try {
      const response = await fetch(reportsPath);

      if (!response.ok) {
        throw new Error(await responseError(response));
      }

      const loaded = (await response.json()) as QualityReportRevision[];

      setRevisions(loaded);
      setSelectedRevision((current) => {
        if (current === null) {
          return loaded[0] ?? null;
        }

        return (
          loaded.find((revision) => revision.id === current.id) ??
          loaded[0] ??
          null
        );
      });
      setMessage(
        loaded.length === 0
          ? "No quality report revisions exist for this project."
          : `${loaded.length} immutable quality report revision(s) loaded.`,
      );
    } catch (error) {
      setMessage(
        `Could not load quality reports: ${
          error instanceof Error ? error.message : "Unknown error"
        }`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function generateReport(): Promise<void> {
    setBusy(true);
    setMessage("Generating an immutable quality report revision...");

    try {
      const response = await fetch(reportsPath, {
        method: "POST",
      });

      if (!response.ok) {
        throw new Error(await responseError(response));
      }

      const created = (await response.json()) as QualityReportRevision;

      setRevisions((current) => [
        created,
        ...current.filter((revision) => revision.id !== created.id),
      ]);
      setSelectedRevision(created);
      setMessage(`Generated immutable quality report revision ${created.id}.`);
    } catch (error) {
      setMessage(
        `Could not generate a quality report: ${
          error instanceof Error ? error.message : "Unknown error"
        }`,
      );
    } finally {
      setBusy(false);
    }
  }

  async function openRevision(revisionId: string): Promise<void> {
    setBusy(true);
    setMessage("Loading immutable report snapshot...");

    try {
      const response = await fetch(
        `${reportsPath}/${encodeURIComponent(revisionId)}`,
      );

      if (!response.ok) {
        throw new Error(await responseError(response));
      }

      const revision = (await response.json()) as QualityReportRevision;

      setRevisions((current) =>
        current.map((existing) =>
          existing.id === revision.id ? revision : existing,
        ),
      );
      setSelectedRevision(revision);
      setMessage(`Viewing immutable quality report revision ${revision.id}.`);
    } catch (error) {
      setMessage(
        `Could not load the report revision: ${
          error instanceof Error ? error.message : "Unknown error"
        }`,
      );
    } finally {
      setBusy(false);
    }
  }

  const report = selectedRevision?.snapshot.report;
  const summary = selectedRevision?.snapshot.summary;

  return (
    <section aria-labelledby="quality-reports-heading">
      <h3 id="quality-reports-heading">Quality reports</h3>

      <p>
        Generating a report creates a new immutable revision. It does not modify
        prior revisions or rerun execution jobs.
      </p>

      <p aria-live="polite">{message}</p>

      <p>
        <button
          type="button"
          disabled={busy}
          onClick={() => void generateReport()}
        >
          Generate quality report
        </button>{" "}
        <button
          type="button"
          disabled={busy}
          onClick={() => void loadReports()}
        >
          Load report revisions
        </button>
      </p>

      {revisions.length > 0 && (
        <>
          <h4>Available revisions</h4>

          <ul>
            {revisions.map((revision) => (
              <li key={revision.id}>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void openRevision(revision.id)}
                >
                  View snapshot
                </button>{" "}
                <code>{revision.id}</code> — {revision.created_at}
              </li>
            ))}
          </ul>
        </>
      )}

      {selectedRevision !== null &&
        report !== undefined &&
        summary !== undefined && (
          <article aria-labelledby="quality-report-detail-heading">
            <h4 id="quality-report-detail-heading">Selected report snapshot</h4>

            <p>
              <a
                href={`${reportsPath}/${encodeURIComponent(
                  selectedRevision.id,
                )}/export/markdown`}
              >
                Download Markdown (.md)
              </a>{" "}
              <a
                href={`${reportsPath}/${encodeURIComponent(
                  selectedRevision.id,
                )}/export/json`}
              >
                Download canonical JSON (.json)
              </a>
            </p>

            <dl>
              <dt>Revision ID</dt>
              <dd>
                <code>{selectedRevision.id}</code>
              </dd>

              <dt>Created</dt>
              <dd>{selectedRevision.created_at}</dd>

              <dt>Schema version</dt>
              <dd>{selectedRevision.schema_version}</dd>

              <dt>Generator version</dt>
              <dd>{report.generator_version}</dd>

              <dt>Report SHA-256</dt>
              <dd>
                <code>{selectedRevision.report_sha256}</code>
              </dd>

              <dt>Snapshot SHA-256</dt>
              <dd>
                <code>{selectedRevision.snapshot_sha256}</code>
              </dd>
            </dl>

            <h5>Summary</h5>

            <ul>
              <li>
                Source document versions:{" "}
                {summary.source_document_version_count}
              </li>
              <li>
                Requirement analysis runs:{" "}
                {summary.requirement_analysis_run_count}
              </li>
              <li>Findings: {summary.finding_count}</li>
              <li>Generated test cases: {summary.generated_test_case_count}</li>
              <li>Executions: {summary.execution_count}</li>
              <li>Succeeded executions: {summary.succeeded_execution_count}</li>
              <li>Failed executions: {summary.failed_execution_count}</li>
              <li>Cancelled executions: {summary.cancelled_execution_count}</li>
              <li>Failure analyses: {summary.failure_analysis_count}</li>
            </ul>

            <h5>Finding counts</h5>

            {summary.finding_counts.length === 0 ? (
              <p>No findings were included in this report.</p>
            ) : (
              <ul>
                {summary.finding_counts.map((finding) => (
                  <li key={`${finding.severity}:${finding.category}`}>
                    {finding.count} × {finding.severity} / {finding.category}
                  </li>
                ))}
              </ul>
            )}

            <h5>Report sections</h5>

            <ol>
              {report.sections.map((section) => (
                <li key={section.name}>
                  <h6>{section.name}</h6>
                  <p>
                    State: <strong>{label(section.state)}</strong>
                    {section.state_reason !== null &&
                      ` — ${section.state_reason}`}
                  </p>

                  {section.claims.length === 0 ? (
                    <p>No claims were recorded for this section.</p>
                  ) : (
                    <ul>
                      {section.claims.map((claim) => (
                        <li key={claim.id}>
                          <p>
                            <strong>{claim.kind}:</strong> {claim.statement}
                          </p>

                          {claim.unsupported && (
                            <p>
                              <strong>Limitation:</strong>{" "}
                              {claim.unsupported_reason ?? "Unsupported claim."}
                            </p>
                          )}

                          <p>
                            Evidence:{" "}
                            {claim.evidence.length === 0
                              ? "None"
                              : claim.evidence.map((evidence, index) => (
                                  <span key={`${evidence.kind}:${evidence.id}`}>
                                    {index > 0 ? ", " : ""}
                                    <code>
                                      {evidence.kind}:{evidence.id}
                                    </code>
                                  </span>
                                ))}
                          </p>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>

            <h5>Provenance</h5>

            <ul>
              <IdentifierList
                title="Source document versions"
                identifiers={report.provenance.source_document_version_ids}
              />
              <IdentifierList
                title="Requirement analysis runs"
                identifiers={report.provenance.requirement_analysis_run_ids}
              />
              <IdentifierList
                title="Generated test cases"
                identifiers={report.provenance.generated_test_case_ids}
              />
              <IdentifierList
                title="Execution jobs"
                identifiers={report.provenance.execution_job_ids}
              />
            </ul>

            <p>Evidence catalog entries: {report.evidence_catalog.length}</p>
          </article>
        )}
    </section>
  );
}
