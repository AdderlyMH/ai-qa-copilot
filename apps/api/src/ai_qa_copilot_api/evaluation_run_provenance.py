"""Content-free provenance for one C1/v1 evaluation run; never B1 evidence.

The ``evaluation-run/v1`` report has a fixed field set, so provider and
configuration identity is recorded in this separate file, written next to the
run report. It holds identifiers, hashes, limits, and totals only: no prompt,
model output, or credential.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, cast

from ai_qa_copilot_api.c1_evaluation_model import (
    C1_CALL_LEDGER_SCHEMA_VERSION,
    load_c1_pricing,
)
from ai_qa_copilot_api.evaluation_budgeted_benchmark import (
    BUDGETED_EVALUATION_CORPUS_SUITE_ID,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationRunRejected,
    evaluation_run_from_json,
)
from ai_qa_copilot_api.model_gateway import (
    C1_CONFIGURATION_VERSION,
    C1_MODEL_ID,
    MODEL_PROVIDER_ANTHROPIC,
)
from ai_qa_copilot_api.naive_baseline import load_naive_baseline_config


EVALUATION_RUN_PROVENANCE_SCHEMA_VERSION: Final = "evaluation-run-provenance/v1"
C1_EVIDENCE_CLASS: Final = "c1-provider-comparison"
REVIEW_EVIDENCE_DIRECTORY: Final = Path("evaluation/reviews")
_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")


class EvaluationRunProvenanceRejected(EvaluationRunRejected):
    """Raised when run provenance would be incomplete, inconsistent, or misplaced."""


@dataclass(frozen=True)
class EvaluationRunProvenance:
    schema_version: str
    evidence_class: str
    b1_evidence: bool
    provider: str
    model_id: str
    configuration_version: str
    prompt_version: str
    b0_configuration_sha256: str
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


def build_c1_run_provenance(
    *,
    run_report_path: Path,
    fixture_path: Path,
    pricing_path: Path,
    b0_configuration_path: Path,
    ledger_paths: Sequence[Path],
    git_commit: str,
    max_call_cost_microusd: int,
    max_run_cost_microusd: int,
) -> EvaluationRunProvenance:
    """Validate a C1 run's artifacts and record their content-free provenance."""

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

    run = evaluation_run_from_json(_read(run_report_path, "Run report"))
    fixture_sha256 = _sha256_file(fixture_path, "Fixture")
    if run.suite_id != BUDGETED_EVALUATION_CORPUS_SUITE_ID:
        raise EvaluationRunProvenanceRejected(
            f"C1 runs must use the {BUDGETED_EVALUATION_CORPUS_SUITE_ID} corpus"
        )
    if run.fixture_sha256 != fixture_sha256:
        raise EvaluationRunProvenanceRejected(
            "Run report fixture hash does not match the supplied fixture"
        )
    if run.max_concurrency != 1:
        raise EvaluationRunProvenanceRejected("C1 runs require max_concurrency 1")
    if run.max_expected_cost is None:
        raise EvaluationRunProvenanceRejected(
            "C1 runs require an explicit max_expected_cost"
        )

    pricing = load_c1_pricing(pricing_path)
    b0_configuration = load_naive_baseline_config(b0_configuration_path)
    if not ledger_paths:
        raise EvaluationRunProvenanceRejected("At least one C1 call ledger is required")

    call_count = 0
    charged_microusd = 0
    for ledger_path in ledger_paths:
        for record in _ledger_records(ledger_path):
            if (
                record.get("schema_version") != C1_CALL_LEDGER_SCHEMA_VERSION
                or record.get("provider") != MODEL_PROVIDER_ANTHROPIC
                or record.get("model_id") != C1_MODEL_ID
                or record.get("configuration_version") != C1_CONFIGURATION_VERSION
                or record.get("pricing_version") != pricing.pricing_version
            ):
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} does not match C1 provenance"
                )
            if (
                record.get("max_call_microusd") != max_call_cost_microusd
                or record.get("max_run_microusd") != max_run_cost_microusd
            ):
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} limits differ from the declared limits"
                )
            charged = record.get("charged_microusd")
            if isinstance(charged, bool) or not isinstance(charged, int) or charged < 0:
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} has an invalid charge"
                )
            call_count += 1
            charged_microusd += charged

    return EvaluationRunProvenance(
        schema_version=EVALUATION_RUN_PROVENANCE_SCHEMA_VERSION,
        evidence_class=C1_EVIDENCE_CLASS,
        b1_evidence=False,
        provider=MODEL_PROVIDER_ANTHROPIC,
        model_id=C1_MODEL_ID,
        configuration_version=C1_CONFIGURATION_VERSION,
        prompt_version=b0_configuration.prompt_version,
        b0_configuration_sha256=_sha256_file(b0_configuration_path, "B0 configuration"),
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


def write_c1_run_provenance(
    provenance: EvaluationRunProvenance,
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
            "C1 provenance must never be written under evaluation/reviews"
        )
    try:
        with output.open("x", encoding="utf-8", newline="\n") as file:
            file.write(provenance.as_json())
    except FileExistsError as error:
        raise EvaluationRunProvenanceRejected(
            "Provenance output already exists; evidence is never replaced"
        ) from error


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
