"use client";

import { FormEvent, useState } from "react";

type ExecutionPlanReview = {
  plan_id: string;
  plan_hash: string;
  target_id: string;
  target_base_url: string;
  test_case_id: string;
  method: string;
  path: string;
  citation_ids: string[];
  limits: {
    request_timeout_ms: number;
    max_request_body_bytes: number;
    max_response_bytes: number;
    max_assertions: number;
  };
  estimate: {
    request_count: number;
    request_body_bytes: number;
    assertion_count: number;
    maximum_response_bytes: number;
    maximum_duration_ms: number;
  };
};

type ReviewedPlanRequest = {
  generated_test_case: Record<string, unknown>;
  target_id: string;
  limits: {
    request_timeout_ms: number;
    max_request_body_bytes: number;
    max_response_bytes: number;
    max_assertions: number;
  };
  expected_plan_hash: string;
};

type ExecutionApproval = {
  id: string;
  project_id: string;
  plan_id: string;
  plan_hash: string;
  approver_id: string;
  approver_authentication_source: string;
  comment: string | null;
  approved_at: string;
  expires_at: string;
  consumed_at: string | null;
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

function parseGeneratedTestCase(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Generated test payload must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

export function ExecutionPlanReviewPanel({ projectId }: { projectId: string }) {
  const [generatedTestCase, setGeneratedTestCase] = useState("");
  const [timeoutMs, setTimeoutMs] = useState("10000");
  const [maxRequestBodyBytes, setMaxRequestBodyBytes] = useState("64000");
  const [maxResponseBytes, setMaxResponseBytes] = useState("256000");
  const [maxAssertions, setMaxAssertions] = useState("20");
  const [approvalComment, setApprovalComment] = useState("");
  const [review, setReview] = useState<ExecutionPlanReview | null>(null);
  const [reviewedPlanRequest, setReviewedPlanRequest] =
    useState<ReviewedPlanRequest | null>(null);
  const [approval, setApproval] = useState<ExecutionApproval | null>(null);
  const [message, setMessage] = useState(
    "Paste a validated generated-test JSON payload to preview its immutable execution plan.",
  );
  const [busy, setBusy] = useState(false);

  function invalidatePreview() {
    if (reviewedPlanRequest !== null) {
      setMessage("Plan input changed. Preview the immutable plan again.");
    }
    setReview(null);
    setReviewedPlanRequest(null);
    setApproval(null);
  }

  async function previewPlan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    let payload: Record<string, unknown>;
    try {
      payload = parseGeneratedTestCase(generatedTestCase);
    } catch (error) {
      setReview(null);
      setReviewedPlanRequest(null);
      setApproval(null);
      setMessage(
        error instanceof Error
          ? error.message
          : "Generated test payload is not valid JSON.",
      );
      return;
    }

    const limits = {
      request_timeout_ms: Number(timeoutMs),
      max_request_body_bytes: Number(maxRequestBodyBytes),
      max_response_bytes: Number(maxResponseBytes),
      max_assertions: Number(maxAssertions),
    };

    setBusy(true);
    try {
      const response = await fetch(
        `/api/projects/${projectId}/execution-plan-reviews`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            generated_test_case: payload,
            target_id: "synthetic-order-api",
            limits,
          }),
        },
      );
      if (!response.ok) {
        throw new Error(await responseError(response));
      }

      const planReview = (await response.json()) as ExecutionPlanReview;
      setReview(planReview);
      setReviewedPlanRequest({
        generated_test_case: payload,
        target_id: "synthetic-order-api",
        limits,
        expected_plan_hash: planReview.plan_hash,
      });
      setApproval(null);
      setMessage(
        "Plan preview created. You may approve this exact immutable plan once.",
      );
    } catch (error) {
      setReview(null);
      setReviewedPlanRequest(null);
      setApproval(null);
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to create the plan preview.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function approvePlan() {
    if (reviewedPlanRequest === null || review === null) {
      setMessage("Preview an immutable plan before creating an approval.");
      return;
    }

    setBusy(true);
    try {
      const response = await fetch(
        `/api/projects/${projectId}/execution-approvals`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...reviewedPlanRequest,
            comment: approvalComment || null,
          }),
        },
      );
      if (!response.ok) {
        throw new Error(await responseError(response));
      }

      const createdApproval = (await response.json()) as ExecutionApproval;
      setApproval(createdApproval);
      setMessage(
        "Approval created for the displayed immutable plan. It expires automatically.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "Unable to create the approval.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="execution-plan-review"
      style={{ marginTop: "1.5rem" }}
    >
      <h3 id="execution-plan-review">Execution-plan review</h3>
      <p>
        Preview validates a canonical plan. Approval binds one owner decision to
        its displayed hash; it does not execute a request.
      </p>

      <form onSubmit={previewPlan} style={{ display: "grid", gap: "0.75rem" }}>
        <label>
          Generated-test JSON
          <textarea
            required
            value={generatedTestCase}
            onChange={(event) => {
              setGeneratedTestCase(event.target.value);
              invalidatePreview();
            }}
            placeholder='{"schema_version":"generated-test-case/v1", ...}'
            rows={12}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <label>
          Target
          <input
            disabled
            readOnly
            value="synthetic-order-api"
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <label>
          Timeout (milliseconds)
          <input
            min={1}
            max={30000}
            required
            type="number"
            value={timeoutMs}
            onChange={(event) => {
              setTimeoutMs(event.target.value);
              invalidatePreview();
            }}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <label>
          Maximum request-body bytes
          <input
            min={1}
            max={1000000}
            required
            type="number"
            value={maxRequestBodyBytes}
            onChange={(event) => {
              setMaxRequestBodyBytes(event.target.value);
              invalidatePreview();
            }}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <label>
          Maximum response bytes
          <input
            min={1}
            max={1000000}
            required
            type="number"
            value={maxResponseBytes}
            onChange={(event) => {
              setMaxResponseBytes(event.target.value);
              invalidatePreview();
            }}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <label>
          Maximum assertions
          <input
            min={1}
            max={20}
            required
            type="number"
            value={maxAssertions}
            onChange={(event) => {
              setMaxAssertions(event.target.value);
              invalidatePreview();
            }}
            style={{ display: "block", width: "100%" }}
          />
        </label>

        <button disabled={busy} type="submit">
          Preview immutable plan
        </button>
      </form>

      <p aria-live="polite">{message}</p>

      {review ? (
        <section aria-labelledby="plan-preview-result">
          <h4 id="plan-preview-result">Read-only plan preview</h4>
          <p>
            <strong>Plan hash:</strong> <code>{review.plan_hash}</code>
          </p>
          <p>
            <strong>Target:</strong> {review.target_id} (
            {review.target_base_url})
          </p>
          <p>
            <strong>Request:</strong> {review.method} {review.path}
          </p>
          <p>
            <strong>Test case:</strong> {review.test_case_id}
          </p>
          <p>
            <strong>Citations:</strong> {review.citation_ids.join(", ")}
          </p>
          <p>
            <strong>Limits:</strong> {review.limits.request_timeout_ms} ms ·{" "}
            {review.limits.max_request_body_bytes} request-body bytes ·{" "}
            {review.limits.max_response_bytes} response bytes ·{" "}
            {review.limits.max_assertions} assertions
          </p>
          <p>
            <strong>Estimate:</strong> {review.estimate.request_count} request ·{" "}
            {review.estimate.request_body_bytes} request-body bytes ·{" "}
            {review.estimate.assertion_count} assertions · up to{" "}
            {review.estimate.maximum_duration_ms} ms and{" "}
            {review.estimate.maximum_response_bytes} response bytes
          </p>

          {approval === null ? (
            <section aria-labelledby="plan-approval">
              <h4 id="plan-approval">Approve displayed plan</h4>
              <label>
                Approval comment (optional)
                <textarea
                  value={approvalComment}
                  onChange={(event) => setApprovalComment(event.target.value)}
                  maxLength={1000}
                  rows={3}
                  style={{ display: "block", width: "100%" }}
                />
              </label>
              <p>
                Approval expires after 10 minutes and can be consumed only once
                by a future restricted worker.
              </p>
              <button disabled={busy} onClick={approvePlan} type="button">
                Approve displayed plan
              </button>
            </section>
          ) : (
            <section aria-labelledby="approval-result">
              <h4 id="approval-result">Approval created</h4>
              <p>
                <strong>Approval ID:</strong> <code>{approval.id}</code>
              </p>
              <p>
                <strong>Expires at:</strong> {approval.expires_at}
              </p>
              <p>
                This approval is recorded for the displayed plan hash and does
                not execute a request.
              </p>
            </section>
          )}
        </section>
      ) : null}
    </section>
  );
}
