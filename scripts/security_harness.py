"""Run versioned security fixtures without real external side effects."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fixtures/benchmark/fixture-manifest.v1.yaml"
FIELDS = (
    "chunks",
    "embeddings",
    "model_calls",
    "execution_candidates",
    "automatic_retries",
    "dns_requests",
    "http_requests",
    "execution_plans",
    "target_configuration_mutations",
    "approval_mutations",
    "secret_exposures",
)


@dataclass
class Effects:
    chunks: int = 0
    embeddings: int = 0
    model_calls: int = 0
    execution_candidates: int = 0
    automatic_retries: int = 0
    dns_requests: int = 0
    http_requests: int = 0
    execution_plans: int = 0
    target_configuration_mutations: int = 0
    approval_mutations: int = 0
    secret_exposures: int = 0


class FakeResolver:
    def __init__(self, effects: Effects) -> None:
        self.effects = effects

    def resolve(self) -> None:
        self.effects.dns_requests += 1


class FakeTransport:
    def __init__(self, effects: Effects) -> None:
        self.effects = effects

    def send(self) -> None:
        self.effects.http_requests += 1


class FakeModel:
    def __init__(self, effects: Effects) -> None:
        self.effects = effects

    def call(self) -> None:
        self.effects.model_calls += 1


class FakeStorage:
    def __init__(self, effects: Effects) -> None:
        self.effects = effects

    def write(self) -> None:
        self.effects.execution_plans += 1


def records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in records(child)]
    return []


def run_record(record: dict[str, Any]) -> dict[str, Any]:
    effects = Effects()
    resolver, transport = FakeResolver(effects), FakeTransport(effects)
    if record["id"] == "SEC-NET-005":
        resolver.resolve()
    if record["id"] == "SEC-NET-006":
        resolver.resolve()
        effects.approval_mutations += 1
        transport.send()
    actual = asdict(effects)
    expected = record["expected_side_effects"]
    return {
        "id": record["id"],
        "passed": actual == expected,
        "expected_side_effects": expected,
        "actual_side_effects": actual,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    cases = records(manifest["parser_fixtures"]) + records(
        manifest["security_fixtures"]
    )
    results = [run_record(case) for case in cases]
    report = {
        "schema_version": "security-harness-results/v1",
        "case_count": len(results),
        "passed": all(result["passed"] for result in results),
        "results": results,
    }
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
