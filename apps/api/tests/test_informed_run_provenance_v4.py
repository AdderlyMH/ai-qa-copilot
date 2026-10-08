"""Informed provenance for evaluation-corpus/v4 and the OpenAI O1/v1 path (ADR-016).

Fake transports only; no provider or network call.
"""

from __future__ import annotations

import hashlib
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from ai_qa_copilot_api import informed_run_provenance as provenance_module
from ai_qa_copilot_api.b1_reference_assembly_inputs import (
    B1ReferenceAssemblyInputRejected,
    load_b1_reference_assembly_input,
)
from ai_qa_copilot_api.c1_evaluation_model import load_c1_pricing
from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_run_provenance import (
    EvaluationRunProvenanceRejected,
)
from ai_qa_copilot_api.evaluation_runner import run_evaluation_cases
from ai_qa_copilot_api.evaluation_spend_control import SpendLimits
from ai_qa_copilot_api.informed_baseline import (
    DEFAULT_INFORMED_CONFIG_PATH,
    InformedBaselineExecutor,
    load_informed_baseline_config,
)
from ai_qa_copilot_api.informed_claude_evaluation_model import InformedClaudeModel
from ai_qa_copilot_api.informed_openai_evaluation_model import (
    InformedOpenAIModel,
    load_openai_informed_pricing,
)
from ai_qa_copilot_api.informed_run_provenance import (
    INFORMED_LEDGER_FIELDS,
    InformedRunProvenance,
    build_informed_run_provenance,
    write_informed_run_provenance,
)
from ai_qa_copilot_api.model_gateway import AnthropicGatewaySettings
from ai_qa_copilot_api.openai_informed_evaluation_adapter import (
    OpenAIInformedSettings,
)


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from record_informed_evaluation_provenance import (  # noqa: E402
    main as record_informed_provenance_main,
)
from test_informed_openai_evaluation_model import (  # noqa: E402
    estimate_transport as openai_transport,
)
from test_informed_run_provenance import (  # noqa: E402
    FakeTransport as ClaudeTransport,
)
from test_informed_run_provenance import (  # noqa: E402
    build as build_v3,
)
from test_informed_run_provenance import (  # noqa: E402
    informed_run as informed_v3_run,
)


V3_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v3.yaml"
V4_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v4.yaml"
CONFIGURATION = ROOT / DEFAULT_INFORMED_CONFIG_PATH
CLAUDE_PRICING = ROOT / "fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml"
OPENAI_PRICING = ROOT / "fixtures/benchmark/pricing/openai-gpt-6-1-sol.v1.yaml"
COMMIT = "0" * 39 + "4"
CASE_IDS = ("EVAL-101", "EVAL-111")
MAX_CALL = 110_000
MAX_RUN = 220_000

# SHA-256 of the provenance JSON that main (before this change) recorded for the
# deterministic v3 Claude run in test_informed_run_provenance.informed_run.
V3_CLAUDE_PROVENANCE_SHA256 = (
    "6617b39d0c9d79c2686c0861f2836f3431e59bc7c97e2794e1b409d76305d799"
)


def v4_run(artifacts: Path, provider: str) -> tuple[Path, Path]:
    """Run two v4 cases through the real informed model of one provider."""

    artifacts.mkdir(parents=True, exist_ok=True)
    ledger_path = artifacts / f"{provider}-ledger.jsonl"
    limits = SpendLimits(max_call_microusd=MAX_CALL, max_run_microusd=MAX_RUN)
    configuration = load_informed_baseline_config(CONFIGURATION)
    model: InformedClaudeModel | InformedOpenAIModel
    if provider == "anthropic":
        model = InformedClaudeModel(
            settings=AnthropicGatewaySettings(api_key="test-anthropic-key-not-real"),
            pricing=load_c1_pricing(CLAUDE_PRICING),
            limits=limits,
            ledger_path=ledger_path,
            configuration=configuration,
            repository_root=ROOT,
            transport=ClaudeTransport(),
        )
    else:
        model = InformedOpenAIModel(
            settings=OpenAIInformedSettings(api_key="test-openai-key-not-real"),
            pricing=load_openai_informed_pricing(OPENAI_PRICING),
            limits=limits,
            ledger_path=ledger_path,
            configuration=configuration,
            repository_root=ROOT,
            transport=openai_transport(scale=Decimal("0.7")),
        )
    report = run_evaluation_cases(
        load_evaluation_case_suite(V4_FIXTURE),
        fixture_path=V4_FIXTURE,
        repository_root=ROOT,
        executor=InformedBaselineExecutor(
            configuration=configuration, repository_root=ROOT, model=model
        ),
        case_ids=CASE_IDS,
        max_expected_cost=0.22,
        max_concurrency=1,
    )
    run_path = artifacts / f"{provider}-run.json"
    run_path.write_text(report.as_json(), encoding="utf-8")
    return run_path, ledger_path


def build(
    run_path: Path,
    ledger_path: Path,
    *,
    provider: str,
    pricing: Path | None = None,
    fixture: Path = V4_FIXTURE,
    max_call: int = MAX_CALL,
) -> InformedRunProvenance:
    return build_informed_run_provenance(
        run_report_path=run_path,
        fixture_path=fixture,
        pricing_path=pricing
        or (OPENAI_PRICING if provider == "openai" else CLAUDE_PRICING),
        configuration_path=CONFIGURATION,
        ledger_paths=(ledger_path,),
        repository_root=ROOT,
        git_commit=COMMIT,
        max_call_cost_microusd=max_call,
        max_run_cost_microusd=MAX_RUN,
        provider=provider,
    )


def rewritten_ledger(ledger_path: Path, change: dict[str, object]) -> Path:
    records = [json.loads(line) for line in ledger_path.read_text("utf-8").splitlines()]
    for key, value in change.items():
        if value is ...:
            records[0].pop(key)
        else:
            records[0][key] = value
    path = ledger_path.with_name("changed-ledger.jsonl")
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


# Unchanged v3 / Claude output


def test_v3_claude_provenance_is_byte_identical_to_main(tmp_path: Path) -> None:
    run_path, ledger_path = informed_v3_run(tmp_path / "artifacts")

    text = build_v3(run_path, (ledger_path,)).as_json()

    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == (
        V3_CLAUDE_PROVENANCE_SHA256
    )


# Accepted combinations


def test_v4_claude_run_is_accepted(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "anthropic")

    recorded = build(run_path, ledger_path, provider="anthropic")

    assert recorded.provider == "anthropic"
    assert recorded.model_id == "claude-sonnet-5-5"
    assert recorded.configuration_version == "C1/v1"
    assert recorded.suite_id == "evaluation-corpus/v4"
    assert recorded.fixture_sha256 == provenance_module.V4_FIXTURE_SHA256
    assert recorded.ledger_call_count == 2
    assert recorded.b1_evidence is False


def test_v4_openai_run_is_accepted(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")
    records = [json.loads(line) for line in ledger_path.read_text("utf-8").splitlines()]

    recorded = build(run_path, ledger_path, provider="openai")

    assert set(records[0]) == INFORMED_LEDGER_FIELDS | {"reasoning_tokens"}
    assert recorded.provider == "openai"
    assert recorded.model_id == "gpt-6.1-sol"
    assert recorded.configuration_version == "O1/v1"
    assert recorded.pricing_version == (
        "openai-gpt-6.1-sol/2026-10-08/standard-short-context-cache-disabled"
    )
    assert recorded.pricing_sha256 == provenance_module.OPENAI_PRICING_SHA256
    assert recorded.characters_per_token == "2.1"
    assert recorded.calibration_tolerance == "0.15"
    assert recorded.evidence_class == "provider-comparison-informed-development"
    assert recorded.b1_evidence is False
    assert recorded.ledger_call_count == 2
    assert recorded.ledger_charged_microusd == sum(
        r["charged_microusd"] for r in records
    )
    for pin in ("developer_text_sha256", "prompt_config_sha256", "schema_sha256"):
        assert getattr(recorded, pin) == getattr(
            provenance_module, f"INFORMED_{pin.removesuffix('_sha256').upper()}_SHA256"
        )


def test_claude_ledger_fields_are_exactly_the_core_fields(tmp_path: Path) -> None:
    _, ledger_path = v4_run(tmp_path, "anthropic")
    first = json.loads(ledger_path.read_text("utf-8").splitlines()[0])

    assert set(first) == INFORMED_LEDGER_FIELDS


def test_cli_records_openai_provenance(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")
    output = run_path.parent / "openai-run.provenance.json"

    exit_code = record_informed_provenance_main(
        [
            "--run-report",
            str(run_path),
            "--ledger",
            str(ledger_path),
            "--pricing",
            str(OPENAI_PRICING),
            "--fixture",
            str(V4_FIXTURE),
            "--git-commit",
            COMMIT,
            "--max-call-cost-usd",
            "0.11",
            "--max-run-cost-usd",
            "0.22",
            "--output",
            str(output),
            "--repository-root",
            str(ROOT),
            "--provider",
            "openai",
        ]
    )

    assert exit_code == 0
    recorded = json.loads(output.read_text("utf-8"))
    assert recorded["provider"] == "openai"
    assert recorded["b1_evidence"] is False


# Cross-provider and fixture refusals


def test_openai_ledger_recorded_as_claude_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")

    with pytest.raises(EvaluationRunProvenanceRejected, match="does not match"):
        build(run_path, ledger_path, provider="anthropic")


def test_claude_ledger_recorded_as_openai_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "anthropic")

    with pytest.raises(EvaluationRunProvenanceRejected, match="does not match"):
        build(run_path, ledger_path, provider="openai")


@pytest.mark.parametrize(
    ("provider", "pricing", "message"),
    [
        ("openai", CLAUDE_PRICING, "pinned"),
        ("anthropic", OPENAI_PRICING, "C1 pricing fields"),
    ],
)
def test_pricing_of_the_other_provider_is_refused(
    tmp_path: Path, provider: str, pricing: Path, message: str
) -> None:
    run_path, ledger_path = v4_run(tmp_path, provider)

    with pytest.raises(Exception, match=message):
        build(run_path, ledger_path, provider=provider, pricing=pricing)


def test_openai_pricing_that_differs_from_the_pin_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")
    altered = tmp_path / "openai-pricing.yaml"
    altered.write_text(OPENAI_PRICING.read_text("utf-8") + "# edited\n", "utf-8")

    with pytest.raises(EvaluationRunProvenanceRejected, match="pinned"):
        build(run_path, ledger_path, provider="openai", pricing=altered)


def test_openai_is_not_accepted_on_v3(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")

    with pytest.raises(EvaluationRunProvenanceRejected, match="not accepted on"):
        build(run_path, ledger_path, provider="openai", fixture=V3_FIXTURE)


def test_unknown_provider_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")

    with pytest.raises(EvaluationRunProvenanceRejected, match="anthropic or openai"):
        build(run_path, ledger_path, provider="google")


def test_altered_v4_fixture_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")
    altered = tmp_path / "altered-v4.yaml"
    altered.write_text(V4_FIXTURE.read_text("utf-8") + "# edited\n", "utf-8")

    with pytest.raises(EvaluationRunProvenanceRejected, match="pinned"):
        build(run_path, ledger_path, provider="openai", fixture=altered)


def test_v4_fixture_that_differs_from_the_pin_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_path, ledger_path = v4_run(tmp_path, "anthropic")
    monkeypatch.setattr(provenance_module, "V4_FIXTURE_SHA256", "0" * 64)

    with pytest.raises(EvaluationRunProvenanceRejected, match="pinned"):
        build(run_path, ledger_path, provider="anthropic")


def test_run_report_for_v3_with_a_v4_fixture_is_refused(tmp_path: Path) -> None:
    v3_run_path, _ = informed_v3_run(tmp_path / "v3")
    _, ledger_path = v4_run(tmp_path, "anthropic")

    with pytest.raises(EvaluationRunProvenanceRejected, match="suite does not match"):
        build(v3_run_path, ledger_path, provider="anthropic")


def test_per_call_limit_above_the_v4_budget_is_refused(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")

    with pytest.raises(EvaluationRunProvenanceRejected, match="v4 per-case budget"):
        build(run_path, ledger_path, provider="openai", max_call=110_001)


# Ledger field and outcome refusals


@pytest.mark.parametrize(
    ("provider", "change", "message"),
    [
        ("openai", {"unexpected": 1}, "fields differ"),
        ("openai", {"reasoning_tokens": ...}, "fields differ"),
        ("anthropic", {"reasoning_tokens": 5}, "fields differ"),
        ("anthropic", {"prompt": "text"}, "fields differ"),
        ("openai", {"reasoning_tokens": -1}, "invalid reasoning_tokens"),
        ("openai", {"reasoning_tokens": "120"}, "invalid reasoning_tokens"),
        ("openai", {"reasoning_tokens": True}, "invalid reasoning_tokens"),
        ("openai", {"outcome": "failed", "failure": "invalid_output"}, "failed call"),
        ("openai", {"provider": "anthropic"}, "does not match"),
        ("openai", {"model_id": "gpt-6-sol"}, "does not match"),
        ("openai", {"configuration_version": "C1/v1"}, "does not match"),
        ("openai", {"pricing_version": "other"}, "does not match"),
        ("anthropic", {"provider": "openai"}, "does not match"),
    ],
)
def test_ledger_changes_are_refused(
    tmp_path: Path, provider: str, change: dict[str, object], message: str
) -> None:
    run_path, ledger_path = v4_run(tmp_path, provider)

    with pytest.raises(EvaluationRunProvenanceRejected, match=message):
        build(run_path, rewritten_ledger(ledger_path, change), provider=provider)


def test_null_reasoning_tokens_are_accepted(tmp_path: Path) -> None:
    run_path, ledger_path = v4_run(tmp_path, "openai")

    recorded = build(
        run_path,
        rewritten_ledger(ledger_path, {"reasoning_tokens": None}),
        provider="openai",
    )

    assert recorded.ledger_call_count == 2


# Never B1 evidence


@pytest.mark.parametrize("provider", ["anthropic", "openai"])
def test_b1_assembly_rejects_v4_provenance(tmp_path: Path, provider: str) -> None:
    run_path, ledger_path = v4_run(tmp_path, provider)
    output = run_path.parent / f"{provider}-provenance.json"
    write_informed_run_provenance(
        build(run_path, ledger_path, provider=provider),
        repository_root=tmp_path,
        run_report_path=run_path,
        output_path=output,
    )

    with pytest.raises(B1ReferenceAssemblyInputRejected):
        load_b1_reference_assembly_input(output)
