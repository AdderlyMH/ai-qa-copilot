"""Run selected versioned evaluation cases through a supplied executor adapter."""

from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path
from typing import cast

from ai_qa_copilot_api.evaluation_cases import load_evaluation_case_suite
from ai_qa_copilot_api.evaluation_runner import (
    EvaluationCaseExecutor,
    EvaluationRunRejected,
    evaluation_run_from_json,
    run_evaluation_cases,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "fixtures/benchmark/evaluation-cases.v1.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument(
        "--executor",
        required=True,
        help="Executor factory in module:attribute form.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--split", action="append", dest="splits")
    parser.add_argument("--category", action="append", dest="categories")
    parser.add_argument("--tag", action="append", dest="tags")
    parser.add_argument("--criticality", action="append", dest="criticalities")
    parser.add_argument("--max-expected-cost", type=float)
    parser.add_argument("--max-concurrency", type=int, default=1)
    args = parser.parse_args(argv)

    if not args.fixture.is_file():
        raise SystemExit(f"Evaluation fixture does not exist: {args.fixture}")
    if not args.repository_root.is_dir():
        raise SystemExit(f"Repository root does not exist: {args.repository_root}")
    if args.resume is not None and not args.resume.is_file():
        raise SystemExit(f"Resume report does not exist: {args.resume}")
    if args.output.exists() and args.resume is None:
        raise SystemExit(
            f"Output already exists: {args.output}. "
            "Use --resume or choose a different --output path."
        )
    if (
        args.output.exists()
        and args.resume is not None
        and args.output.resolve() != args.resume.resolve()
    ):
        raise SystemExit(
            "An existing output may only be overwritten when it is the "
            "same path supplied to --resume."
        )

    try:
        resume_from = (
            evaluation_run_from_json(args.resume.read_text(encoding="utf-8"))
            if args.resume is not None
            else None
        )
        report = run_evaluation_cases(
            load_evaluation_case_suite(args.fixture),
            fixture_path=args.fixture,
            repository_root=args.repository_root,
            executor=_load_executor(args.executor),
            case_ids=args.case_ids,
            splits=args.splits,
            categories=args.categories,
            tags=args.tags,
            criticalities=args.criticalities,
            max_expected_cost=args.max_expected_cost,
            max_concurrency=args.max_concurrency,
            resume_from=resume_from,
        )
    except EvaluationRunRejected as error:
        raise SystemExit(str(error)) from error

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report.as_json(), encoding="utf-8")
    print(f"Evaluation run written: {_display_path(args.output)}")
    return 0


def _load_executor(specification: str) -> EvaluationCaseExecutor:
    module_name, separator, attribute_name = specification.partition(":")
    if not separator or not module_name or not attribute_name:
        raise SystemExit("--executor must use module:attribute form")

    try:
        module = import_module(module_name)
    except ModuleNotFoundError as error:
        raise SystemExit(
            f"Executor module could not be imported: {module_name}"
        ) from error

    factory = getattr(module, attribute_name, None)
    if not callable(factory):
        raise SystemExit(
            f"Executor factory is missing or not callable: {specification}"
        )

    executor = factory()
    if not callable(getattr(executor, "execute", None)):
        raise SystemExit(
            f"Executor factory did not return an object with execute(): {specification}"
        )

    return cast(EvaluationCaseExecutor, executor)


def _display_path(path: Path) -> Path:
    try:
        return path.resolve().relative_to(ROOT)
    except ValueError:
        return path.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
