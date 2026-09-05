"""Deterministic normalization and duplicate-candidate grouping for test proposals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Final
from unicodedata import normalize
from uuid import UUID, uuid5

from ai_qa_copilot_api.generated_tests import (
    AssertionTarget,
    GeneratedTestCaseV1,
)


NORMALIZATION_VERSION: Final = "generated-test-normalization/v1"
DUPLICATE_GROUP_NAMESPACE: Final = UUID("bfa7fa30-b11c-41b7-95d0-3b2fbd63d108")


class TestNormalizationError(ValueError):
    """Raised when generated tests cannot be grouped deterministically."""


@dataclass(frozen=True)
class NormalizedGeneratedTestCaseV1:
    """A comparison-only view that leaves the original proposal unchanged."""

    test_case_id: UUID
    normalized_title: str
    semantic_key: str
    semantic_fingerprint: str


@dataclass(frozen=True)
class DuplicateCandidateGroupV1:
    """A non-destructive group of tests with equivalent observable behavior."""

    id: UUID
    semantic_fingerprint: str
    test_case_ids: tuple[UUID, ...]


def normalize_generated_test_case(
    test_case: GeneratedTestCaseV1,
) -> NormalizedGeneratedTestCaseV1:
    """Create a stable comparison view without changing the supplied proposal."""

    semantic_key = _canonical_json(_semantic_payload(test_case))
    return NormalizedGeneratedTestCaseV1(
        test_case_id=test_case.id,
        normalized_title=_normalize_title(test_case.title),
        semantic_key=semantic_key,
        semantic_fingerprint=sha256(semantic_key.encode("utf-8")).hexdigest(),
    )


def group_duplicate_candidates(
    test_cases: Sequence[GeneratedTestCaseV1],
) -> tuple[DuplicateCandidateGroupV1, ...]:
    """Group equivalent candidates while retaining every original test-case ID."""

    _require_unique_test_case_ids(test_cases)

    members_by_key: dict[str, list[UUID]] = {}
    fingerprints_by_key: dict[str, str] = {}
    for test_case in test_cases:
        normalized = normalize_generated_test_case(test_case)
        members_by_key.setdefault(normalized.semantic_key, []).append(test_case.id)
        fingerprints_by_key[normalized.semantic_key] = normalized.semantic_fingerprint

    groups: list[DuplicateCandidateGroupV1] = []
    for semantic_key in sorted(members_by_key):
        member_ids = tuple(sorted(members_by_key[semantic_key], key=str))
        if len(member_ids) < 2:
            continue
        groups.append(
            DuplicateCandidateGroupV1(
                id=uuid5(DUPLICATE_GROUP_NAMESPACE, semantic_key),
                semantic_fingerprint=fingerprints_by_key[semantic_key],
                test_case_ids=member_ids,
            )
        )
    return tuple(groups)


def _require_unique_test_case_ids(test_cases: Sequence[GeneratedTestCaseV1]) -> None:
    test_case_ids = [test_case.id for test_case in test_cases]
    if len(set(test_case_ids)) != len(test_case_ids):
        raise TestNormalizationError("Generated test case IDs must be unique")


def _normalize_title(title: str) -> str:
    return " ".join(normalize("NFKC", title).casefold().split())


def _semantic_payload(test_case: GeneratedTestCaseV1) -> dict[str, object]:
    """Keep behavior-relevant fields and exclude identity and provenance metadata."""

    return {
        "normalization_version": NORMALIZATION_VERSION,
        "kind": test_case.kind.value,
        "request": {
            "method": test_case.request.method.value,
            "path": test_case.request.path,
            "query": sorted(
                [
                    {
                        "name": parameter.name,
                        "value": parameter.value,
                    }
                    for parameter in test_case.request.query
                ],
                key=_canonical_json,
            ),
            "headers": sorted(
                [
                    {
                        "name": header.name.lower(),
                        "value": header.value.strip(),
                    }
                    for header in test_case.request.headers
                ],
                key=_canonical_json,
            ),
            "json_body": test_case.request.json_body,
        },
        "assertions": sorted(
            [
                {
                    "target": assertion.target.value,
                    "selector": _normalized_selector(
                        target=assertion.target,
                        selector=assertion.selector,
                    ),
                    "operator": assertion.operator.value,
                    "expected_value": assertion.expected_value,
                }
                for assertion in test_case.assertions
            ],
            key=_canonical_json,
        ),
    }


def _normalized_selector(
    *,
    target: AssertionTarget,
    selector: str | None,
) -> str | None:
    if target is AssertionTarget.RESPONSE_HEADER and selector is not None:
        return selector.lower()
    return selector


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
