"""Record content-free informed-baseline provenance next to an evaluation run report."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ai_qa_copilot_api.evaluation_runner import EvaluationRunRejected
from ai_qa_copilot_api.informed_baseline import DEFAULT_INFORMED_CONFIG_PATH
from ai_qa_copilot_api.informed_run_provenance import (
    build_informed_run_provenance,
    write_informed_run_provenance,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v3.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-report", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, action="append", required=True)
    parser.add_argument("--pricing", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--informed-configuration",
        type=Path,
        default=ROOT / DEFAULT_INFORMED_CONFIG_PATH,
    )
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--max-call-cost-usd", required=True)
    parser.add_argument("--max-run-cost-usd", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument(
        "--provider", choices=("anthropic", "openai"), default="anthropic"
    )
    args = parser.parse_args(argv)

    try:
        provenance = build_informed_run_provenance(
            run_report_path=args.run_report,
            fixture_path=args.fixture,
            pricing_path=args.pricing,
            configuration_path=args.informed_configuration,
            ledger_paths=tuple(args.ledger),
            repository_root=args.repository_root,
            git_commit=args.git_commit,
            max_call_cost_microusd=_microusd(args.max_call_cost_usd),
            max_run_cost_microusd=_microusd(args.max_run_cost_usd),
            provider=args.provider,
        )
        write_informed_run_provenance(
            provenance,
            repository_root=args.repository_root,
            run_report_path=args.run_report,
            output_path=args.output,
        )
    except EvaluationRunRejected as error:
        raise SystemExit(str(error)) from error

    print(f"Informed run provenance written: {args.output}")
    return 0


def _microusd(text: str) -> int:
    try:
        amount = Decimal(text) * 1_000_000
    except InvalidOperation as error:
        raise SystemExit(f"Invalid USD amount: {text}") from error
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise SystemExit(f"Invalid USD amount: {text}")
    return int(amount)


if __name__ == "__main__":
    raise SystemExit(main())
