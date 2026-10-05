from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path

import pytest
import yaml

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    EvaluationCaseSuite,
    EvaluationExpected,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.informed_baseline import (
    DEFAULT_INFORMED_CONFIG_PATH,
    OPENAPI_REFERENCE_PATTERN,
    REQUIREMENT_REFERENCE_PATTERN,
    SCHEMA_REFERENCE_PATTERN,
    InformedBaselineConfig,
    InformedBaselineExecutor,
    InformedBaselineRejected,
    InformedModelResponse,
    build_developer_instruction,
    informed_output_schema,
    load_informed_baseline_config,
    load_informed_catalog,
    render_catalog,
)
from ai_qa_copilot_api.naive_baseline import B0_SIDE_EFFECTS


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v2.yaml"
CONFIG_PATH = ROOT / DEFAULT_INFORMED_CONFIG_PATH
CATALOG_PATH = ROOT / "fixtures/benchmark/ground-truth.v1.yaml"

# SHA-256 of the static developer text. A prompt change must bump the prompt
# version, update this pin, and be reviewed (ADR-015).
DEVELOPER_TEXT_SHA256 = (
    "f024095091f73da5c1762387164754b7b5ff92f3bdd482070fc8313354a378ee"
)

ALLOWED_SCHEMA_KEYWORDS = {
    "type",
    "properties",
    "items",
    "enum",
    "pattern",
    "required",
    "additionalProperties",
}


class RecordingModel:
    def __init__(self, content: str, cost: float = 0.01) -> None:
        self.content = content
        self.cost = cost
        self.calls: list[tuple[str, str]] = []

    def complete(
        self, *, developer_instruction: str, user_input: str
    ) -> InformedModelResponse:
        self.calls.append((developer_instruction, user_input))
        return InformedModelResponse(content=self.content, cost=self.cost)


def _suite() -> EvaluationCaseSuite:
    return load_evaluation_case_suite(FIXTURE)


def _executor(model: RecordingModel | None = None) -> InformedBaselineExecutor:
    return InformedBaselineExecutor(
        configuration=load_informed_baseline_config(CONFIG_PATH),
        repository_root=ROOT,
        model=model or RecordingModel("{}"),
    )


def _case(case_id: str) -> EvaluationCase:
    return next(case for case in _suite().cases if case.id == case_id)


def _normalized(reference: str) -> str:
    """Hash-form view of a v1/v2 reference, used to compare with the grammar."""

    reference = reference.replace("##", "#")
    reference = reference.replace("OAS-BASE-001#OAS-BASE-001#", "OAS-BASE-001#")
    return re.sub(r"^(REQ-BASE-001#[A-Za-z0-9-]+):", r"\1#", reference)


def _good_output(**overrides: object) -> str:
    output: dict[str, object] = {
        "boundary": "analysis_only",
        "ground_truth_ids": ["GT-FIND-001"],
        "source_references": ["REQ-BASE-001#REQ-ORDER-004#statement"],
    }
    output.update(overrides)
    return json.dumps(output)


def test_committed_configuration_loads_and_pins_the_catalog() -> None:
    configuration = load_informed_baseline_config(CONFIG_PATH)

    assert configuration.baseline_id == "INFORMED"
    assert configuration.prompt_version == "informed-single-prompt/v1"
    assert configuration.side_effects == B0_SIDE_EFFECTS
    assert (
        hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
        == configuration.catalog_sha256
    )
    assert load_informed_catalog(configuration, ROOT).catalog_id


def test_boundary_codes_cover_every_fixture_boundary() -> None:
    configuration = load_informed_baseline_config(CONFIG_PATH)

    fixture_boundaries = {case.expected.policy_boundary for case in _suite().cases}

    assert set(configuration.boundary_codes) == fixture_boundaries
    assert len(configuration.boundary_codes) == 4


def test_developer_text_is_static_and_pinned() -> None:
    first = _executor().build_prompt(_case("EVAL-001"))
    other = _executor().build_prompt(_case("EVAL-025"))

    assert first.developer_instruction == other.developer_instruction
    assert (
        hashlib.sha256(first.developer_instruction.encode("utf-8")).hexdigest()
        == DEVELOPER_TEXT_SHA256
    )


def test_developer_text_discloses_codes_grammar_and_catalog_ids_only() -> None:
    configuration = load_informed_baseline_config(CONFIG_PATH)
    text = _executor().developer_instruction
    catalog_yaml = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
    records = catalog_yaml["findings"] + catalog_yaml["policies"]

    for code in configuration.boundary_codes:
        assert code in text
    for record in records:
        assert record["id"] in text
    assert len(records) == 19

    # Excluded catalog fields must not leak into the prompt.
    for record in records:
        for locator in record["source_locators"]:
            assert locator not in text
        for element in record.get("required_explanation_elements", []):
            assert element not in text
        for conclusion in record.get("prohibited_conclusions", []):
            assert conclusion not in text
    assert "severity" not in text.lower()
    assert "source_locators" not in text


def test_catalog_has_one_line_per_entry_from_catalog_fields() -> None:
    configuration = load_informed_baseline_config(CONFIG_PATH)
    lines = render_catalog(load_informed_catalog(configuration, ROOT)).splitlines()

    assert len(lines) == 19
    assert lines[0] == (
        "- GT-FIND-001 | finding | contradiction | "
        "conflicting_customer_cancellation_window | artifacts: REQ-BASE-001"
    )
    assert lines[-1] == (
        "- GT-POL-003 | policy | operation_server_metadata_cannot_create_target | "
        "artifacts: OAS-BASE-001"
    )


def test_reference_examples_are_expected_by_no_case() -> None:
    configuration = load_informed_baseline_config(CONFIG_PATH)
    expected = {
        _normalized(reference)
        for case in _suite().cases
        for reference in case.expected.expected_source_references
    }
    expected_locators = {reference.split("#", 1)[1] for reference in expected}

    assert configuration.reference_examples
    for example in configuration.reference_examples:
        assert example not in expected
        assert example.split("#", 1)[1] not in expected_locators
        assert example in _executor().developer_instruction


def test_reference_examples_resolve_in_the_source_artifacts() -> None:
    configuration = load_informed_baseline_config(CONFIG_PATH)
    requirements = (ROOT / "fixtures/sample-requirements.md").read_text(
        encoding="utf-8"
    )
    openapi_text = (ROOT / "fixtures/sample-openapi.yaml").read_text(encoding="utf-8")
    openapi = yaml.safe_load(openapi_text)

    for example in configuration.reference_examples:
        artifact, locator = example.split("#", 1)
        if artifact == "REQ-BASE-001":
            assert f"### {locator.split('#')[0]} " in requirements
        elif locator.startswith("absence:"):
            assert locator.removeprefix("absence:") not in openapi_text
        else:
            node: object = openapi
            for part in locator.lstrip("/").split("/"):
                assert isinstance(node, dict)
                node = node[part.replace("~1", "/").replace("~0", "~")]
            assert node


def test_prompt_is_byte_identical_when_expected_values_are_sentinels() -> None:
    executor = _executor()
    sentinel = EvaluationExpected(
        required_ground_truth_ids=("SENTINEL-GT-ID",),
        prohibited_ground_truth_ids=("SENTINEL-PROHIBITED-ID",),
        expected_source_references=("SENTINEL-ARTIFACT#SENTINEL-REFERENCE",),
        policy_boundary="SENTINEL_BOUNDARY",
        side_effects={"model_calls": 999},
        scorer_version="SENTINEL-SCORER",
        maximum_expected_cost=999,
    )

    for case in _suite().cases:
        changed = dataclasses.replace(case, expected=sentinel)
        original_prompt = executor.build_prompt(case)
        changed_prompt = executor.build_prompt(changed)

        assert changed_prompt == original_prompt
        assert "SENTINEL" not in changed_prompt.developer_instruction
        assert "SENTINEL" not in changed_prompt.user_input


def test_user_message_is_the_request_then_artifacts_in_b0_delimiters() -> None:
    case = _case("EVAL-025")
    prompt = _executor().build_prompt(case)

    assert prompt.user_input.startswith(f"User request:\n{case.inputs.user_request}")
    assert (
        "Source artifacts:\n--- artifact: REQ-BASE-001 ---\npath: " in prompt.user_input
    )
    assert "--- end artifact: OAS-BASE-001 ---" in prompt.user_input
    assert case.id not in prompt.user_input
    assert "GT-FIND" not in prompt.user_input


def test_execute_makes_exactly_one_call_and_returns_the_validated_observation() -> None:
    model = RecordingModel(_good_output(), cost=0.02)
    observation = _executor(model).execute(_case("EVAL-001"))

    assert len(model.calls) == 1
    assert observation.boundary == "analysis_only"
    assert observation.ground_truth_ids == ("GT-FIND-001",)
    assert observation.source_references == ("REQ-BASE-001#REQ-ORDER-004#statement",)
    assert observation.side_effects == B0_SIDE_EFFECTS
    assert observation.cost == 0.02


def test_oversized_prompt_is_rejected_before_any_model_call() -> None:
    configuration = dataclasses.replace(
        load_informed_baseline_config(CONFIG_PATH), maximum_prompt_characters=1_000
    )
    model = RecordingModel("{}")
    executor = InformedBaselineExecutor(
        configuration=configuration, repository_root=ROOT, model=model
    )

    with pytest.raises(InformedBaselineRejected, match="maximum_prompt_characters"):
        executor.execute(_case("EVAL-001"))

    assert model.calls == []


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not json", "JSON object"),
        ("[]", "mapping"),
        (json.dumps({"boundary": "analysis_only"}), "exactly boundary"),
        (_good_output(boundary="model_analysis"), "boundary is not allowed"),
        (_good_output(ground_truth_ids=["GT-FIND-099"]), "unknown catalog ID"),
        (_good_output(ground_truth_ids=["GT-FIND-001", "GT-FIND-001"]), "duplicates"),
        (
            _good_output(source_references=["REQ-BASE-001#REQ-ORDER-004:statement"]),
            "outside the grammar",
        ),
        (
            _good_output(source_references=["OAS-BASE-001##/paths/~1orders/get"]),
            "outside the grammar",
        ),
        (
            _good_output(
                source_references=["OAS-BASE-001#OAS-BASE-001#absence:X-Correlation-ID"]
            ),
            "outside the grammar",
        ),
        (_good_output(source_references=["REQ-BASE-001#statement"]), "grammar"),
    ],
)
def test_invalid_model_output_is_rejected_after_its_single_call(
    content: str, message: str
) -> None:
    model = RecordingModel(content)

    with pytest.raises(InformedBaselineRejected, match=message):
        _executor(model).execute(_case("EVAL-001"))

    assert len(model.calls) == 1


def test_empty_selections_are_valid() -> None:
    observation = _executor(
        RecordingModel(_good_output(ground_truth_ids=[], source_references=[]))
    ).execute(_case("EVAL-001"))

    assert observation.ground_truth_ids == ()
    assert observation.source_references == ()


def test_output_schema_is_provider_neutral_and_uses_only_shared_keywords() -> None:
    configuration = load_informed_baseline_config(CONFIG_PATH)
    catalog = load_informed_catalog(configuration, ROOT)
    schema = informed_output_schema(configuration, catalog)
    properties = schema["properties"]
    assert isinstance(properties, dict)

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["boundary", "ground_truth_ids", "source_references"]
    assert properties["boundary"]["enum"] == list(configuration.boundary_codes)
    assert properties["ground_truth_ids"]["items"]["enum"] == [
        record.id for record in catalog.records
    ]
    assert properties["source_references"]["items"]["pattern"] == (
        SCHEMA_REFERENCE_PATTERN
    )

    def keywords(node: object) -> set[str]:
        if isinstance(node, dict):
            found = set(node) - {"boundary", "ground_truth_ids", "source_references"}
            return found.union(*(keywords(value) for value in node.values()))
        return set()

    # Keyword names appear only at schema levels; property names are filtered above.
    assert keywords(schema) <= ALLOWED_SCHEMA_KEYWORDS
    assert informed_output_schema(configuration, catalog) == schema
    assert _executor().output_schema == schema


def test_every_fixture_reference_fits_the_grammar_and_the_schema_pattern() -> None:
    requirement = re.compile(REQUIREMENT_REFERENCE_PATTERN)
    openapi = re.compile(OPENAPI_REFERENCE_PATTERN)
    shared = re.compile(SCHEMA_REFERENCE_PATTERN)

    for case in _suite().cases:
        for reference in case.expected.expected_source_references:
            normalized = _normalized(reference)
            assert requirement.fullmatch(normalized) or openapi.fullmatch(normalized)
            assert shared.fullmatch(normalized)


def test_configuration_rejects_unsafe_variants(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    def write(changes: dict[str, object]) -> Path:
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump({**raw, **changes}), encoding="utf-8")
        return path

    with pytest.raises(InformedBaselineRejected, match="one model call"):
        load_informed_baseline_config(
            write({"side_effects": {**raw["side_effects"], "chunks": 1}})
        )
    with pytest.raises(InformedBaselineRejected, match="prompt version"):
        load_informed_baseline_config(write({"prompt_version": "other/v1"}))
    with pytest.raises(InformedBaselineRejected, match="analysis_only"):
        load_informed_baseline_config(write({"boundary_codes": ["other"]}))
    with pytest.raises(InformedBaselineRejected, match="grammar"):
        load_informed_baseline_config(
            write({"reference_examples": ["REQ-BASE-001#REQ-PAY-001:AC-2"]})
        )
    with pytest.raises(InformedBaselineRejected, match="fields must be exactly"):
        load_informed_baseline_config(write({"extra": 1}))

    wrong_catalog = load_informed_baseline_config(write({"catalog_sha256": "0" * 64}))
    with pytest.raises(InformedBaselineRejected, match="pinned catalog_sha256"):
        load_informed_catalog(wrong_catalog, ROOT)


def test_developer_text_builder_is_deterministic() -> None:
    configuration: InformedBaselineConfig = load_informed_baseline_config(CONFIG_PATH)
    catalog = load_informed_catalog(configuration, ROOT)

    assert build_developer_instruction(configuration, catalog) == (
        build_developer_instruction(configuration, catalog)
    )
