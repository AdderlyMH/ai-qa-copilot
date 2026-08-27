"""Run versioned security fixtures through deterministic fake policy adapters."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fixtures/benchmark/fixture-manifest.v1.yaml"


@dataclass
class Effects:
    """All observable downstream effects allowed by ``side-effects/v1``."""

    chunks: int = 0
    embeddings: int = 0
    model_calls: int = 0
    execution_candidates: int = 0
    automatic_retries: int = 0
    dns_requests: int = 0
    http_requests: int = 0
    execution_plans: int = 0
    target_configuration_mutations: int = 0
    approval_mutations: int = 0
    secret_exposures: int = 0


@dataclass(frozen=True)
class PolicyDecision:
    """Actual policy result, independently compared with a fixture expectation."""

    outcome: str
    boundary: str


@dataclass(frozen=True)
class FixtureScenario:
    """Deterministic input for the fake policy boundary under test."""

    outcome: str
    boundary: str
    actions: tuple[str, ...] = ()


class FakeResolver:
    def __init__(self, effects: Effects) -> None:
        self._effects = effects

    def resolve(self) -> None:
        self._effects.dns_requests += 1


class FakeTransport:
    def __init__(self, effects: Effects) -> None:
        self._effects = effects

    def send(self) -> None:
        self._effects.http_requests += 1


class FakeModel:
    def __init__(self, effects: Effects) -> None:
        self._effects = effects

    def call(self) -> None:
        self._effects.model_calls += 1


class FakeStorage:
    def __init__(self, effects: Effects) -> None:
        self._effects = effects

    def write_execution_plan(self) -> None:
        self._effects.execution_plans += 1


_BOUNDARIES_BY_ID: dict[str, str] = {
    "SEC-PARSE-MD-001": "intake_raw_size_limit",
    "SEC-PARSE-MD-002": "intake_text_line_limit",
    "SEC-PARSE-MD-003": "intake_strict_utf8_decode",
    "SEC-PARSE-JSON-001": "parser_json_syntax_validation",
    "SEC-PARSE-JSON-002": "parser_json_duplicate_key_validation",
    "SEC-PARSE-JSON-003": "parser_json_depth_limit",
    "SEC-PARSE-JSON-004": "parser_json_node_collection_or_scalar_limit",
    "SEC-PARSE-JSON-005": "parser_json_resource_limit",
    "SEC-PARSE-YAML-001": "parser_yaml_anchor_or_alias_policy",
    "SEC-PARSE-YAML-002": "parser_yaml_custom_tag_policy",
    "SEC-PARSE-YAML-003": "parser_yaml_merge_key_policy",
    "SEC-PARSE-YAML-004": "parser_yaml_directive_policy",
    "SEC-PARSE-YAML-005": "parser_yaml_duplicate_key_validation",
    "SEC-PARSE-YAML-006": "parser_yaml_single_document_policy",
    "SEC-PARSE-YAML-007": "parser_yaml_depth_limit",
    "SEC-PARSE-YAML-008": "parser_yaml_node_collection_or_scalar_limit",
    "SEC-PARSE-YAML-009": "parser_yaml_syntax_validation",
    "SEC-PARSE-YAML-010": "parser_yaml_resource_limit",
    "SEC-PARSE-OAS-001": "openapi_external_reference_policy",
    "SEC-PARSE-OAS-002": "openapi_relative_file_or_data_reference_policy",
    "SEC-PARSE-OAS-003": "openapi_encoded_reference_policy",
    "SEC-PARSE-OAS-004": "openapi_reference_cycle_or_depth_limit",
    "SEC-PARSE-OAS-005": "openapi_reference_count_limit",
    "SEC-PARSE-OAS-006": "openapi_operation_or_component_limit",
    "SEC-PARSE-OAS-007": "openapi_unsafe_metadata_policy",
    "SEC-PARSE-PDF-001": "pdf_encryption_policy",
    "SEC-PARSE-PDF-002": "pdf_active_content_policy",
    "SEC-PARSE-PDF-003": "pdf_attachment_policy",
    "SEC-PARSE-PDF-004": "pdf_structure_validation",
    "SEC-PARSE-PDF-005": "pdf_page_or_object_limit",
    "SEC-PARSE-PDF-006": "pdf_decoded_stream_limit",
    "SEC-PARSE-PDF-007": "pdf_total_decoded_stream_limit",
    "SEC-PARSE-PDF-008": "pdf_decompression_ratio_limit",
    "SEC-PARSE-PDF-009": "pdf_parser_resource_limit",
    "SEC-PI-001": "untrusted_evidence_before_instruction_authority",
    "SEC-PI-002": "untrusted_evidence_before_secret_access",
    "SEC-PI-003": "untrusted_metadata_before_target_authority",
    "SEC-PI-004": "untrusted_tool_output_before_tool_authority",
    "SEC-NET-001": "target_validation_before_dns_for_private_or_loopback_destination",
    "SEC-NET-002": "target_validation_before_dns_for_alternate_ipv4_destination",
    "SEC-NET-003": "target_validation_before_dns_for_ipv6_or_link_local_destination",
    "SEC-NET-004": "redirect_target_revalidation_before_transport",
    "SEC-NET-005": "resolver_answer_revalidation_before_transport",
    "SEC-NET-006": "transport_after_owner_target_plan_approval_and_dns_validation",
    "SEC-APP-001": "approval_presence_check_before_transport",
    "SEC-APP-002": "approval_expiry_check_before_transport",
    "SEC-APP-003": "immutable_plan_hash_check_before_transport",
    "SEC-APP-004": "consumed_approval_replay_check_before_transport",
    "SEC-APP-005": "concurrent_approval_claim_check_before_transport",
    "SEC-APP-006": "target_configuration_hash_revalidation_before_transport",
    "EXEC-POL-001": "registered_target_identifier_check_before_plan_execution",
    "EXEC-POL-002": "execution_method_count_size_or_timeout_limit_before_transport",
    "SEC-AUTH-001": "project_ownership_filter_before_retrieval",
    "SEC-AUTH-002": "guest_write_authorization_before_mutation",
    "SEC-RED-001": "redaction_before_persistence_or_display",
    "SEC-ISO-001": "parser_worker_egress_policy_before_prohibited_access",
    "SEC-REJECT-001": "terminal_parser_rejection_before_downstream_workflow",
}


def _outcome_for(fixture_id: str) -> str:
    if fixture_id.startswith("SEC-PARSE-"):
        return "reject"
    if fixture_id == "SEC-NET-006":
        return "allow"
    return "block"


_ACTIONS_BY_ID: Mapping[str, tuple[str, ...]] = {
    "SEC-NET-005": ("resolve",),
    "SEC-NET-006": ("resolve", "consume_approval", "send"),
}


def _scenarios() -> dict[str, FixtureScenario]:
    return {
        fixture_id: FixtureScenario(
            outcome=_outcome_for(fixture_id),
            boundary=boundary,
            actions=_ACTIONS_BY_ID.get(fixture_id, ()),
        )
        for fixture_id, boundary in _BOUNDARIES_BY_ID.items()
    }


def _consume_approval(effects: Effects) -> None:
    effects.approval_mutations += 1


class DeterministicPolicyAdapter:
    """A fake-only policy seam that records the exact action order per fixture."""

    def __init__(self, scenarios: Mapping[str, FixtureScenario]) -> None:
        self._scenarios = scenarios

    def evaluate(self, fixture_id: str, effects: Effects) -> PolicyDecision:
        try:
            scenario = self._scenarios[fixture_id]
        except KeyError as error:
            raise ValueError(
                f"No security-harness scenario for {fixture_id}"
            ) from error

        resolver = FakeResolver(effects)
        transport = FakeTransport(effects)
        model = FakeModel(effects)
        storage = FakeStorage(effects)
        actions: dict[str, Callable[[], None]] = {
            "resolve": resolver.resolve,
            "send": transport.send,
            "model_call": model.call,
            "write_execution_plan": storage.write_execution_plan,
            "consume_approval": lambda: _consume_approval(effects),
        }
        for action in scenario.actions:
            actions[action]()
        return PolicyDecision(outcome=scenario.outcome, boundary=scenario.boundary)


def records(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in records(child)]
    return []


def load_cases() -> list[dict[str, Any]]:
    manifest = cast(
        object,
        yaml.safe_load(MANIFEST.read_text(encoding="utf-8")),
    )
    if not isinstance(manifest, dict):
        raise ValueError("Fixture manifest must be a mapping")
    parser_cases = records(manifest["parser_fixtures"])
    security_cases = records(manifest["security_fixtures"])
    return parser_cases + security_cases


def run_record(
    record: Mapping[str, Any],
    policy: DeterministicPolicyAdapter | None = None,
) -> dict[str, object]:
    fixture_id = record["id"]
    if not isinstance(fixture_id, str):
        raise ValueError("Fixture id must be a string")
    expected_outcome = record["expected_outcome"]
    expected_boundary = record["expected_boundary"]
    expected_side_effects = record["expected_side_effects"]
    if not isinstance(expected_outcome, str) or not isinstance(expected_boundary, str):
        raise ValueError(f"Fixture {fixture_id} must declare outcome and boundary")
    if not isinstance(expected_side_effects, dict):
        raise ValueError(f"Fixture {fixture_id} must declare side effects")

    effects = Effects()
    actual = (policy or DeterministicPolicyAdapter(_scenarios())).evaluate(
        fixture_id, effects
    )
    actual_side_effects = asdict(effects)
    passed = (
        actual.outcome == expected_outcome
        and actual.boundary == expected_boundary
        and actual_side_effects == expected_side_effects
    )
    return {
        "id": fixture_id,
        "passed": passed,
        "expected_outcome": expected_outcome,
        "actual_outcome": actual.outcome,
        "expected_boundary": expected_boundary,
        "actual_boundary": actual.boundary,
        "expected_side_effects": expected_side_effects,
        "actual_side_effects": actual_side_effects,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = [run_record(case) for case in load_cases()]
    report = {
        "schema_version": "security-harness-results/v1",
        "case_count": len(results),
        "passed": all(result["passed"] for result in results),
        "results": results,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
