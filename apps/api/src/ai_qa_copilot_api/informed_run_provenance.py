"""Content-free provenance for one informed-baseline run; never B1 evidence.

``evaluation-run-provenance/v2`` is the informed-run counterpart of the C1/v1 B0
provenance in ``evaluation_run_provenance.py`` (unchanged). It records identifiers,
hashes, limits, calibration constants and totals only: no prompt text, model
output, or credential. The prompt, config, schema and catalog hashes are pinned
here, so a recorded run proves which exact prompt produced it (ADR-015).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from ai_qa_copilot_api.c1_evaluation_model import load_c1_pricing
from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_informed_benchmark import (
    INFORMED_EVALUATION_CORPUS_SUITE_ID,
)
from ai_qa_copilot_api.evaluation_run_provenance import (
    REVIEW_EVIDENCE_DIRECTORY,
    EvaluationRunProvenanceRejected,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationRunRejected,
    evaluation_run_from_json,
)
from ai_qa_copilot_api.informed_baseline import (
    build_developer_instruction,
    informed_output_schema,
    load_informed_baseline_config,
    load_informed_catalog,
)
from ai_qa_copilot_api.informed_claude_evaluation_model import (
    CLAUDE_INFORMED_CALIBRATION,
    INFORMED_CALL_LEDGER_SCHEMA_VERSION,
)
from ai_qa_copilot_api.model_gateway import (
    C1_CONFIGURATION_VERSION,
    C1_MODEL_ID,
    MODEL_PROVIDER_ANTHROPIC,
)


INFORMED_PROVENANCE_SCHEMA_VERSION: Final = "evaluation-run-provenance/v2"
INFORMED_EVIDENCE_CLASS: Final = "provider-comparison-informed-development"
V3_FIXTURE_RELATIVE_PATH: Final = Path("fixtures/benchmark/evaluation-cases.v3.yaml")

# Pinned as they exist on main for informed-single-prompt/v1. Changing the
# prompt, its config, or the shared schema is a new prompt version: bump the
# version, update these pins, and re-review (ADR-015).
INFORMED_DEVELOPER_TEXT_SHA256: Final = (
    "f024095091f73da5c1762387164754b7b5ff92f3bdd482070fc8313354a378ee"
)
INFORMED_PROMPT_CONFIG_SHA256: Final = (
    "983dfbf64c9bb7ad07206f4124f13852441a832f9b91d3fd2d84270a4a07b478"
)
INFORMED_SCHEMA_SHA256: Final = (
    "9f06849a25161f346f9036b7158cf83a746121637363d8f6414c2f4be68e1067"
)

_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_MICROUSD_PER_USD: Final = Decimal(1_000_000)


@dataclass(frozen=True)
class InformedRunProvenance:
    schema_version: str
    evidence_class: str
    b1_evidence: bool
    provider: str
    model_id: str
    configuration_version: str
    baseline_id: str
    prompt_version: str
    developer_text_sha256: str
    prompt_config_sha256: str
    schema_sha256: str
    catalog_sha256: str
    characters_per_token: str
    calibration_tolerance: str
    max_calibration_ratio: float
    pricing_version: str
    pricing_sha256: str
    suite_id: str
    fixture_sha256: str
    run_report_sha256: str
    git_commit: str
    max_concurrency: int
    max_expected_cost_usd: float
    max_call_cost_microusd: int
    max_run_cost_microusd: int
    ledger_sha256: tuple[str, ...]
    ledger_call_count: int
    ledger_charged_microusd: int

    def as_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True) + "\n"


def build_informed_run_provenance(
    *,
    run_report_path: Path,
    fixture_path: Path,
    pricing_path: Path,
    configuration_path: Path,
    ledger_paths: Sequence[Path],
    repository_root: Path,
    git_commit: str,
    max_call_cost_microusd: int,
    max_run_cost_microusd: int,
) -> InformedRunProvenance:
    """Validate an informed run's artifacts and record their content-free provenance."""

    if not _COMMIT_PATTERN.fullmatch(git_commit):
        raise EvaluationRunProvenanceRejected(
            "git_commit must be a 40-character lowercase hexadecimal SHA"
        )
    for label, value in (
        ("max_call_cost_microusd", max_call_cost_microusd),
        ("max_run_cost_microusd", max_run_cost_microusd),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise EvaluationRunProvenanceRejected(f"{label} must be positive")

    fixture_sha256 = _sha256_file(fixture_path, "Fixture")
    suite = load_evaluation_case_suite(fixture_path)
    if suite.suite_id != INFORMED_EVALUATION_CORPUS_SUITE_ID:
        raise EvaluationRunProvenanceRejected(
            f"Informed runs must use the {INFORMED_EVALUATION_CORPUS_SUITE_ID} corpus"
        )
    committed = repository_root / V3_FIXTURE_RELATIVE_PATH
    if fixture_sha256 != _sha256_file(committed, "Committed v3 fixture"):
        raise EvaluationRunProvenanceRejected(
            "Fixture does not match the committed evaluation-corpus/v3 fixture"
        )
    case_budget_microusd = int(
        max(Decimal(str(case.expected.maximum_expected_cost)) for case in suite.cases)
        * _MICROUSD_PER_USD
    )
    if max_call_cost_microusd > case_budget_microusd:
        raise EvaluationRunProvenanceRejected(
            "The per-call limit exceeds the v3 per-case budget"
        )
    if max_call_cost_microusd > max_run_cost_microusd:
        raise EvaluationRunProvenanceRejected(
            "The per-call limit cannot exceed the run limit"
        )

    run = evaluation_run_from_json(_read(run_report_path, "Run report"))
    if run.suite_id != INFORMED_EVALUATION_CORPUS_SUITE_ID:
        raise EvaluationRunProvenanceRejected(
            f"Informed runs must use the {INFORMED_EVALUATION_CORPUS_SUITE_ID} corpus"
        )
    if run.fixture_sha256 != fixture_sha256:
        raise EvaluationRunProvenanceRejected(
            "Run report fixture hash does not match the supplied fixture"
        )
    if run.max_concurrency != 1:
        raise EvaluationRunProvenanceRejected("Informed runs require max_concurrency 1")
    if run.max_expected_cost is None:
        raise EvaluationRunProvenanceRejected(
            "Informed runs require an explicit max_expected_cost"
        )

    hashes = _prompt_hashes(configuration_path, repository_root)
    pricing = load_c1_pricing(pricing_path)
    if not ledger_paths:
        raise EvaluationRunProvenanceRejected(
            "At least one informed call ledger is required"
        )

    calibration = CLAUDE_INFORMED_CALIBRATION
    call_count = 0
    charged_microusd = 0
    max_ratio = 0.0
    for ledger_path in ledger_paths:
        for record in _ledger_records(ledger_path):
            if (
                record.get("schema_version") != INFORMED_CALL_LEDGER_SCHEMA_VERSION
                or record.get("provider") != MODEL_PROVIDER_ANTHROPIC
                or record.get("model_id") != C1_MODEL_ID
                or record.get("configuration_version") != C1_CONFIGURATION_VERSION
                or record.get("prompt_version") != hashes.prompt_version
                or record.get("pricing_version") != pricing.pricing_version
                or record.get("characters_per_token")
                != str(calibration.characters_per_token)
                or record.get("tolerance") != str(calibration.tolerance)
            ):
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} does not match informed provenance"
                )
            if (
                record.get("outcome") != "succeeded"
                or record.get("failure") is not None
            ):
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} contains a failed call"
                )
            if (
                record.get("max_call_microusd") != max_call_cost_microusd
                or record.get("max_run_microusd") != max_run_cost_microusd
            ):
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} limits differ from the declared limits"
                )
            charged = record.get("charged_microusd")
            ratio = record.get("calibration_ratio")
            if (
                isinstance(charged, bool)
                or not isinstance(charged, int)
                or charged < 0
                or isinstance(ratio, bool)
                or not isinstance(ratio, int | float)
                or ratio < 0
            ):
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} has an invalid charge or ratio"
                )
            call_count += 1
            charged_microusd += charged
            max_ratio = max(max_ratio, float(ratio))

    if call_count != len(run.selected_case_ids):
        raise EvaluationRunProvenanceRejected(
            "Ledger call count differs from the run report's selected cases"
        )

    return InformedRunProvenance(
        schema_version=INFORMED_PROVENANCE_SCHEMA_VERSION,
        evidence_class=INFORMED_EVIDENCE_CLASS,
        b1_evidence=False,
        provider=MODEL_PROVIDER_ANTHROPIC,
        model_id=C1_MODEL_ID,
        configuration_version=C1_CONFIGURATION_VERSION,
        baseline_id=hashes.baseline_id,
        prompt_version=hashes.prompt_version,
        developer_text_sha256=hashes.developer_text,
        prompt_config_sha256=hashes.prompt_config,
        schema_sha256=hashes.schema,
        catalog_sha256=hashes.catalog,
        characters_per_token=str(calibration.characters_per_token),
        calibration_tolerance=str(calibration.tolerance),
        max_calibration_ratio=max_ratio,
        pricing_version=pricing.pricing_version,
        pricing_sha256=_sha256_file(pricing_path, "Pricing input"),
        suite_id=run.suite_id,
        fixture_sha256=fixture_sha256,
        run_report_sha256=_sha256_file(run_report_path, "Run report"),
        git_commit=git_commit,
        max_concurrency=run.max_concurrency,
        max_expected_cost_usd=float(run.max_expected_cost),
        max_call_cost_microusd=max_call_cost_microusd,
        max_run_cost_microusd=max_run_cost_microusd,
        ledger_sha256=tuple(_sha256_file(path, "Call ledger") for path in ledger_paths),
        ledger_call_count=call_count,
        ledger_charged_microusd=charged_microusd,
    )


def write_informed_run_provenance(
    provenance: InformedRunProvenance,
    *,
    repository_root: Path,
    run_report_path: Path,
    output_path: Path,
) -> None:
    """Write provenance next to the run report, never under review evidence."""

    output = output_path.resolve()
    if output.parent != run_report_path.resolve().parent:
        raise EvaluationRunProvenanceRejected(
            "Provenance must be written next to the run report"
        )
    reviews = (repository_root / REVIEW_EVIDENCE_DIRECTORY).resolve()
    if output == reviews or reviews in output.parents:
        raise EvaluationRunProvenanceRejected(
            "Informed provenance must never be written under evaluation/reviews"
        )
    try:
        with output.open("x", encoding="utf-8", newline="\n") as file:
            file.write(provenance.as_json())
    except FileExistsError as error:
        raise EvaluationRunProvenanceRejected(
            "Provenance output already exists; evidence is never replaced"
        ) from error


@dataclass(frozen=True)
class _PromptHashes:
    baseline_id: str
    prompt_version: str
    developer_text: str
    prompt_config: str
    schema: str
    catalog: str


def _prompt_hashes(configuration_path: Path, repository_root: Path) -> _PromptHashes:
    """Hash the current prompt inputs and require them to equal the pins."""

    try:
        configuration = load_informed_baseline_config(configuration_path)
        catalog = load_informed_catalog(configuration, repository_root)
    except EvaluationRunRejected as error:
        raise EvaluationRunProvenanceRejected(
            f"Informed prompt inputs are invalid: {error}"
        ) from error

    developer_text = hashlib.sha256(
        build_developer_instruction(configuration, catalog).encode("utf-8")
    ).hexdigest()
    schema = hashlib.sha256(
        json.dumps(
            informed_output_schema(configuration, catalog),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    prompt_config = _sha256_file(configuration_path, "Informed configuration")

    for label, actual, pinned in (
        ("developer text", developer_text, INFORMED_DEVELOPER_TEXT_SHA256),
        ("prompt configuration", prompt_config, INFORMED_PROMPT_CONFIG_SHA256),
        ("output schema", schema, INFORMED_SCHEMA_SHA256),
    ):
        if actual != pinned:
            raise EvaluationRunProvenanceRejected(
                f"The informed {label} hash does not match the pinned value"
            )
    return _PromptHashes(
        baseline_id=configuration.baseline_id,
        prompt_version=configuration.prompt_version,
        developer_text=developer_text,
        prompt_config=prompt_config,
        schema=schema,
        catalog=configuration.catalog_sha256,
    )


def _ledger_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(
        _read(path, "Call ledger").splitlines(), start=1
    ):
        try:
            value = cast(object, json.loads(line))
        except json.JSONDecodeError as error:
            raise EvaluationRunProvenanceRejected(
                f"Ledger {path.name} line {line_number} is not JSON"
            ) from error
        if not isinstance(value, dict):
            raise EvaluationRunProvenanceRejected(
                f"Ledger {path.name} line {line_number} is not an object"
            )
        records.append(cast(dict[str, object], value))
    return records


def _read(path: Path, label: str) -> str:
    if not path.is_file():
        raise EvaluationRunProvenanceRejected(f"{label} does not exist: {path.name}")
    return path.read_text(encoding="utf-8")


def _sha256_file(path: Path, label: str) -> str:
    if not path.is_file():
        raise EvaluationRunProvenanceRejected(f"{label} does not exist: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()
