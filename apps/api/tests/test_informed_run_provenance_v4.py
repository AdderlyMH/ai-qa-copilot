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

# Provenance JSON produced by main's informed_run_provenance.py (commit 7bdc485,
# before v4/OpenAI support) for the deterministic v3 Claude run in
# test_informed_run_provenance.informed_run, with the run report rewritten as LF
# bytes (see the test). Produced by loading main's module from `git show` and
# calling build_informed_run_provenance on exactly these inputs; the new module
# returned identical bytes. Every input is platform-independent: the fixture,
# pricing, prompt configuration and catalog are eol=lf in .gitattributes, the
# ledger is written by the spend core with newline="\n", the run report is
# written LF by the test, and the git commit is a fixed value.
MAIN_V3_CLAUDE_PROVENANCE = """\
{
  "b1_evidence": false,
  "baseline_id": "INFORMED",
  "calibration_tolerance": "0.15",
  "catalog_sha256": "c4a5800834585a847f26cf4fc898f5e7cf69551e7ff5769e9de1be6648ed8814",
  "characters_per_token": "2.1",
  "configuration_version": "C1/v1",
  "developer_text_sha256": "f024095091f73da5c1762387164754b7b5ff92f3bdd482070fc8313354a378ee",
  "evidence_class": "provider-comparison-informed-development",
  "fixture_sha256": "8511b573d57e24436a705cb119b4c2db47b5883bdcbb9f498d3adfc5e35b69ae",
  "git_commit": "0000000000000000000000000000000000000002",
  "ledger_call_count": 2,
  "ledger_charged_microusd": 46518,
  "ledger_sha256": [
    "d8210babf4b4cb81106755823aeb56e8bcfcacb5256d285d8ec0b3ce58a6dfaf"
  ],
  "max_calibration_ratio": 0.7001,
  "max_call_cost_microusd": 100000,
  "max_concurrency": 1,
  "max_expected_cost_usd": 0.2,
  "max_run_cost_microusd": 200000,
  "model_id": "claude-sonnet-5-5",
  "pricing_sha256": "7dc30f348c3ac448446beca79bdd8a7f771be67eb224c377bbb23b323f5e2d17",
  "pricing_version": "anthropic-claude-sonnet-5-5/2026-10-04/standard-global-no-inference-geo",
  "prompt_config_sha256": "983dfbf64c9bb7ad07206f4124f13852441a832f9b91d3fd2d84270a4a07b478",
  "prompt_version": "informed-single-prompt/v1",
  "provider": "anthropic",
  "run_report_sha256": "fd14e8eb8fa4ec5928957445727d6fb4e2e0681f44a96793a22ed0821fedf9a1",
  "schema_sha256": "9f06849a25161f346f9036b7158cf83a746121637363d8f6414c2f4be68e1067",
  "schema_version": "evaluation-run-provenance/v2",
  "suite_id": "evaluation-corpus/v3"
}
"""
MAIN_V3_CLAUDE_PROVENANCE_SHA256 = (
    "37631ab157f2490a468323bcb561b7d3c7b26cebc37db90dc629a2a10d68b14c"
)


def write_lf(path: Path, text: str) -> None:
    """Write text with LF bytes on every platform, so hashes are portable."""

    path.write_text(text, encoding="utf-8", newline="\n")


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
    write_lf(run_path, report.as_json())
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
    write_lf(path, "".join(json.dumps(r) + "\n" for r in records))
    return path


# Unchanged v3 / Claude output


def test_v3_claude_provenance_is_byte_identical_to_main(tmp_path: Path) -> None:
    run_path, ledger_path = informed_v3_run(tmp_path / "artifacts")
    # The shared helper writes the run report with the platform newline (CRLF on
    # Windows). Rewrite it as LF so the run-report hash, and with it the whole
    # provenance, is the same on every platform.
    write_lf(run_path, run_path.read_text(encoding="utf-8"))
    assert b"\r" not in run_path.read_bytes()
    assert b"\r" not in ledger_path.read_bytes()

    text = build_v3(run_path, (ledger_path,)).as_json()

    assert text == MAIN_V3_CLAUDE_PROVENANCE
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == (
        MAIN_V3_CLAUDE_PROVENANCE_SHA256
    )
    assert (
        hashlib.sha256(MAIN_V3_CLAUDE_PROVENANCE.encode("utf-8")).hexdigest()
        == MAIN_V3_CLAUDE_PROVENANCE_SHA256
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
