from __future__ import annotations

from pathlib import Path

import pytest

from ai_qa_copilot_api.evaluation_cases import (
    EVALUATION_CASES_SCHEMA_VERSION,
    SIDE_EFFECT_FIELD_NAMES,
    EvaluationCasesRejected,
    filter_evaluation_cases,
    load_evaluation_case_suite,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"
SHA256 = "a" * 64


def suite_header() -> str:
    return """\
schema_version: evaluation-cases/v1
suite_id: evaluation-development/v1
cases:
"""


def case_block(
    case_id: str = "EVAL-001",
    *,
    split: str = "development",
    tags: str = "[requirements, control]",
    criticality: str = "high",
) -> str:
    return f"""\
  - id: {case_id}
    version: 1
    split: {split}
    category: requirement_quality
    tags: {tags}
    criticality: {criticality}
    run_mode: analysis
    side_effect_schema: side-effects/v1
    inputs:
      artifacts:
        - artifact_id: REQ-BASE-001
          path: fixtures/sample-requirements.md
          sha256: {SHA256}
      overlays: []
      user_request: Identify contradictions and missing clarifications.
    expected:
      required_ground_truth_ids: [GT-FIND-001]
      prohibited_ground_truth_ids: []
      expected_source_references:
        - REQ-BASE-001#REQ-ORDER-004:statement
      policy_boundary: analysis_only
      side_effects:
        chunks: 0
        embeddings: 0
        model_calls: 1
        execution_candidates: 0
        automatic_retries: 0
        dns_requests: 0
        http_requests: 0
        execution_plans: 0
        target_configuration_mutations: 0
        approval_mutations: 0
        secret_exposures: 0
      scorer_version: evaluation-scorer/v1
      maximum_expected_cost: 0
"""


def write_suite(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "evaluation-cases.v1.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_the_committed_evaluation_case_fixture() -> None:
    suite = load_evaluation_case_suite(FIXTURE)

    assert suite.schema_version == EVALUATION_CASES_SCHEMA_VERSION
    assert suite.suite_id == "evaluation-development/v1"
    assert [case.id for case in suite.cases] == ["EVAL-001"]
    assert set(suite.cases[0].expected.side_effects) == SIDE_EFFECT_FIELD_NAMES


def test_rejects_unknown_case_fields(tmp_path: Path) -> None:
    path = write_suite(
        tmp_path,
        suite_header()
        + case_block().replace(
            "    run_mode: analysis\n",
            "    run_mode: analysis\n    unexpected: value\n",
        ),
    )

    with pytest.raises(EvaluationCasesRejected, match="unexpected"):
        load_evaluation_case_suite(path)


def test_rejects_invalid_artifact_hash(tmp_path: Path) -> None:
    path = write_suite(
        tmp_path,
        suite_header() + case_block().replace(SHA256, "not-a-sha256"),
    )

    with pytest.raises(EvaluationCasesRejected, match="64 lowercase hexadecimal"):
        load_evaluation_case_suite(path)


def test_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    path = write_suite(tmp_path, suite_header() + case_block() + case_block())

    with pytest.raises(EvaluationCasesRejected, match="duplicate case IDs"):
        load_evaluation_case_suite(path)


def test_rejects_non_positive_case_versions(tmp_path: Path) -> None:
    path = write_suite(
        tmp_path,
        suite_header() + case_block().replace("    version: 1\n", "    version: 0\n"),
    )

    with pytest.raises(EvaluationCasesRejected, match="greater than zero"):
        load_evaluation_case_suite(path)


def test_rejects_legacy_side_effect_aliases(tmp_path: Path) -> None:
    path = write_suite(
        tmp_path,
        suite_header()
        + case_block().replace(
            "        dns_requests: 0\n",
            "        dns_calls: 0\n",
        ),
    )

    with pytest.raises(EvaluationCasesRejected, match="fields are invalid"):
        load_evaluation_case_suite(path)


def test_rejects_negative_expected_cost(tmp_path: Path) -> None:
    path = write_suite(
        tmp_path,
        suite_header()
        + case_block().replace(
            "      maximum_expected_cost: 0\n",
            "      maximum_expected_cost: -1\n",
        ),
    )

    with pytest.raises(EvaluationCasesRejected, match="finite non-negative"):
        load_evaluation_case_suite(path)


def test_filters_cases_in_fixture_order_and_requires_all_tags(tmp_path: Path) -> None:
    suite = load_evaluation_case_suite(
        write_suite(
            tmp_path,
            suite_header()
            + case_block("EVAL-001", tags="[requirements, control]")
            + case_block(
                "EVAL-002",
                split="holdout",
                tags="[security, control]",
                criticality="critical",
            ),
        )
    )

    selected = filter_evaluation_cases(
        suite.cases,
        tags={"control"},
        criticalities={"high", "critical"},
    )
    assert [case.id for case in selected] == ["EVAL-001", "EVAL-002"]

    holdout_security = filter_evaluation_cases(
        suite.cases,
        splits={"holdout"},
        tags={"security", "control"},
    )
    assert [case.id for case in holdout_security] == ["EVAL-002"]
