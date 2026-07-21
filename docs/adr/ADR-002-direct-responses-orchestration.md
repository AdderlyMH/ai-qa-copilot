# ADR-002 — Direct Responses API orchestration

- **Status:** Accepted
- **Date:** 2026-07-18
- **Decision owner:** Project owner
- **Scope:** MVP model orchestration, structured-output handling, and workflow control.

## Context

The workflow needs structured outputs, retrieval, tool proposals, deterministic state transitions, approval boundaries, and reproducible evaluation. Those responsibilities must remain inspectable in application code because they govern authorization, execution eligibility, provenance, and release quality.

A large agent framework would add hidden state, framework-specific control flow, and operational complexity before its benefit has been measured. Without this decision, provider SDK calls could spread across domain modules and model behavior could become coupled to authorization, routing, or execution control.

## Decision

- Use direct OpenAI Responses API orchestration through a local ModelGateway.
- Let domain services own workflow state, retries, and state transitions.
- Validate material model output with versioned Pydantic schemas.
- Keep authorization, routing, validation, approval, and execution in deterministic application code.
- Do not use an autonomous multi-agent system in the MVP.
- Consider an agent runtime only after a baseline comparison shows measurable improvement in reliability, human-interruption handling, tracing, or implementation complexity.

## Alternatives considered

| Alternative | Decision | Reason |
|---|---|---|
| Multi-agent framework | Rejected | Multiple autonomous agents add coordination and hidden-state risk without evidence that they improve the fixed MVP workflow. |
| OpenAI Agents SDK as the primary orchestrator | Deferred | It may be evaluated later for one orchestrator, but direct Responses API calls keep MVP state and controls explicit. |
| LangGraph or similar workflow framework | Deferred | A framework may be reconsidered after a measured workflow problem, not as a default abstraction. |
| Provider-specific logic directly in domain modules | Rejected | It would duplicate provider policy, make fake adapters difficult, and weaken provenance and testing boundaries. |

## Consequences

### Positive consequences

- Workflow state, authorization, approval, and execution boundaries remain visible and testable.
- Model calls receive one adapter for timeout, retry, schema, redaction, usage, and provenance handling.
- Baseline comparisons can distinguish model quality changes from orchestration changes.

### Costs and trade-offs

- The application must implement its own small orchestration and retry policy.
- A later framework adoption requires a measured comparison and migration plan.
- The ModelGateway contract must evolve carefully when provider capabilities change.

## Security, cost, and operational impact

### Security

- The model may propose typed outputs but cannot authorize actions, mutate workflow state outside validation, or access target-network authority.
- Provider credentials remain confined to the general analysis worker and ModelGateway path.

### Cost

- Central usage and cost extraction supports task-specific routing, caps, and reproducible cost reporting.
- The project accepts the cost of maintaining a small gateway to avoid uncontrolled model-call patterns.

### Operations

- ModelGateway owns provider configuration, timeouts, bounded retries, error normalization, correlation IDs, and redaction.
- Prompt, model, schema, retrieval, and response configuration are recorded as run provenance.

## Validation

The following are planned acceptance conditions; this ADR records no executed validation evidence.

| Validation | Required result |
|---|---|
| Fake model-adapter tests | Deterministic tests can simulate valid, invalid, timeout, and retry outcomes without paid model calls. |
| Structured-output validity | Material outputs conform to their Pydantic schemas or fail explicitly after the bounded repair policy. |
| Reproducible run provenance | Each model run records model, prompt, schema, retrieval, request, response-validation, latency, usage, cost, and error metadata. |
| Baseline comparison | A direct-workflow baseline is compared before an agent runtime is added. |
| Provider-call boundary scan | No provider SDK call occurs outside ModelGateway. |

## Rollback criteria

- Disable a new orchestration, prompt, model, or gateway release when it causes invalid structured output, authorization-boundary failure, unacceptable cost, or a measurable regression against the baseline.
- Restore the last validated ModelGateway and workflow configuration while preserving immutable run provenance and error records.
- Do not replace deterministic workflow control with autonomous agents as a rollback action.
- Re-enable a changed orchestration only after fake-adapter, schema, provenance, security-boundary, and baseline-comparison checks satisfy the recorded acceptance conditions.

## Links

- [Product requirements — retrieval and evidence](../PRODUCT_REQUIREMENTS.md#64-retrieval-and-evidence)
- [Product requirements — test generation](../PRODUCT_REQUIREMENTS.md#66-test-generation)
- [Architecture — model gateway](../ARCHITECTURE.md#81-model-gateway)
- [Architecture — workflow strategy](../ARCHITECTURE.md#82-workflow-strategy)
- [Evaluation plan — baselines and candidates](../EVALUATION_PLAN.md#11-baselines-and-candidates)
- [Evaluation plan — reproducibility and provenance](../EVALUATION_PLAN.md#16-reproducibility-and-provenance)
