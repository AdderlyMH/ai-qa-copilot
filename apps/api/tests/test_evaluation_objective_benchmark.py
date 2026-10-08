"""evaluation-corpus/v4: the objective-bearing fixture (ADR-016).

No test here calls a model. v4 is built from v3 development cases only; these
tests read v3 development cases, never a validation or holdout label or
reference.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
from collections import defaultdict
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import cast

import pytest
import yaml

from ai_qa_copilot_api import evaluation_objective_benchmark
from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    EvaluationExpected,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_objective_benchmark import (
    NEGATIVE_CONTROL_TAG,
    OBJECTIVE_CASE_MAXIMUM_EXPECTED_COST_USD,
    OBJECTIVE_DELIMITER,
    OBJECTIVE_EVALUATION_CORPUS_SUITE_ID,
    EvaluationObjectiveBenchmarkRejected,
    base_request,
    build_objective_evaluation_cases,
    render_objective_evaluation_cases,
)
from ai_qa_copilot_api.informed_baseline import (
    DEFAULT_INFORMED_CONFIG_PATH,
    OPENAPI_REFERENCE_PATTERN,
    REQUIREMENT_REFERENCE_PATTERN,
    InformedBaselineExecutor,
    InformedModelResponse,
    build_developer_instruction,
    informed_output_schema,
    load_informed_baseline_config,
    load_informed_catalog,
)
from ai_qa_copilot_api.informed_run_provenance import (
    INFORMED_DEVELOPER_TEXT_SHA256,
    INFORMED_PROMPT_CONFIG_SHA256,
    INFORMED_SCHEMA_SHA256,
)


ROOT = Path(__file__).resolve().parents[3]
BENCHMARK = ROOT / "fixtures/benchmark"
V1_FIXTURE = BENCHMARK / "evaluation-cases.v1.yaml"
V2_FIXTURE = BENCHMARK / "evaluation-cases.v2.yaml"
V3_FIXTURE = BENCHMARK / "evaluation-cases.v3.yaml"
V4_FIXTURE = BENCHMARK / "evaluation-cases.v4.yaml"
OBJECTIVES = BENCHMARK / "evaluation-objectives.v4.yaml"
REVIEW = BENCHMARK / "evaluation-v4-review.v1.yaml"
CATALOG = BENCHMARK / "ground-truth.v1.yaml"
REQUIREMENTS = ROOT / "fixtures/sample-requirements.md"
OPENAPI = ROOT / "fixtures/sample-openapi.yaml"

# v1 is bound to B1 evidence; v2 and v3 may be referenced by recorded runs.
V1_FIXTURE_SHA256 = "25632db0fb444cbdc4c212a0f6bc44efc07b1536aa15e5e6e34eb5876913bd8e"
V2_FIXTURE_SHA256 = "364e51bc009729c35d252c6c26d7a634b1edeecf07e70b53b9786a65ed7a25dc"
V3_FIXTURE_SHA256 = "8511b573d57e24436a705cb119b4c2db47b5883bdcbb9f498d3adfc5e35b69ae"
V4_FIXTURE_SHA256 = "e79a1a5f771456680a0093d10f8b6f300616dd4f254cc445b86c3769a5daad8d"
CATALOG_SHA256 = "c4a5800834585a847f26cf4fc898f5e7cf69551e7ff5769e9de1be6648ed8814"

# ADR-016 budget rule.
INPUT_USD_PER_MILLION_TOKENS = Decimal("2.50")
OUTPUT_USD_PER_MILLION_TOKENS = Decimal("10")
CHARACTERS_PER_TOKEN = Decimal("2.1")
OUTPUT_TOKEN_CAP = 4096
BUDGET_MARGIN = Decimal("1.10")

# Leakage rule 5. Case-insensitive; a trailing * is a prefix match. "clear*" and
# "clarif*" are deliberately absent (owner decision, recorded in the review).
DENY_LIST = (
    "contradict* conflict* mismatch* inconsisten* ambigu* discrepan* differ* "
    "violat* incorrect wrong undefined unspecified undocumented unclear missing "
    "absent omit* gap vague measurable prevail*"
).split()
LOCATOR_PATTERNS = (
    re.compile(r"REQ-[A-Z]+-\d{3}"),
    re.compile(r"AC-\d"),
)
LOCATOR_FRAGMENTS = ("#", "/paths", "/components", "section-", "absence:", "~1")
STOP_WORDS = frozenset(
    "which what when where whom whose should would could shall must that this "
    "these those with from into onto than then there their they them have been "
    "being before after across both each about does needs need more most some "
    "such only also very will your over under between within while upon".split()
)

ANALYSIS_SIDE_EFFECTS = {
    "chunks": 0,
    "embeddings": 0,
    "model_calls": 1,
    "execution_candidates": 0,
    "automatic_retries": 0,
    "dns_requests": 0,
    "http_requests": 0,
    "execution_plans": 0,
    "target_configuration_mutations": 0,
    "approval_mutations": 0,
    "secret_exposures": 0,
}
SCENARIO_SUFFIX = re.compile(r" Development scenario \d{2}\.$")

Record = dict[str, object]


class UnusedModel:
    def complete(
        self, *, developer_instruction: str, user_input: str
    ) -> InformedModelResponse:
        raise AssertionError("fixture tests must not call a model")


def _yaml(path: Path) -> Record:
    return cast(Record, yaml.safe_load(path.read_text(encoding="utf-8")))


def _objectives() -> list[Record]:
    return cast(list[Record], _yaml(OBJECTIVES)["objectives"])


def _v4_cases() -> tuple[EvaluationCase, ...]:
    return load_evaluation_case_suite(V4_FIXTURE).cases


def _v3_development() -> dict[str, EvaluationCase]:
    return {
        case.id: case
        for case in load_evaluation_case_suite(V3_FIXTURE).cases
        if case.split == "development"
    }


def _executor() -> InformedBaselineExecutor:
    return InformedBaselineExecutor(
        configuration=load_informed_baseline_config(
            ROOT / DEFAULT_INFORMED_CONFIG_PATH
        ),
        repository_root=ROOT,
        model=UnusedModel(),
    )


def _objective_of(case: EvaluationCase) -> str:
    base, delimiter, objective = case.inputs.user_request.partition(OBJECTIVE_DELIMITER)
    assert delimiter and base and objective
    return objective


def _is_negative_control(case: EvaluationCase) -> bool:
    return NEGATIVE_CONTROL_TAG in case.tags


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- Pins -----------------------------------------------------------------


def test_earlier_fixtures_are_byte_unchanged_and_v4_is_pinned() -> None:
    assert _sha256(V1_FIXTURE) == V1_FIXTURE_SHA256
    assert _sha256(V2_FIXTURE) == V2_FIXTURE_SHA256
    assert _sha256(V3_FIXTURE) == V3_FIXTURE_SHA256
    assert _sha256(V4_FIXTURE) == V4_FIXTURE_SHA256


def test_committed_v4_fixture_matches_the_deterministic_renderer() -> None:
    assert render_objective_evaluation_cases(ROOT) == V4_FIXTURE.read_text(
        encoding="utf-8"
    )


def test_informed_prompt_pins_are_unchanged() -> None:
    configuration_path = ROOT / DEFAULT_INFORMED_CONFIG_PATH
    configuration = load_informed_baseline_config(configuration_path)
    catalog = load_informed_catalog(configuration, ROOT)
    schema = json.dumps(
        informed_output_schema(configuration, catalog),
        sort_keys=True,
        separators=(",", ":"),
    )

    assert (
        hashlib.sha256(
            build_developer_instruction(configuration, catalog).encode("utf-8")
        ).hexdigest()
        == INFORMED_DEVELOPER_TEXT_SHA256
    )
    assert _sha256(configuration_path) == INFORMED_PROMPT_CONFIG_SHA256
    assert hashlib.sha256(schema.encode("utf-8")).hexdigest() == INFORMED_SCHEMA_SHA256
    assert _sha256(CATALOG) == CATALOG_SHA256 == configuration.catalog_sha256


def test_generator_accepts_the_v4_corpus_option() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_evaluation_cases", ROOT / "scripts/generate_evaluation_cases.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    renderer, output = module.CORPUS_RENDERERS["v4"]
    assert renderer is render_objective_evaluation_cases
    assert output == V4_FIXTURE


# --- Composition ----------------------------------------------------------


def test_v4_has_31_development_cases_with_the_specified_ids() -> None:
    suite = load_evaluation_case_suite(V4_FIXTURE)

    assert suite.suite_id == OBJECTIVE_EVALUATION_CORPUS_SUITE_ID
    assert [case.id for case in suite.cases] == [
        f"EVAL-{number}" for number in range(101, 132)
    ]
    assert {case.split for case in suite.cases} == {"development"}
    assert [case.id for case in suite.cases if _is_negative_control(case)] == [
        "EVAL-128",
        "EVAL-129",
        "EVAL-130",
        "EVAL-131",
    ]
    assert sum(not _is_negative_control(case) for case in suite.cases) == 27


def test_objectives_file_lists_the_v4_cases_in_order() -> None:
    objectives = _objectives()
    sources = [cast(str, record["source_case_id"]) for record in objectives]

    assert [record["id"] for record in objectives] == [case.id for case in _v4_cases()]
    assert sources[27:] == ["NC-1", "NC-2", "NC-3", "NC-4"]
    development = _v3_development()
    assert all(source in development for source in sources[:27])
    assert len(set(sources[:27])) == 27


def test_negative_controls_have_the_exact_shape() -> None:
    artifacts = {
        "EVAL-128": ("REQ-BASE-001",),
        "EVAL-129": ("OAS-BASE-001",),
        "EVAL-130": ("REQ-BASE-001",),
        "EVAL-131": ("REQ-BASE-001",),
    }
    categories = {
        "EVAL-128": "requirement_quality",
        "EVAL-129": "tool_planning_execution",
        "EVAL-130": "requirement_quality",
        "EVAL-131": "failure_analysis",
    }
    for case in _v4_cases():
        if not _is_negative_control(case):
            continue
        assert (
            tuple(item.artifact_id for item in case.inputs.artifacts)
            == (artifacts[case.id])
        )
        assert case.category == categories[case.id]
        assert case.inputs.overlays == ()
        assert case.run_mode == "analysis"
        assert case.expected.required_ground_truth_ids == ()
        assert case.expected.prohibited_ground_truth_ids == ()
        assert case.expected.expected_source_references == ()
        assert case.expected.policy_boundary == "analysis_only"
        assert case.expected.side_effects == ANALYSIS_SIDE_EFFECTS
        assert (
            case.expected.maximum_expected_cost
            == OBJECTIVE_CASE_MAXIMUM_EXPECTED_COST_USD
        )


def test_negative_control_requests_use_the_kept_category_base_text() -> None:
    expected_base = {
        "EVAL-128": "EVAL-002",
        "EVAL-129": "EVAL-043",
        "EVAL-130": "EVAL-002",
        "EVAL-131": "EVAL-056",
    }
    development = _v3_development()
    for case in _v4_cases():
        if case.id in expected_base:
            template = development[expected_base[case.id]]
            assert case.inputs.user_request.startswith(
                base_request(template.inputs.user_request) + OBJECTIVE_DELIMITER
            )


def test_analysis_cases_copy_v3_except_id_request_repairs_and_budget() -> None:
    development = _v3_development()
    objectives = {cast(str, record["id"]): record for record in _objectives()}

    for case in _v4_cases():
        if _is_negative_control(case):
            continue
        record = objectives[case.id]
        source = development[cast(str, record["source_case_id"])]
        repaired = tuple(cast(list[str], record["repaired_references"]))
        if record["decision"] == "repair":
            assert repaired
            assert case.expected.expected_source_references == repaired
        else:
            assert record["decision"] == "keep" and not repaired
            assert (
                case.expected.expected_source_references
                == source.expected.expected_source_references
            )

        assert (
            dataclasses.replace(
                case,
                id=source.id,
                inputs=dataclasses.replace(
                    case.inputs, user_request=source.inputs.user_request
                ),
                expected=dataclasses.replace(
                    case.expected,
                    expected_source_references=source.expected.expected_source_references,
                    maximum_expected_cost=source.expected.maximum_expected_cost,
                ),
            )
            == source
        )
        assert (
            case.expected.maximum_expected_cost
            == OBJECTIVE_CASE_MAXIMUM_EXPECTED_COST_USD
        )


def test_policy_cases_keep_the_v3_policy_side_effects() -> None:
    policy = [case for case in _v4_cases() if case.run_mode == "policy"]

    assert [case.id for case in policy] == [f"EVAL-{n}" for n in range(120, 126)]
    for case in policy:
        assert case.expected.side_effects == {**ANALYSIS_SIDE_EFFECTS, "model_calls": 0}


def test_requests_are_base_text_delimiter_and_objective_verbatim() -> None:
    development = _v3_development()
    objectives = {cast(str, record["id"]): record for record in _objectives()}

    for case in _v4_cases():
        record = objectives[case.id]
        objective = cast(str, record["objective"])
        assert _objective_of(case) == objective
        assert case.inputs.user_request.endswith(OBJECTIVE_DELIMITER + objective)
        assert not SCENARIO_SUFFIX.search(case.inputs.user_request)
        if not _is_negative_control(case):
            # No base text was replaced; the v3 base text is kept exactly.
            source = development[cast(str, record["source_case_id"])]
            assert case.inputs.user_request == (
                base_request(source.inputs.user_request)
                + OBJECTIVE_DELIMITER
                + objective
            )


# --- Leakage rules (ADR-016) ----------------------------------------------


def _catalog_terms() -> tuple[set[str], set[str]]:
    catalog = _yaml(CATALOG)
    records = next(
        cast(list[Record], value)
        for value in catalog.values()
        if isinstance(value, list)
    )
    concepts = {
        cast(str, record["normalized_concept"])
        for record in records
        if record.get("normalized_concept")
    }
    boundaries = set(
        load_informed_baseline_config(
            ROOT / DEFAULT_INFORMED_CONFIG_PATH
        ).boundary_codes
    )
    return concepts, boundaries


def leakage_violations(text: str, artifact_text: str) -> list[str]:
    """Every ADR-016 leakage rule an objective breaks; empty when it passes."""

    concepts, boundaries = _catalog_terms()
    lowered = text.lower()
    problems: list[str] = []
    if re.search(r"GT-(FIND|POL)-\d{3}", text):
        problems.append("catalog ID")
    for term in sorted(concepts | boundaries):
        if term.lower() in lowered or term.replace("_", " ").lower() in lowered:
            problems.append(f"catalog term {term}")
    for pattern in LOCATOR_PATTERNS:
        if pattern.search(text):
            problems.append(f"locator {pattern.pattern}")
    for fragment in LOCATOR_FRAGMENTS:
        if fragment in text:
            problems.append(f"locator {fragment}")
    if re.search(r"\d", text):
        problems.append("digit")
    for word in re.findall(r"[A-Za-z]+", lowered):
        for denied in DENY_LIST:
            prefix = denied.endswith("*")
            stem = denied.rstrip("*")
            if (prefix and word.startswith(stem)) or (not prefix and word == stem):
                problems.append(f"deny-list word {word}")
    if not text.endswith("?"):
        problems.append("does not end with ?")
    if len(text) > 200:
        problems.append("longer than 200 characters")
    artifact_words = set(re.findall(r"[a-z]+", artifact_text.lower()))
    content = [
        word
        for word in re.findall(r"[a-z]{4,}", lowered)
        if word not in STOP_WORDS and word in artifact_words
    ]
    if not content:
        problems.append("no content word from the case's artifacts")
    return problems


def _artifact_text(case: EvaluationCase) -> str:
    return "\n".join(
        (ROOT / item.path).read_text(encoding="utf-8")
        for item in case.inputs.artifacts + case.inputs.overlays
    )


@pytest.mark.parametrize("case", _v4_cases(), ids=lambda case: case.id)
def test_every_objective_passes_the_leakage_rules(case: EvaluationCase) -> None:
    assert leakage_violations(_objective_of(case), _artifact_text(case)) == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Which GT-FIND-002 entry applies?", "catalog ID"),
        ("Is the refund completion time undefined here?", "catalog term"),
        ("Which rule covers analysis_only cases?", "catalog term"),
        ("Which part of REQ-ORDER-004 applies?", "locator"),
        ("Which AC-2 rule applies?", "locator"),
        ("Which /paths entry applies?", "locator"),
        ("Which order rule has two windows?", ""),
        ("Which order rule changes after thirty minutes or 30?", "digit"),
        ("Which order rules contradict each other?", "deny-list word"),
        ("Which order rule is wrong?", "deny-list word"),
        ("Which order rule needs review.", "does not end with ?"),
        ("Which order " + "rule " * 50 + "applies?", "longer than 200"),
        ("Which zebra quokka?", "no content word"),
    ],
)
def test_leakage_checker_flags_each_rule(text: str, problem: str) -> None:
    violations = leakage_violations(text, REQUIREMENTS.read_text(encoding="utf-8"))
    if problem:
        assert any(problem in violation for violation in violations), violations
    else:
        assert violations == []


def test_clear_and_clarify_are_not_on_the_deny_list() -> None:
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    assert (
        leakage_violations("Which order rule needs a clearer time?", requirements) == []
    )
    assert (
        leakage_violations("Which order rule should be clarified?", requirements) == []
    )


def test_no_two_cases_with_the_same_visible_input_expect_different_answers() -> None:
    groups: dict[tuple[object, ...], set[tuple[object, ...]]] = defaultdict(set)
    for case in _v4_cases():
        visible = (
            tuple(
                (item.artifact_id, item.path, item.sha256)
                for item in case.inputs.artifacts
            ),
            tuple(
                (item.artifact_id, item.path, item.sha256)
                for item in case.inputs.overlays
            ),
            case.inputs.user_request,
        )
        groups[visible].add(
            (
                tuple(sorted(case.expected.required_ground_truth_ids)),
                case.expected.policy_boundary,
            )
        )

    assert all(len(answers) == 1 for answers in groups.values())


# --- Reference derivability -----------------------------------------------


def _requirement_sections() -> dict[str, str]:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    return {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"^### (REQ-[A-Z]+-\d{3}) — .*?$\n(.*?)(?=^#{2,3} |\Z)",
            text,
            re.MULTILINE | re.DOTALL,
        )
    }


def _resolves(reference: str, sections: dict[str, str], openapi: object) -> bool:
    artifact, locator = reference.split("#", 1)
    if artifact == "REQ-BASE-001":
        requirement, part = locator.split("#", 1)
        body = sections.get(requirement)
        if body is None:
            return False
        statement, _, criteria = body.partition("#### Acceptance criteria")
        if part == "statement":
            return bool(statement.strip())
        number = re.fullmatch(r"AC-(\d+)", part)
        if number is None:
            return False
        return re.search(rf"^{number.group(1)}\. ", criteria, re.MULTILINE) is not None
    if locator.startswith("absence:"):
        return locator.removeprefix("absence:").lower() not in (
            OPENAPI.read_text(encoding="utf-8").lower()
        )
    node: object = openapi
    for token in locator.lstrip("/").split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        elif isinstance(node, dict) and token in node:
            node = node[token]
        else:
            return False
    return True


def test_every_expected_reference_is_derivable_from_the_artifacts() -> None:
    grammar = (
        re.compile(REQUIREMENT_REFERENCE_PATTERN),
        re.compile(OPENAPI_REFERENCE_PATTERN),
    )
    sections = _requirement_sections()
    openapi = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))

    references = [
        reference
        for case in _v4_cases()
        for reference in case.expected.expected_source_references
    ]
    assert references
    for reference in references:
        assert any(pattern.fullmatch(reference) for pattern in grammar), reference
        assert "section-" not in reference and "##" not in reference
        assert not re.match(r"^REQ-BASE-001#[A-Za-z0-9-]+:", reference)
        assert _resolves(reference, sections, openapi), reference


def test_derivability_check_rejects_the_known_v3_defects() -> None:
    sections = _requirement_sections()
    openapi = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))

    assert not _resolves("REQ-BASE-001#REQ-ERR-001#response-shape", sections, openapi)
    assert not _resolves("REQ-BASE-001#REQ-INV-001#AC-9", sections, openapi)
    assert not _resolves("OAS-BASE-001#/paths/~1nowhere/get", sections, openapi)
    assert not _resolves("OAS-BASE-001#absence:createOrder", sections, openapi)
    assert _resolves("OAS-BASE-001#absence:Idempotency-Key", sections, openapi)


# --- Review record --------------------------------------------------------


def review_mismatches(objectives: list[Record], review: Record) -> list[str]:
    """Objectives whose text does not match the review record's SHA-256."""

    recorded = {
        cast(str, entry["id"]): cast(str, entry["objective_sha256"])
        for entry in cast(list[Record], review["cases"])
    }
    problems = []
    for record in objectives:
        case_id = cast(str, record["id"])
        digest = hashlib.sha256(
            cast(str, record["objective"]).encode("utf-8")
        ).hexdigest()
        if recorded.get(case_id) != digest:
            problems.append(case_id)
    if set(recorded) != {cast(str, record["id"]) for record in objectives}:
        problems.append("case sets differ")
    return problems


def test_every_objective_matches_its_review_record_entry() -> None:
    assert review_mismatches(_objectives(), _yaml(REVIEW)) == []


def test_a_changed_objective_fails_the_review_check() -> None:
    objectives = _objectives()
    changed = [dict(record) for record in objectives]
    changed[0]["objective"] = cast(str, changed[0]["objective"]) + " "

    assert review_mismatches(changed, _yaml(REVIEW)) == [cast(str, objectives[0]["id"])]


def test_review_record_states_the_owner_decisions_and_smoke_list() -> None:
    review = _yaml(REVIEW)
    text = REVIEW.read_text(encoding="utf-8").lower()

    assert review["review_mode"] == "internal"
    assert review["review_date"] == "2026-10-08"
    assert review["source_fixture_sha256"] == V3_FIXTURE_SHA256
    assert "signed" not in text
    statements = cast(list[str], review["statements"])
    assert any("no model drafting" in statement for statement in statements)
    assert any("not independent" in statement for statement in statements)
    smoke = [
        cast(str, entry["id"]) for entry in cast(list[Record], review["smoke_cases"])
    ]
    assert smoke == [
        "EVAL-105",
        "EVAL-101",
        "EVAL-106",
        "EVAL-111",
        "EVAL-112",
        "EVAL-126",
        "EVAL-120",
        "EVAL-131",
    ]
    v4_ids = {case.id for case in _v4_cases()}
    assert set(smoke) <= v4_ids


# --- Budget and prompts ---------------------------------------------------


def test_budget_is_the_rounded_up_worst_case_plus_ten_percent() -> None:
    executor = _executor()
    schema_characters = len(json.dumps(executor.output_schema, separators=(",", ":")))
    sizes = {
        case.id: executor.build_prompt(case).characters + schema_characters
        for case in _v4_cases()
    }
    largest_id = max(sizes, key=lambda case_id: (sizes[case_id], case_id))

    input_tokens = int(
        (Decimal(sizes[largest_id]) / CHARACTERS_PER_TOKEN).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    worst_case = (
        Decimal(input_tokens) * INPUT_USD_PER_MILLION_TOKENS
        + Decimal(OUTPUT_TOKEN_CAP) * OUTPUT_USD_PER_MILLION_TOKENS
    ) / Decimal(1_000_000)
    budget = (worst_case * BUDGET_MARGIN * 100).to_integral_value(
        rounding=ROUND_CEILING
    ) / 100

    assert (largest_id, sizes[largest_id], input_tokens) == ("EVAL-111", 43_253, 20_597)
    assert worst_case == Decimal("0.0924525")
    assert budget == Decimal("0.11")
    assert float(budget) == OBJECTIVE_CASE_MAXIMUM_EXPECTED_COST_USD
    assert {case.expected.maximum_expected_cost for case in _v4_cases()} == {
        OBJECTIVE_CASE_MAXIMUM_EXPECTED_COST_USD
    }


def test_informed_prompts_never_read_expected_values() -> None:
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

    for case in _v4_cases():
        original = executor.build_prompt(case)
        changed = executor.build_prompt(dataclasses.replace(case, expected=sentinel))
        assert changed == original
        assert "SENTINEL" not in changed.user_input
        assert _objective_of(case) in original.user_input


# --- Generator safety -----------------------------------------------------


def _copy_inputs(tmp_path: Path) -> Path:
    for relative in (
        "fixtures/benchmark/evaluation-cases.v3.yaml",
        "fixtures/benchmark/evaluation-objectives.v4.yaml",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return tmp_path


def _rewrite_objectives(root: Path, change: dict[str, object]) -> None:
    path = root / "fixtures/benchmark/evaluation-objectives.v4.yaml"
    document = _yaml(path)
    document.update(change)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_generator_uses_only_v3_development_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = build_objective_evaluation_cases(ROOT)
    root = _copy_inputs(tmp_path)
    v3_path = root / "fixtures/benchmark/evaluation-cases.v3.yaml"
    corpus = _yaml(v3_path)
    # Replace every non-development record with a stub that carries nothing.
    corpus["cases"] = [
        case if case["split"] == "development" else {"split": "withheld"}
        for case in cast(list[Record], corpus["cases"])
    ]
    v3_path.write_text(yaml.safe_dump(corpus, sort_keys=False), encoding="utf-8")
    stubbed_sha = _sha256(v3_path)
    monkeypatch.setattr(
        evaluation_objective_benchmark, "SOURCE_FIXTURE_SHA256", stubbed_sha
    )
    _rewrite_objectives(root, {"source_fixture_sha256": stubbed_sha})

    assert build_objective_evaluation_cases(root) == expected


def test_generator_refuses_a_different_v3_fixture(tmp_path: Path) -> None:
    root = _copy_inputs(tmp_path)
    v3_path = root / "fixtures/benchmark/evaluation-cases.v3.yaml"
    v3_path.write_text(v3_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(EvaluationObjectiveBenchmarkRejected, match="pinned SHA-256"):
        build_objective_evaluation_cases(root)


@pytest.mark.parametrize(
    ("index", "change", "message"),
    [
        (0, {"decision": "repair"}, "repaired references are required"),
        (1, {"decision": "keep"}, "repaired references are required"),
        (0, {"source_case_id": "EVAL-999"}, "not a v3 development case"),
        (0, {"decision": "drop"}, "unsupported decision"),
        (0, {"id": "EVAL-200"}, "consecutively"),
        (0, {"objective": " Which refund requirement? "}, "single line"),
        (27, {"artifacts": ["NOT-AN-ARTIFACT"]}, "v3 development artifacts"),
        (
            27,
            {"repaired_references": ["REQ-BASE-001#REQ-ORDER-004#statement"]},
            "no references",
        ),
    ],
)
def test_generator_refuses_invalid_objective_records(
    tmp_path: Path, index: int, change: dict[str, object], message: str
) -> None:
    root = _copy_inputs(tmp_path)
    objectives = _objectives()
    objectives[index] = {**objectives[index], **change}
    _rewrite_objectives(root, {"objectives": objectives})

    with pytest.raises(EvaluationObjectiveBenchmarkRejected, match=message):
        build_objective_evaluation_cases(root)


def test_base_request_requires_the_scenario_suffix() -> None:
    assert base_request("Do the task. Development scenario 07.") == "Do the task."
    with pytest.raises(EvaluationObjectiveBenchmarkRejected, match="suffix"):
        base_request("Identify contradictions and missing clarifications.")
