"""Deterministically derive the v3 corpus from the budgeted v2 corpus.

v3 is v2 with a new suite identifier, hash-form source references everywhere,
and the per-case budget for the informed baseline. Every other case field is
identical. v1 and v2 (and their generators) are not changed: the reference fix is
applied here as a strict normalization pass, so v1 stays bound to B1 evidence and
v2 stays as any earlier run saw it (ADR-015).

Reference defects repaired, all of which contradict the documented grammar
(``REQ-BASE-001#REQ-ORDER-004#statement``, ``OAS-BASE-001#/paths/~1orders/get``):

- the colon locator kind (``REQ-BASE-001#REQ-ORDER-004:statement``);
- a doubled hash before an OpenAPI JSON Pointer (``OAS-BASE-001##/paths/...``);
- a doubled artifact prefix (``OAS-BASE-001#OAS-BASE-001#absence:...``).

Per-case budget derivation (approved 2026-10-05, ADR-015):

- Pricing: 2 USD input and 10 USD output per million tokens.
- Most expensive case: the largest informed prompt (developer text, user
  message, and output schema), 43,197 characters at 2.1 characters per token
  = 20,570 input tokens, plus the 4,096-token output cap.
- Worst case 0.08210 USD, plus 10 percent = 0.09031 USD, rounded up to the cent:
  0.10 USD.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Final, cast

import yaml

from ai_qa_copilot_api.evaluation_budgeted_benchmark import (
    build_budgeted_evaluation_cases,
)
from ai_qa_copilot_api.informed_baseline import (
    OPENAPI_REFERENCE_PATTERN,
    REQUIREMENT_REFERENCE_PATTERN,
)


INFORMED_EVALUATION_CORPUS_SUITE_ID: Final = "evaluation-corpus/v3"
INFORMED_CASE_MAXIMUM_EXPECTED_COST_USD: Final = 0.10

_COLON_LOCATOR_KIND = re.compile(r"^(REQ-BASE-001#[A-Za-z0-9-]+):")
_DOUBLED_ARTIFACT_PREFIX: Final = "OAS-BASE-001#OAS-BASE-001#"
_REFERENCE_GRAMMAR = (
    re.compile(REQUIREMENT_REFERENCE_PATTERN),
    re.compile(OPENAPI_REFERENCE_PATTERN),
)


class EvaluationInformedBenchmarkRejected(ValueError):
    """Raised when the v3 corpus cannot be derived safely."""


def render_informed_evaluation_cases(repository_root: Path) -> str:
    """Render the v3 100-case corpus with the v1 and v2 YAML conventions."""

    return yaml.safe_dump(
        build_informed_evaluation_cases(repository_root),
        sort_keys=False,
        allow_unicode=False,
    )


def build_informed_evaluation_cases(repository_root: Path) -> dict[str, object]:
    """Copy v2, changing only the suite ID, source references, and budgets."""

    corpus = deepcopy(build_budgeted_evaluation_cases(repository_root))
    cases = corpus.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationInformedBenchmarkRejected("v2 corpus must contain cases")

    for case in cast(list[object], cases):
        if not isinstance(case, dict):
            raise EvaluationInformedBenchmarkRejected("v2 case must be a mapping")
        expected = cast(Mapping[str, object], case).get("expected")
        if not isinstance(expected, dict):
            raise EvaluationInformedBenchmarkRejected("v2 case must declare expected")
        expected_fields = cast(dict[str, object], expected)
        references = expected_fields.get("expected_source_references")
        if not isinstance(references, list):
            raise EvaluationInformedBenchmarkRejected(
                "v2 case must declare expected_source_references"
            )
        normalized = [
            normalize_source_reference(reference)
            for reference in cast(list[object], references)
        ]
        if len(set(normalized)) != len(normalized):
            raise EvaluationInformedBenchmarkRejected(
                "Normalization produced duplicate source references"
            )
        expected_fields["expected_source_references"] = normalized
        expected_fields["maximum_expected_cost"] = (
            INFORMED_CASE_MAXIMUM_EXPECTED_COST_USD
        )

    corpus["suite_id"] = INFORMED_EVALUATION_CORPUS_SUITE_ID
    return corpus


def normalize_source_reference(reference: object) -> str:
    """Return the hash-form reference, or refuse a reference it cannot repair."""

    if not isinstance(reference, str):
        raise EvaluationInformedBenchmarkRejected("Source reference must be text")

    normalized = reference
    if normalized.startswith(_DOUBLED_ARTIFACT_PREFIX):
        normalized = normalized.removeprefix("OAS-BASE-001#")
    normalized = normalized.replace("OAS-BASE-001##/", "OAS-BASE-001#/")
    normalized = _COLON_LOCATOR_KIND.sub(r"\1#", normalized)

    if not any(pattern.fullmatch(normalized) for pattern in _REFERENCE_GRAMMAR):
        raise EvaluationInformedBenchmarkRejected(
            f"Source reference cannot be brought to the documented grammar: {reference}"
        )
    return normalized
