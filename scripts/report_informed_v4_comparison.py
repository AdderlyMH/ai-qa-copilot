"""Verify informed-v4 run artifacts and render the provider-comparison tables.

Reads run folders produced by the provider-comparison workflow (ledger,
provenance, run report and, except probes, score report) as data. Every folder
is verified before anything is reported, and any mismatch refuses the report:

- the ledger and run-report SHA-256 equal the provenance; the score report's
  ``run_sha256`` equals the provenance ``run_report_sha256``;
- the ledger's charged total equals the provenance total, every call succeeded,
  and ``b1_evidence`` is false;
- provider, model and configuration agree with the folder and the ledger;
- the recorded provenance is byte-identical to one rebuilt from the artifacts by
  the committed recorder (which also checks the v4 fixture pin, the four prompt
  pins, the pricing file and the ledger fields);
- the score report is byte-identical to one re-scored by the committed scorer.

The Markdown output reports exactly four checks (required IDs, unexpected IDs,
source references, boundary) as passed of applicable, per run and per v4
category, with the negative controls separate and required IDs and references
"n/a" on them. It never reports an overall pass figure. Output is deterministic
(sorted, LF).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from ai_qa_copilot_api.evaluation_cases import (
    EvaluationCase,
    load_evaluation_case_suite,
)
from ai_qa_copilot_api.evaluation_run_provenance import (
    EvaluationRunProvenanceRejected,
)
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationRun,
    EvaluationRunRejected,
    evaluation_run_from_json,
)
from ai_qa_copilot_api.evaluation_scoring import (
    EvaluationScoreReport,
    load_ground_truth_catalog,
    score_evaluation_run,
)
from ai_qa_copilot_api.informed_baseline import DEFAULT_INFORMED_CONFIG_PATH
from ai_qa_copilot_api.informed_run_provenance import (
    INFORMED_DEVELOPER_TEXT_SHA256,
    INFORMED_PROMPT_CONFIG_SHA256,
    INFORMED_SCHEMA_SHA256,
    V4_FIXTURE_RELATIVE_PATH,
    V4_FIXTURE_SHA256,
    build_informed_run_provenance,
)


ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH_RELATIVE_PATH: Final = Path("fixtures/benchmark/ground-truth.v1.yaml")
NEGATIVE_CONTROL_TAG: Final = "negative_control"
NEGATIVE_CONTROLS_LABEL: Final = "negative controls"

FULL_RUNS: Final = ("claude-1", "claude-2", "openai-1", "openai-2")
OPTIONAL_RUNS: Final = ("smoke-claude", "smoke-openai", "probe-1", "probe-2")
FOLDER_PROVIDER: Final = {
    "claude-1": "anthropic",
    "claude-2": "anthropic",
    "openai-1": "openai",
    "openai-2": "openai",
    "smoke-claude": "anthropic",
    "smoke-openai": "openai",
    "probe-1": "openai",
    "probe-2": "openai",
}
FOLDER_SCOPE: Final = {
    "claude-1": "development",
    "claude-2": "development",
    "openai-1": "development",
    "openai-2": "development",
    "smoke-claude": "smoke",
    "smoke-openai": "smoke",
    "probe-1": "probe",
    "probe-2": "probe",
}
PROVIDER_IDENTITY: Final = {
    "anthropic": ("claude-sonnet-5-5", "C1/v1"),
    "openai": ("gpt-6.1-sol", "O1/v1"),
}
PROVIDER_PRICING: Final = {
    "anthropic": Path("fixtures/benchmark/pricing/anthropic-claude-sonnet-5-5.v1.yaml"),
    "openai": Path("fixtures/benchmark/pricing/openai-gpt-6-1-sol.v1.yaml"),
}
PROVIDER_LABEL: Final = {"anthropic": "Claude", "openai": "OpenAI"}
DISCRIMINATING_CHECKS: Final = (
    ("required_ground_truth_ids", "Required IDs"),
    ("unexpected_ground_truth_ids", "No unexpected IDs"),
    ("expected_source_references", "Source references"),
    ("policy_boundary", "Boundary"),
)
NOT_APPLICABLE_ON_CONTROLS: Final = frozenset(
    {"required_ground_truth_ids", "expected_source_references"}
)

Record = dict[str, object]


class ComparisonReportRejected(ValueError):
    """Raised when a run folder fails verification."""


@dataclass(frozen=True)
class VerifiedRun:
    label: str
    provider: str
    scope: str
    provenance: Record
    ledger: tuple[Record, ...]
    run: EvaluationRun
    score: EvaluationScoreReport | None
    ledger_sha256: str
    run_report_sha256: str


# Verification


def verify_run_folder(folder: Path, label: str, repository_root: Path) -> VerifiedRun:
    """Verify one run folder completely or refuse it."""

    if label not in FOLDER_PROVIDER:
        raise ComparisonReportRejected(f"Unknown run folder name: {label}")
    provider = FOLDER_PROVIDER[label]
    scope = FOLDER_SCOPE[label]
    stem = f"informed-v4-{provider}-{scope}"
    paths = {
        kind: folder / f"{stem}-{kind}"
        for kind in ("ledger.jsonl", "provenance.json", "run.json", "score.json")
    }
    required = ["ledger.jsonl", "provenance.json", "run.json"]
    if scope != "probe":
        required.append("score.json")
    for kind in required:
        if not paths[kind].is_file():
            raise ComparisonReportRejected(f"{label}: missing {paths[kind].name}")
    unexpected = sorted(
        item.name
        for item in folder.iterdir()
        if item.is_file() and item.name not in {paths[kind].name for kind in required}
    )
    if unexpected:
        raise ComparisonReportRejected(f"{label}: unexpected files {unexpected}")

    provenance_text = paths["provenance.json"].read_text(encoding="utf-8")
    provenance = cast(Record, json.loads(provenance_text))
    model_id, configuration = PROVIDER_IDENTITY[provider]
    if (
        provenance.get("provider"),
        provenance.get("model_id"),
        provenance.get("configuration_version"),
    ) != (provider, model_id, configuration):
        raise ComparisonReportRejected(
            f"{label}: provenance provider, model or configuration is not {provider}"
        )
    if provenance.get("b1_evidence") is not False:
        raise ComparisonReportRejected(f"{label}: b1_evidence must be false")
    for field, pinned in (
        ("fixture_sha256", V4_FIXTURE_SHA256),
        ("developer_text_sha256", INFORMED_DEVELOPER_TEXT_SHA256),
        ("prompt_config_sha256", INFORMED_PROMPT_CONFIG_SHA256),
        ("schema_sha256", INFORMED_SCHEMA_SHA256),
    ):
        if provenance.get(field) != pinned:
            raise ComparisonReportRejected(f"{label}: {field} differs from the pin")

    ledger_sha256 = _sha256(paths["ledger.jsonl"])
    run_report_sha256 = _sha256(paths["run.json"])
    if provenance.get("ledger_sha256") != [ledger_sha256]:
        raise ComparisonReportRejected(
            f"{label}: ledger SHA-256 differs from provenance"
        )
    if provenance.get("run_report_sha256") != run_report_sha256:
        raise ComparisonReportRejected(
            f"{label}: run-report SHA-256 differs from provenance"
        )

    ledger = tuple(
        cast(Record, json.loads(line))
        for line in paths["ledger.jsonl"].read_text(encoding="utf-8").splitlines()
    )
    for record in ledger:
        if record.get("outcome") != "succeeded" or record.get("failure") is not None:
            raise ComparisonReportRejected(f"{label}: the ledger has a failed call")
        if (
            record.get("provider"),
            record.get("model_id"),
            record.get("configuration_version"),
        ) != (provider, model_id, configuration):
            raise ComparisonReportRejected(
                f"{label}: ledger provider, model or configuration is not {provider}"
            )
    if sum(_int(record, "charged_microusd") for record in ledger) != provenance.get(
        "ledger_charged_microusd"
    ):
        raise ComparisonReportRejected(
            f"{label}: charged total differs from the ledger sum"
        )

    try:
        rebuilt = build_informed_run_provenance(
            run_report_path=paths["run.json"],
            fixture_path=repository_root / V4_FIXTURE_RELATIVE_PATH,
            pricing_path=repository_root / PROVIDER_PRICING[provider],
            configuration_path=repository_root / DEFAULT_INFORMED_CONFIG_PATH,
            ledger_paths=(paths["ledger.jsonl"],),
            repository_root=repository_root,
            git_commit=str(provenance.get("git_commit")),
            max_call_cost_microusd=_int(provenance, "max_call_cost_microusd"),
            max_run_cost_microusd=_int(provenance, "max_run_cost_microusd"),
            provider=provider,
        )
    except EvaluationRunProvenanceRejected as error:
        raise ComparisonReportRejected(f"{label}: {error}") from error
    if rebuilt.as_json() != provenance_text:
        raise ComparisonReportRejected(
            f"{label}: recorded provenance differs from a rebuild from its artifacts"
        )

    run = evaluation_run_from_json(paths["run.json"].read_text(encoding="utf-8"))
    score: EvaluationScoreReport | None = None
    if scope != "probe":
        score_text = paths["score.json"].read_text(encoding="utf-8")
        recorded = cast(Record, json.loads(score_text))
        if recorded.get("run_sha256") != run_report_sha256:
            raise ComparisonReportRejected(
                f"{label}: score run_sha256 differs from provenance run_report_sha256"
            )
        fixture_path = repository_root / V4_FIXTURE_RELATIVE_PATH
        catalog_path = repository_root / GROUND_TRUTH_RELATIVE_PATH
        score = score_evaluation_run(
            load_evaluation_case_suite(fixture_path),
            run,
            load_ground_truth_catalog(catalog_path),
            case_fixture_path=fixture_path,
            ground_truth_path=catalog_path,
        )
        if score.as_json() != score_text:
            raise ComparisonReportRejected(
                f"{label}: score report differs from a re-score of its run report"
            )

    return VerifiedRun(
        label=label,
        provider=provider,
        scope=scope,
        provenance=provenance,
        ledger=ledger,
        run=run,
        score=score,
        ledger_sha256=ledger_sha256,
        run_report_sha256=run_report_sha256,
    )


def load_runs(runs_root: Path, repository_root: Path) -> list[VerifiedRun]:
    """Verify the four full runs and any optional runs present."""

    runs: list[VerifiedRun] = []
    for label in FULL_RUNS:
        folder = runs_root / label
        if not folder.is_dir():
            raise ComparisonReportRejected(f"Missing full run folder: {label}")
        runs.append(verify_run_folder(folder, label, repository_root))
    for label in OPTIONAL_RUNS:
        folder = runs_root / label
        if folder.is_dir():
            runs.append(verify_run_folder(folder, label, repository_root))
    return runs


# Analysis


def category_of(case: EvaluationCase) -> str:
    if NEGATIVE_CONTROL_TAG in case.tags:
        return NEGATIVE_CONTROLS_LABEL
    return case.category


def check_counts(
    run: VerifiedRun, cases: Mapping[str, EvaluationCase], case_ids: Sequence[str]
) -> dict[str, tuple[int, int] | None]:
    """Passed and applicable per discriminating check; None when nothing applies."""

    assert run.score is not None
    scores = {score.case_id: score for score in run.score.scores}
    counts: dict[str, tuple[int, int] | None] = {}
    for code, _ in DISCRIMINATING_CHECKS:
        passed = applicable = 0
        for case_id in case_ids:
            if (
                code in NOT_APPLICABLE_ON_CONTROLS
                and category_of(cases[case_id]) == NEGATIVE_CONTROLS_LABEL
            ):
                continue
            check = next(c for c in scores[case_id].checks if c.code == code)
            applicable += 1
            passed += int(check.passed)
        counts[code] = (passed, applicable) if applicable else None
    return counts


def observations(
    run: VerifiedRun,
) -> dict[str, tuple[tuple[str, ...], str, tuple[str, ...]]]:
    """Per case: sorted IDs, boundary, sorted references."""

    return {
        result.case_id: (
            tuple(sorted(result.observation.ground_truth_ids)),
            result.observation.boundary,
            tuple(sorted(result.observation.source_references)),
        )
        for result in run.run.results
    }


def same_artifact_different_granularity(expected: str, cited: str) -> bool:
    """True when ``cited`` points into the same artifact element at another granularity.

    Requirements: same requirement ID, different part. OpenAPI: one JSON pointer
    is a prefix of the other.
    """

    expected_artifact, _, expected_locator = expected.partition("#")
    cited_artifact, _, cited_locator = cited.partition("#")
    if expected_artifact != cited_artifact or expected == cited:
        return False
    if expected_artifact == "REQ-BASE-001":
        return expected_locator.split("#")[0] == cited_locator.split("#")[0]
    if expected_locator.startswith("/") and cited_locator.startswith("/"):
        return cited_locator.startswith(expected_locator + "/") or (
            expected_locator.startswith(cited_locator + "/")
        )
    return False


def ledger_totals(run: VerifiedRun) -> dict[str, str]:
    reasoning = [r.get("reasoning_tokens") for r in run.ledger]
    reported = [value for value in reasoning if isinstance(value, int)]
    return {
        "calls": str(len(run.ledger)),
        "charged": f"{sum(_int(r, 'charged_microusd') for r in run.ledger) / 1_000_000:.6f}",
        "input": str(sum(_int(r, "actual_input_tokens") for r in run.ledger)),
        "output": str(sum(_int(r, "output_tokens") for r in run.ledger)),
        "reasoning": str(sum(reported)) if run.provider == "openai" else "n/a",
        "max_ratio": f"{max(_float(r, 'calibration_ratio') for r in run.ledger):.4f}",
        "max_output": str(max(_int(r, "output_tokens") for r in run.ledger)),
    }


# Rendering


def render_report(runs: Sequence[VerifiedRun], repository_root: Path) -> str:
    suite = load_evaluation_case_suite(repository_root / V4_FIXTURE_RELATIVE_PATH)
    cases = {case.id: case for case in suite.cases}
    scored = [run for run in runs if run.score is not None]
    full = [run for run in runs if run.label in FULL_RUNS]
    lines: list[str] = []
    add = lines.append

    add(
        "<!-- Generated by scripts/report_informed_v4_comparison.py; do not edit by hand. -->"
    )
    add("")
    add("### Verified inputs")
    add("")
    add(
        "| Run | Provider | Scope | Calls | Commit | Run report SHA-256 | Ledger SHA-256 |"
    )
    add("|---|---|---|---|---|---|---|")
    for run in runs:
        add(
            f"| {run.label} | {PROVIDER_LABEL[run.provider]} | {run.scope} | "
            f"{len(run.ledger)} | `{str(run.provenance['git_commit'])[:12]}` | "
            f"`{run.run_report_sha256}` | `{run.ledger_sha256}` |"
        )
    add("")
    add(
        "Each run's provenance was rebuilt from its artifacts by the committed "
        "recorder and matched byte for byte, and each score report matched a "
        "re-score of its run report by the committed scorer."
    )

    add("")
    add("### Discriminating checks by run")
    add("")
    add(
        "Passed of applicable. Required IDs and source references are n/a on the "
        "four negative controls; side effects are excluded."
    )
    add("")
    add("| Run | " + " | ".join(label for _, label in DISCRIMINATING_CHECKS) + " |")
    add("|---|" + "---|" * len(DISCRIMINATING_CHECKS))
    for run in scored:
        counts = check_counts(run, cases, run.run.selected_case_ids)
        add(
            f"| {run.label} | "
            + " | ".join(_cell(counts[c]) for c, _ in DISCRIMINATING_CHECKS)
            + " |"
        )

    policy = sorted(case.id for case in suite.cases if case.run_mode == "policy")
    add("")
    add(
        f"Policy cases ({', '.join(policy)}) expect no model call; their "
        "side-effects check fails by construction (structural), so it is not "
        "reported."
    )

    for run in full:
        add("")
        add(f"### By category: {run.label}")
        add("")
        add(
            "| Category | Cases | "
            + " | ".join(label for _, label in DISCRIMINATING_CHECKS)
            + " |"
        )
        add("|---|---|" + "---|" * len(DISCRIMINATING_CHECKS))
        groups: dict[str, list[str]] = defaultdict(list)
        for case_id in run.run.selected_case_ids:
            groups[category_of(cases[case_id])].append(case_id)
        for category in sorted(
            groups, key=lambda name: (name == NEGATIVE_CONTROLS_LABEL, name)
        ):
            counts = check_counts(run, cases, sorted(groups[category]))
            add(
                f"| {category} | {len(groups[category])} | "
                + " | ".join(_cell(counts[c]) for c, _ in DISCRIMINATING_CHECKS)
                + " |"
            )

    add("")
    add("### Run-to-run stability")
    add("")
    add("| Provider | Runs | Cases | Same IDs and boundary | Same reference sets |")
    add("|---|---|---|---|---|")
    for provider in ("anthropic", "openai"):
        pair = [run for run in full if run.provider == provider]
        first, second = observations(pair[0]), observations(pair[1])
        shared = sorted(set(first) & set(second))
        same_answer = sum(first[c][:2] == second[c][:2] for c in shared)
        same_refs = sum(first[c][2] == second[c][2] for c in shared)
        add(
            f"| {PROVIDER_LABEL[provider]} | {pair[0].label}, {pair[1].label} | "
            f"{len(shared)} | {same_answer} of {len(shared)} | {same_refs} of {len(shared)} |"
        )

    claude = next(run for run in full if run.provider == "anthropic")
    openai = next(run for run in full if run.provider == "openai")
    claude_obs, openai_obs = observations(claude), observations(openai)
    add("")
    add(f"### Where the providers differ ({claude.label} and {openai.label})")
    add("")
    add("Cases whose selected IDs or boundary differ between the providers.")
    add("")
    add("| Case | Category | Expected | Claude | OpenAI |")
    add("|---|---|---|---|---|")
    differing = sorted(
        c
        for c in set(claude_obs) & set(openai_obs)
        if claude_obs[c][:2] != openai_obs[c][:2]
    )
    for case_id in differing:
        case = cases[case_id]
        expected = (
            tuple(sorted(case.expected.required_ground_truth_ids)),
            case.expected.policy_boundary,
        )
        add(
            f"| {case_id} | {category_of(case)} | {_answer(expected)} | "
            f"{_answer(claude_obs[case_id][:2])} | {_answer(openai_obs[case_id][:2])} |"
        )
    if not differing:
        add("| none | n/a | n/a | n/a | n/a |")

    add("")
    add("### Reference misses")
    add("")
    add(
        "Expected references a run did not cite, with the run's cited references in "
        'the same artifact. Granularity is "yes" when a cited reference shares the '
        "requirement ID or is a JSON-pointer prefix or extension of the expected one."
    )
    add("")
    add(
        "| Run | Case | Expected, not cited | Cited in the same artifact | Same artifact, different granularity |"
    )
    add("|---|---|---|---|---|")
    any_miss = False
    for run in full:
        for case_id in sorted(observations(run)):
            if category_of(cases[case_id]) == NEGATIVE_CONTROLS_LABEL:
                continue
            cited = observations(run)[case_id][2]
            for missing in sorted(
                set(cases[case_id].expected.expected_source_references) - set(cited)
            ):
                artifact = missing.partition("#")[0]
                same_artifact = [c for c in cited if c.partition("#")[0] == artifact]
                granularity = any(
                    same_artifact_different_granularity(missing, c) for c in cited
                )
                add(
                    f"| {run.label} | {case_id} | `{missing}` | "
                    f"{', '.join(f'`{c}`' for c in same_artifact) or 'none'} | "
                    f"{'yes' if granularity else 'no'} |"
                )
                any_miss = True
    if not any_miss:
        add("| none | n/a | n/a | n/a | n/a |")

    add("")
    add("### Cost and tokens (from the ledgers)")
    add("")
    add(
        "| Run | Provider | Calls | Charged USD | Input tokens | Output tokens | "
        "Reasoning tokens | Max calibration ratio | Max output tokens |"
    )
    add("|---|---|---|---|---|---|---|---|---|")
    for run in runs:
        totals = ledger_totals(run)
        add(
            f"| {run.label} | {PROVIDER_LABEL[run.provider]} | {totals['calls']} | "
            f"{totals['charged']} | {totals['input']} | {totals['output']} | "
            f"{totals['reasoning']} | {totals['max_ratio']} | {totals['max_output']} |"
        )
    total = sum(_int(r, "charged_microusd") for run in runs for r in run.ledger)
    add("")
    add(f"Total charged across these {len(runs)} runs: {total / 1_000_000:.6f} USD.")
    return "\n".join(lines) + "\n"


def _cell(count: tuple[int, int] | None) -> str:
    return "n/a" if count is None else f"{count[0]} of {count[1]}"


def _answer(answer: tuple[tuple[str, ...], str]) -> str:
    ids, boundary = answer
    return f"{', '.join(ids) or 'none'}; `{boundary}`"


def _int(record: Mapping[str, object], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ComparisonReportRejected(f"{key} must be an integer")
    return value


def _float(record: Mapping[str, object], key: str) -> float:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ComparisonReportRejected(f"{key} must be a number")
    return float(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    try:
        runs = load_runs(args.runs_root, args.repository_root)
        report = render_report(runs, args.repository_root)
    except (ComparisonReportRejected, EvaluationRunRejected) as error:
        raise SystemExit(str(error)) from error
    args.output.write_text(report, encoding="utf-8", newline="\n")
    print(f"Comparison tables written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
