"""Content-free provenance for one informed-baseline run; never B1 evidence.

``evaluation-run-provenance/v2`` is the informed-run counterpart of the C1/v1 B0
provenance in ``evaluation_run_provenance.py`` (unchanged). It records identifiers,
hashes, limits, calibration constants and totals only: no prompt text, model
output, or credential. The prompt, config, schema and catalog hashes are pinned
here, so a recorded run proves which exact prompt produced it (ADR-015).

Accepted combinations (ADR-016): Claude C1/v1 on ``evaluation-corpus/v3`` or
``evaluation-corpus/v4``, and OpenAI O1/v1 (``gpt-6.1-sol``) on
``evaluation-corpus/v4`` only. Provider, model, configuration, calibration,
pricing loader and ledger fields come from one provider profile, so an OpenAI
ledger with Claude pricing, or the reverse, is refused. The OpenAI pricing file
and the v4 fixture are pinned by SHA-256. Ledger records must carry exactly the
fields the provider's factory writes. The provenance format is unchanged, so a
v3 Claude provenance file is byte-identical to the one recorded before.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final, cast

from ai_qa_copilot_api.c1_evaluation_model import load_c1_pricing
from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_informed_benchmark import (
    INFORMED_EVALUATION_CORPUS_SUITE_ID,
)
from ai_qa_copilot_api.evaluation_objective_benchmark import (
    OBJECTIVE_EVALUATION_CORPUS_SUITE_ID,
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
from ai_qa_copilot_api.evaluation_spend_control import Calibration
from ai_qa_copilot_api.informed_claude_evaluation_model import (
    CLAUDE_INFORMED_CALIBRATION,
    INFORMED_CALL_LEDGER_SCHEMA_VERSION,
)
from ai_qa_copilot_api.informed_openai_evaluation_model import (
    OPENAI_INFORMED_CALIBRATION,
    OPENAI_REASONING_LEDGER_FIELD,
    OpenAIInformedEvaluationRejected,
    load_openai_informed_pricing,
)
from ai_qa_copilot_api.metrics import ProviderPricing
from ai_qa_copilot_api.model_gateway import (
    C1_CONFIGURATION_VERSION,
    C1_MODEL_ID,
    MODEL_PROVIDER_ANTHROPIC,
    MODEL_PROVIDER_OPENAI,
)
from ai_qa_copilot_api.openai_informed_evaluation_adapter import (
    OPENAI_INFORMED_CONFIGURATION_VERSION,
    OPENAI_INFORMED_MODEL_ID,
)


INFORMED_PROVENANCE_SCHEMA_VERSION: Final = "evaluation-run-provenance/v2"
INFORMED_EVIDENCE_CLASS: Final = "provider-comparison-informed-development"
V3_FIXTURE_RELATIVE_PATH: Final = Path("fixtures/benchmark/evaluation-cases.v3.yaml")
V4_FIXTURE_RELATIVE_PATH: Final = Path("fixtures/benchmark/evaluation-cases.v4.yaml")
V4_FIXTURE_SHA256: Final = (
    "e79a1a5f771456680a0093d10f8b6f300616dd4f254cc445b86c3769a5daad8d"
)
OPENAI_PRICING_RELATIVE_PATH: Final = Path(
    "fixtures/benchmark/pricing/openai-gpt-6-1-sol.v1.yaml"
)
OPENAI_PRICING_SHA256: Final = (
    "9c9805755033b12ef01fb37f6726d1452091d23c503903f16db64c8ce19a8046"
)

# Every field the spend core writes on an informed ledger record. A provider
# profile may add named extra fields; any other field is refused.
INFORMED_LEDGER_FIELDS: Final = frozenset(
    {
        "schema_version",
        "provider",
        "model_id",
        "configuration_version",
        "prompt_version",
        "pricing_version",
        "call_index",
        "outcome",
        "failure",
        "estimated_input_tokens",
        "actual_input_tokens",
        "output_tokens",
        "calibration_ratio",
        "response_id",
        "worst_case_microusd",
        "charged_microusd",
        "running_total_microusd",
        "max_call_microusd",
        "max_run_microusd",
        "characters_per_token",
        "tolerance",
    }
)

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
_SUITE_LABELS: Final = {
    INFORMED_EVALUATION_CORPUS_SUITE_ID: "v3",
    OBJECTIVE_EVALUATION_CORPUS_SUITE_ID: "v4",
}
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
    provider: str = MODEL_PROVIDER_ANTHROPIC,
) -> InformedRunProvenance:
    """Validate an informed run's artifacts and record their content-free provenance."""

    profile = _PROVIDER_PROFILES.get(provider)
    if profile is None:
        raise EvaluationRunProvenanceRejected("provider must be anthropic or openai")

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
    if suite.suite_id not in _SUITE_LABELS:
        raise EvaluationRunProvenanceRejected(
            f"Informed runs must use the {INFORMED_EVALUATION_CORPUS_SUITE_ID} or "
            f"{OBJECTIVE_EVALUATION_CORPUS_SUITE_ID} corpus"
        )
    if suite.suite_id not in profile.suite_ids:
        raise EvaluationRunProvenanceRejected(
            f"Provider {provider} runs are not accepted on {suite.suite_id}"
        )
    _require_committed_fixture(suite.suite_id, fixture_sha256, repository_root)
    suite_label = _SUITE_LABELS[suite.suite_id]
    case_budget_microusd = int(
        max(Decimal(str(case.expected.maximum_expected_cost)) for case in suite.cases)
        * _MICROUSD_PER_USD
    )
    if max_call_cost_microusd > case_budget_microusd:
        raise EvaluationRunProvenanceRejected(
            f"The per-call limit exceeds the {suite_label} per-case budget"
        )
    if max_call_cost_microusd > max_run_cost_microusd:
        raise EvaluationRunProvenanceRejected(
            "The per-call limit cannot exceed the run limit"
        )

    run = evaluation_run_from_json(_read(run_report_path, "Run report"))
    if run.suite_id != suite.suite_id:
        raise EvaluationRunProvenanceRejected(
            f"Run report suite does not match the {suite.suite_id} fixture"
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
    pricing = profile.load_pricing(pricing_path)
    if not ledger_paths:
        raise EvaluationRunProvenanceRejected(
            "At least one informed call ledger is required"
        )

    calibration = profile.calibration
    allowed_fields = INFORMED_LEDGER_FIELDS | profile.extra_ledger_fields
    call_count = 0
    charged_microusd = 0
    max_ratio = 0.0
    for ledger_path in ledger_paths:
        for record in _ledger_records(ledger_path):
            if (
                record.get("schema_version") != INFORMED_CALL_LEDGER_SCHEMA_VERSION
                or record.get("provider") != profile.provider
                or record.get("model_id") != profile.model_id
                or record.get("configuration_version") != profile.configuration_version
                or record.get("prompt_version") != hashes.prompt_version
                or record.get("pricing_version") != pricing.pricing_version
                or record.get("characters_per_token")
                != str(calibration.characters_per_token)
                or record.get("tolerance") != str(calibration.tolerance)
            ):
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} does not match informed provenance"
                )
            if set(record) != allowed_fields:
                raise EvaluationRunProvenanceRejected(
                    f"Ledger {ledger_path.name} does not match informed provenance: "
                    "its fields differ from the provider's ledger fields"
                )
            for name in profile.extra_ledger_fields:
                extra = record[name]
                if extra is not None and (
                    isinstance(extra, bool) or not isinstance(extra, int) or extra < 0
                ):
                    raise EvaluationRunProvenanceRejected(
                        f"Ledger {ledger_path.name} has an invalid {name} value"
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
        provider=profile.provider,
        model_id=profile.model_id,
        configuration_version=profile.configuration_version,
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
class _ProviderProfile:
    provider: str
    model_id: str
    configuration_version: str
    calibration: Calibration
    load_pricing: Callable[[Path], ProviderPricing]
    extra_ledger_fields: frozenset[str]
    suite_ids: frozenset[str]


def _load_openai_pricing(path: Path) -> ProviderPricing:
    if _sha256_file(path, "Pricing input") != OPENAI_PRICING_SHA256:
        raise EvaluationRunProvenanceRejected(
            "OpenAI pricing input does not match the pinned "
            f"{OPENAI_PRICING_RELATIVE_PATH.as_posix()}"
        )
    try:
        return load_openai_informed_pricing(path).pricing
    except OpenAIInformedEvaluationRejected as error:
        raise EvaluationRunProvenanceRejected(str(error)) from error


_PROVIDER_PROFILES: Final = {
    MODEL_PROVIDER_ANTHROPIC: _ProviderProfile(
        provider=MODEL_PROVIDER_ANTHROPIC,
        model_id=C1_MODEL_ID,
        configuration_version=C1_CONFIGURATION_VERSION,
        calibration=CLAUDE_INFORMED_CALIBRATION,
        load_pricing=load_c1_pricing,
        extra_ledger_fields=frozenset(),
        suite_ids=frozenset(
            {INFORMED_EVALUATION_CORPUS_SUITE_ID, OBJECTIVE_EVALUATION_CORPUS_SUITE_ID}
        ),
    ),
    MODEL_PROVIDER_OPENAI: _ProviderProfile(
        provider=MODEL_PROVIDER_OPENAI,
        model_id=OPENAI_INFORMED_MODEL_ID,
        configuration_version=OPENAI_INFORMED_CONFIGURATION_VERSION,
        calibration=OPENAI_INFORMED_CALIBRATION,
        load_pricing=_load_openai_pricing,
        extra_ledger_fields=frozenset({OPENAI_REASONING_LEDGER_FIELD}),
        suite_ids=frozenset({OBJECTIVE_EVALUATION_CORPUS_SUITE_ID}),
    ),
}


def _require_committed_fixture(
    suite_id: str, fixture_sha256: str, repository_root: Path
) -> None:
    if suite_id == INFORMED_EVALUATION_CORPUS_SUITE_ID:
        committed = repository_root / V3_FIXTURE_RELATIVE_PATH
        if fixture_sha256 != _sha256_file(committed, "Committed v3 fixture"):
            raise EvaluationRunProvenanceRejected(
                "Fixture does not match the committed evaluation-corpus/v3 fixture"
            )
        return
    committed = repository_root / V4_FIXTURE_RELATIVE_PATH
    if fixture_sha256 != V4_FIXTURE_SHA256 or fixture_sha256 != _sha256_file(
        committed, "Committed v4 fixture"
    ):
        raise EvaluationRunProvenanceRejected(
            "Fixture does not match the committed, pinned evaluation-corpus/v4 fixture"
        )


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
