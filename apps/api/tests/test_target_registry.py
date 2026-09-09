from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from ai_qa_copilot_api.target_registry import (
    DEFAULT_TARGET_REGISTRY,
    TARGET_REGISTRY_SCHEMA_VERSION,
    AddressResolver,
    TargetConfiguration,
    TargetId,
    TargetRegistry,
    TargetValidationBoundary,
    TargetValidationError,
    validate_registered_target,
)


@dataclass
class FakeResolver:
    """Deterministic resolver double that never performs a DNS request."""

    answers: tuple[tuple[str, ...], ...]
    calls: int = 0
    hostnames: list[str] = field(default_factory=list)

    def resolve(self, hostname: str) -> tuple[str, ...]:
        self.hostnames.append(hostname)
        try:
            answer = self.answers[self.calls]
        except IndexError as error:
            raise AssertionError("Unexpected resolver call") from error
        self.calls += 1
        return answer


def registry_with(
    *,
    base_url: str = "https://ai-qa-sandbox.onrender.com",
    redirects_allowed: bool = False,
    schema_version: str = TARGET_REGISTRY_SCHEMA_VERSION,
) -> TargetRegistry:
    return TargetRegistry(
        targets=(
            TargetConfiguration(
                id=TargetId.SYNTHETIC_ORDER_API,
                base_url=base_url,
                redirects_allowed=redirects_allowed,
                schema_version=schema_version,
            ),
        )
    )


def assert_rejected(
    error: pytest.ExceptionInfo[TargetValidationError],
    boundary: TargetValidationBoundary,
) -> None:
    assert error.value.boundary is boundary


def test_default_registry_allows_only_the_exact_public_sandbox_target() -> None:
    assert DEFAULT_TARGET_REGISTRY.targets == (
        TargetConfiguration(
            id=TargetId.SYNTHETIC_ORDER_API,
            base_url="https://ai-qa-sandbox.onrender.com",
        ),
    )

    target = DEFAULT_TARGET_REGISTRY.get(TargetId.SYNTHETIC_ORDER_API)

    assert target.id is TargetId.SYNTHETIC_ORDER_API
    assert target.base_url == "https://ai-qa-sandbox.onrender.com"
    assert "*" not in target.base_url
    assert target.redirects_allowed is False
    assert target.schema_version == TARGET_REGISTRY_SCHEMA_VERSION


def test_unknown_target_id_fails_closed_before_resolution() -> None:
    resolver = FakeResolver(answers=())

    with pytest.raises(TargetValidationError) as error:
        validate_registered_target("unregistered-target", resolver=resolver)

    assert_rejected(error, TargetValidationBoundary.UNKNOWN_TARGET_ID)
    assert resolver.calls == 0
    assert resolver.hostnames == []


def test_valid_target_requires_two_identical_public_resolution_results() -> None:
    resolver = FakeResolver(
        answers=(
            ("8.8.8.8", "1.1.1.1"),
            ("1.1.1.1", "8.8.8.8"),
        )
    )

    target = validate_registered_target(
        TargetId.SYNTHETIC_ORDER_API,
        resolver=resolver,
    )

    assert target.id is TargetId.SYNTHETIC_ORDER_API
    assert target.origin == "https://ai-qa-sandbox.onrender.com"
    assert target.hostname == "ai-qa-sandbox.onrender.com"
    assert target.port == 443
    assert target.resolved_addresses == ("1.1.1.1", "8.8.8.8")
    assert target.redirects_allowed is False
    assert resolver.calls == 2
    assert resolver.hostnames == [
        "ai-qa-sandbox.onrender.com",
        "ai-qa-sandbox.onrender.com",
    ]


@pytest.mark.parametrize(
    ("base_url", "boundary"),
    [
        (
            "http://ai-qa-sandbox.onrender.com",
            TargetValidationBoundary.HTTPS_REQUIRED,
        ),
        (
            "https://user:password@ai-qa-sandbox.onrender.com",
            TargetValidationBoundary.USERINFO_FORBIDDEN,
        ),
        (
            "https://ai-qa-sandbox.onrender.com:8443",
            TargetValidationBoundary.NONSTANDARD_PORT,
        ),
        (
            "https://ai-qa-sandbox.onrender.com/orders",
            TargetValidationBoundary.PATH_FORBIDDEN,
        ),
        (
            "https://ai-qa-sandbox.onrender.com?tenant=other",
            TargetValidationBoundary.QUERY_OR_FRAGMENT_FORBIDDEN,
        ),
        (
            "https://ai-qa-sandbox.onrender.com#fragment",
            TargetValidationBoundary.QUERY_OR_FRAGMENT_FORBIDDEN,
        ),
        (
            "https://metadata.google.internal",
            TargetValidationBoundary.METADATA_TARGET,
        ),
        (
            "https://instance-data.ec2.internal",
            TargetValidationBoundary.METADATA_TARGET,
        ),
        (
            "https://127.0.0.1",
            TargetValidationBoundary.LITERAL_IP,
        ),
        (
            "https://[::1]",
            TargetValidationBoundary.LITERAL_IP,
        ),
        (
            "https://0177.0.0.1",
            TargetValidationBoundary.ALTERNATE_IP_NOTATION,
        ),
        (
            "https://0x7F000001",
            TargetValidationBoundary.ALTERNATE_IP_NOTATION,
        ),
        (
            "https://2130706433",
            TargetValidationBoundary.ALTERNATE_IP_NOTATION,
        ),
    ],
)
def test_registry_rejects_disallowed_target_configurations(
    base_url: str,
    boundary: TargetValidationBoundary,
) -> None:
    with pytest.raises(TargetValidationError) as error:
        registry_with(base_url=base_url)

    assert_rejected(error, boundary)


def test_registry_rejects_enabled_redirects() -> None:
    with pytest.raises(TargetValidationError) as error:
        registry_with(redirects_allowed=True)

    assert_rejected(error, TargetValidationBoundary.REDIRECTS_ENABLED)


def test_registry_rejects_unsupported_schema_version() -> None:
    with pytest.raises(TargetValidationError) as error:
        registry_with(schema_version="target-registry/unsupported")

    assert_rejected(error, TargetValidationBoundary.MALFORMED_URL)


def test_registry_rejects_an_empty_target_catalog() -> None:
    with pytest.raises(TargetValidationError) as error:
        TargetRegistry(targets=())

    assert_rejected(error, TargetValidationBoundary.EMPTY_REGISTRY)


def test_registry_rejects_duplicate_server_side_target_ids() -> None:
    first = TargetConfiguration(
        id=TargetId.SYNTHETIC_ORDER_API,
        base_url="https://ai-qa-sandbox.onrender.com",
    )
    duplicate = TargetConfiguration(
        id=TargetId.SYNTHETIC_ORDER_API,
        base_url="https://another.synthetic.test",
    )

    with pytest.raises(TargetValidationError) as error:
        TargetRegistry(targets=(first, duplicate))

    assert_rejected(error, TargetValidationBoundary.DUPLICATE_TARGET_ID)


@pytest.mark.parametrize(
    ("answers", "boundary"),
    [
        ((), TargetValidationBoundary.EMPTY_RESOLVER_ANSWER),
        (("not-an-ip",), TargetValidationBoundary.INVALID_RESOLVER_ANSWER),
        (("127.0.0.1",), TargetValidationBoundary.RESTRICTED_RESOLVER_ANSWER),
        (("10.0.0.8",), TargetValidationBoundary.RESTRICTED_RESOLVER_ANSWER),
        (("169.254.169.254",), TargetValidationBoundary.RESTRICTED_RESOLVER_ANSWER),
        (("::1",), TargetValidationBoundary.RESTRICTED_RESOLVER_ANSWER),
    ],
)
def test_resolver_answers_fail_closed_before_a_target_can_be_used(
    answers: tuple[str, ...],
    boundary: TargetValidationBoundary,
) -> None:
    resolver = FakeResolver(answers=(answers,))

    with pytest.raises(TargetValidationError) as error:
        validate_registered_target(
            TargetId.SYNTHETIC_ORDER_API,
            resolver=resolver,
        )

    assert_rejected(error, boundary)
    assert resolver.calls == 1


def test_changed_public_answers_are_rejected_as_dns_rebinding() -> None:
    resolver = FakeResolver(
        answers=(
            ("8.8.8.8",),
            ("1.1.1.1",),
        )
    )

    with pytest.raises(TargetValidationError) as error:
        validate_registered_target(
            TargetId.SYNTHETIC_ORDER_API,
            resolver=resolver,
        )

    assert_rejected(error, TargetValidationBoundary.DNS_REBINDING)
    assert resolver.calls == 2
    assert resolver.hostnames == [
        "ai-qa-sandbox.onrender.com",
        "ai-qa-sandbox.onrender.com",
    ]


def test_rebinding_to_a_private_address_is_rejected_before_target_use() -> None:
    resolver = FakeResolver(
        answers=(
            ("8.8.8.8",),
            ("169.254.169.254",),
        )
    )

    with pytest.raises(TargetValidationError) as error:
        validate_registered_target(
            TargetId.SYNTHETIC_ORDER_API,
            resolver=resolver,
        )

    assert_rejected(error, TargetValidationBoundary.RESTRICTED_RESOLVER_ANSWER)
    assert resolver.calls == 2


def test_fake_resolver_satisfies_the_injected_resolver_contract() -> None:
    resolver: AddressResolver = FakeResolver(
        answers=(
            ("8.8.8.8",),
            ("8.8.8.8",),
        )
    )

    target = validate_registered_target(
        TargetId.SYNTHETIC_ORDER_API,
        resolver=resolver,
    )

    assert target.resolved_addresses == ("8.8.8.8",)
