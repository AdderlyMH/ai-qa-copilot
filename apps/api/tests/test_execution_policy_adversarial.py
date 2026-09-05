from __future__ import annotations

from dataclasses import replace

import pytest

from ai_qa_copilot_api.execution_policy_adversarial import (
    EXECUTION_POLICY_FIXTURE_SCHEMA_VERSION,
    BlockingBoundary,
    ExecutionPolicyFixtureV1,
    FakeResolver,
    FakeTransport,
    FIXTURES,
    PolicyOutcome,
    evaluate_default_deny,
    run_execution_policy_fixture,
    run_execution_policy_suite,
)


def fixture_by_id(fixture_id: str) -> ExecutionPolicyFixtureV1:
    for fixture in FIXTURES:
        if fixture.id == fixture_id:
            return fixture
    raise AssertionError(f"Missing fixture: {fixture_id}")


def test_fixture_catalog_has_a_stable_version_and_unique_ids() -> None:
    assert len(FIXTURES) == 15
    assert {fixture.schema_version for fixture in FIXTURES} == {
        EXECUTION_POLICY_FIXTURE_SCHEMA_VERSION
    }
    assert len({fixture.id for fixture in FIXTURES}) == len(FIXTURES)


def test_fixture_catalog_covers_every_required_adversarial_category() -> None:
    boundaries = {fixture.expected_boundary for fixture in FIXTURES}

    assert {
        BlockingBoundary.MALFORMED_URL,
        BlockingBoundary.RESTRICTED_LITERAL_IP,
        BlockingBoundary.ALTERNATE_IP_NOTATION,
        BlockingBoundary.METADATA_TARGET,
        BlockingBoundary.REDIRECT_DISABLED,
        BlockingBoundary.FORBIDDEN_HEADER,
        BlockingBoundary.APPROVAL_MUTATED,
        BlockingBoundary.APPROVAL_REPLAY,
        BlockingBoundary.RESPONSE_SIZE_LIMIT,
        BlockingBoundary.RESOLVER_PRIVATE_ANSWER,
        BlockingBoundary.DNS_REBINDING,
        BlockingBoundary.EXECUTOR_UNAVAILABLE,
    } <= boundaries


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda fixture: fixture.id)
def test_every_fixture_denies_before_any_transport_send(
    fixture: ExecutionPolicyFixtureV1,
) -> None:
    result = run_execution_policy_fixture(fixture)

    assert result.passed is True
    assert result.actual_boundary is fixture.expected_boundary
    assert result.resolver_calls == fixture.expected_resolver_calls
    assert result.transport_sends == 0


def test_suite_is_deterministic_and_all_cases_pass() -> None:
    first = run_execution_policy_suite()
    second = run_execution_policy_suite()

    assert first == second
    assert len(first) == len(FIXTURES)
    assert all(result.passed for result in first)
    assert all(result.transport_sends == 0 for result in first)


def test_dns_rebinding_is_revalidated_immediately_before_transport() -> None:
    fixture = fixture_by_id("EXEC-POL-014")
    resolver = FakeResolver(fixture.resolver_answers)
    transport = FakeTransport()

    decision = evaluate_default_deny(
        fixture.request,
        resolver=resolver,
        transport=transport,
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.boundary is BlockingBoundary.DNS_REBINDING
    assert resolver.hostnames == [
        "sandbox.example.test",
        "sandbox.example.test",
    ]
    assert resolver.calls == 2
    assert transport.sends == 0


def test_safe_resolver_answers_still_fail_closed_without_an_executor() -> None:
    fixture = fixture_by_id("EXEC-POL-015")
    resolver = FakeResolver(fixture.resolver_answers)
    transport = FakeTransport()

    decision = evaluate_default_deny(
        fixture.request,
        resolver=resolver,
        transport=transport,
    )

    assert decision.outcome is PolicyOutcome.DENY
    assert decision.boundary is BlockingBoundary.EXECUTOR_UNAVAILABLE
    assert resolver.calls == 2
    assert transport.sends == 0


def test_fake_transport_fails_immediately_if_a_send_is_attempted() -> None:
    transport = FakeTransport()

    with pytest.raises(AssertionError, match="must not invoke outbound transport"):
        transport.send()

    assert transport.sends == 1


def test_fake_resolver_rejects_unconfigured_calls() -> None:
    resolver = FakeResolver(())

    with pytest.raises(AssertionError, match="unexpected resolver call"):
        resolver.resolve("sandbox.example.test")

    assert resolver.calls == 0


def test_invalid_resolver_answer_fails_closed_without_transport() -> None:
    base = fixture_by_id("EXEC-POL-015")
    fixture = replace(
        base,
        expected_boundary=BlockingBoundary.RESOLVER_PRIVATE_ANSWER,
        resolver_answers=(("not-an-ip-address",),),
        expected_resolver_calls=1,
    )

    result = run_execution_policy_fixture(fixture)

    assert result.passed is True
    assert result.resolver_calls == 1
    assert result.transport_sends == 0


def test_fixture_validation_rejects_an_unknown_schema_version() -> None:
    invalid_fixture = replace(
        fixture_by_id("EXEC-POL-001"),
        schema_version="execution-policy-adversarial/v999",
    )

    with pytest.raises(ValueError, match="Unsupported fixture schema"):
        run_execution_policy_fixture(invalid_fixture)


def test_fixture_validation_rejects_mismatched_resolver_expectations() -> None:
    invalid_fixture = replace(
        fixture_by_id("EXEC-POL-013"),
        expected_resolver_calls=2,
    )

    with pytest.raises(ValueError, match="Resolver-answer count"):
        run_execution_policy_fixture(invalid_fixture)
