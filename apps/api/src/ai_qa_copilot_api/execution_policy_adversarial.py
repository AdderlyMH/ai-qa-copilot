"""Versioned, fake-only adversarial checks for future HTTP execution policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import ipaddress
from typing import Final
from urllib.parse import urlsplit


EXECUTION_POLICY_FIXTURE_SCHEMA_VERSION: Final = "execution-policy-adversarial/v1"
MAX_RESPONSE_BYTES: Final = 1_048_576

_FORBIDDEN_HEADERS: Final = frozenset(
    {
        "authorization",
        "cookie",
        "host",
        "proxy-authorization",
        "x-forwarded-for",
    }
)
_METADATA_HOSTS: Final = frozenset(
    {
        "metadata.google.internal",
        "metadata.google.internal.",
    }
)


class PolicyOutcome(StrEnum):
    """Closed outcomes for the pre-executor adversarial suite."""

    DENY = "deny"


class BlockingBoundary(StrEnum):
    """The exact default-deny boundary reached by a fixture."""

    MALFORMED_URL = "malformed_url_before_dns"
    HTTPS_REQUIRED = "https_scheme_required_before_dns"
    METADATA_TARGET = "metadata_target_blocked_before_dns"
    RESTRICTED_LITERAL_IP = "restricted_literal_ip_blocked_before_dns"
    ALTERNATE_IP_NOTATION = "alternate_ip_notation_blocked_before_dns"
    REDIRECT_DISABLED = "redirect_disabled_before_dns"
    FORBIDDEN_HEADER = "forbidden_header_blocked_before_dns"
    RESPONSE_SIZE_LIMIT = "response_size_limit_before_dns"
    APPROVAL_MISSING = "approval_presence_check_before_dns"
    APPROVAL_MUTATED = "approval_integrity_check_before_dns"
    APPROVAL_REPLAY = "approval_replay_check_before_dns"
    RESOLVER_PRIVATE_ANSWER = "resolver_answer_blocked_before_transport"
    DNS_REBINDING = "resolver_answer_revalidation_before_transport"
    EXECUTOR_UNAVAILABLE = "executor_unavailable_default_deny"


@dataclass(frozen=True)
class ApprovalSnapshot:
    """Minimal immutable approval data required for a future executor."""

    approved_plan_hash: str | None
    current_plan_hash: str
    consumed: bool = False


@dataclass(frozen=True)
class ExecutionPolicyRequest:
    """Pure data inspected before any future outbound transport exists."""

    url: str
    headers: tuple[tuple[str, str], ...]
    approval: ApprovalSnapshot | None
    redirect_requested: bool = False
    declared_response_bytes: int = 0


@dataclass(frozen=True)
class ExecutionPolicyFixtureV1:
    """One versioned default-deny scenario and its expected blocking boundary."""

    id: str
    request: ExecutionPolicyRequest
    expected_boundary: BlockingBoundary
    resolver_answers: tuple[tuple[str, ...], ...] = ()
    expected_resolver_calls: int = 0
    schema_version: str = EXECUTION_POLICY_FIXTURE_SCHEMA_VERSION


@dataclass(frozen=True)
class PolicyDecision:
    """The observable result of one fake-only policy evaluation."""

    outcome: PolicyOutcome
    boundary: BlockingBoundary
    resolver_calls: int
    transport_sends: int


@dataclass(frozen=True)
class FixtureResult:
    """Actual result compared independently with fixture expectations."""

    id: str
    passed: bool
    expected_boundary: BlockingBoundary
    actual_boundary: BlockingBoundary
    resolver_calls: int
    expected_resolver_calls: int
    transport_sends: int


class FakeResolver:
    """Records deterministic DNS answers without performing DNS requests."""

    def __init__(self, answers: tuple[tuple[str, ...], ...]) -> None:
        self._answers = answers
        self.calls = 0
        self.hostnames: list[str] = []

    def resolve(self, hostname: str) -> tuple[str, ...]:
        """Return the next configured answer without contacting a resolver."""

        self.hostnames.append(hostname)
        try:
            answer = self._answers[self.calls]
        except IndexError as error:
            raise AssertionError(
                "Fixture attempted an unexpected resolver call"
            ) from error
        self.calls += 1
        return answer


class FakeTransport:
    """Fails immediately if code attempts to introduce an outbound send."""

    def __init__(self) -> None:
        self.sends = 0

    def send(self) -> None:
        """Record and fail: EXEC-000 may not send HTTP traffic."""

        self.sends += 1
        raise AssertionError("EXEC-000 must not invoke outbound transport")


def evaluate_default_deny(
    request: ExecutionPolicyRequest,
    *,
    resolver: FakeResolver,
    transport: FakeTransport,
) -> PolicyDecision:
    """Evaluate a request through pre-executor policy only; never send traffic."""

    boundary = _pre_dns_boundary(request)
    if boundary is not None:
        return _deny(boundary, resolver, transport)

    host = _validated_hostname(request.url)
    if host is None:
        return _deny(BlockingBoundary.MALFORMED_URL, resolver, transport)

    first_answers = resolver.resolve(host)
    if _contains_restricted_address(first_answers):
        return _deny(BlockingBoundary.RESOLVER_PRIVATE_ANSWER, resolver, transport)

    second_answers = resolver.resolve(host)
    if _contains_restricted_address(second_answers):
        return _deny(BlockingBoundary.DNS_REBINDING, resolver, transport)

    return _deny(BlockingBoundary.EXECUTOR_UNAVAILABLE, resolver, transport)


def run_execution_policy_fixture(
    fixture: ExecutionPolicyFixtureV1,
) -> FixtureResult:
    """Run exactly one fixture through fake adapters and compare expectations."""

    _validate_fixture(fixture)
    resolver = FakeResolver(fixture.resolver_answers)
    transport = FakeTransport()
    decision = evaluate_default_deny(
        fixture.request,
        resolver=resolver,
        transport=transport,
    )
    passed = (
        decision.outcome is PolicyOutcome.DENY
        and decision.boundary is fixture.expected_boundary
        and decision.resolver_calls == fixture.expected_resolver_calls
        and decision.transport_sends == 0
    )
    return FixtureResult(
        id=fixture.id,
        passed=passed,
        expected_boundary=fixture.expected_boundary,
        actual_boundary=decision.boundary,
        resolver_calls=decision.resolver_calls,
        expected_resolver_calls=fixture.expected_resolver_calls,
        transport_sends=decision.transport_sends,
    )


def run_execution_policy_suite() -> tuple[FixtureResult, ...]:
    """Run the complete versioned default-deny catalog without network access."""

    return tuple(run_execution_policy_fixture(fixture) for fixture in FIXTURES)


def _pre_dns_boundary(
    request: ExecutionPolicyRequest,
) -> BlockingBoundary | None:
    if _is_malformed_url(request.url):
        return BlockingBoundary.MALFORMED_URL

    parsed = urlsplit(request.url)
    if parsed.scheme != "https":
        return BlockingBoundary.HTTPS_REQUIRED

    host = parsed.hostname
    if host is None:
        return BlockingBoundary.MALFORMED_URL
    normalized_host = host.lower().rstrip(".")
    if normalized_host in _METADATA_HOSTS:
        return BlockingBoundary.METADATA_TARGET
    if _is_restricted_literal_ip(normalized_host):
        return BlockingBoundary.RESTRICTED_LITERAL_IP
    if _looks_like_alternate_ip_notation(normalized_host):
        return BlockingBoundary.ALTERNATE_IP_NOTATION
    if request.redirect_requested:
        return BlockingBoundary.REDIRECT_DISABLED
    if any(name.lower() in _FORBIDDEN_HEADERS for name, _ in request.headers):
        return BlockingBoundary.FORBIDDEN_HEADER
    if request.declared_response_bytes > MAX_RESPONSE_BYTES:
        return BlockingBoundary.RESPONSE_SIZE_LIMIT
    if request.approval is None or request.approval.approved_plan_hash is None:
        return BlockingBoundary.APPROVAL_MISSING
    if request.approval.approved_plan_hash != request.approval.current_plan_hash:
        return BlockingBoundary.APPROVAL_MUTATED
    if request.approval.consumed:
        return BlockingBoundary.APPROVAL_REPLAY
    return None


def _deny(
    boundary: BlockingBoundary,
    resolver: FakeResolver,
    transport: FakeTransport,
) -> PolicyDecision:
    return PolicyDecision(
        outcome=PolicyOutcome.DENY,
        boundary=boundary,
        resolver_calls=resolver.calls,
        transport_sends=transport.sends,
    )


def _is_malformed_url(value: str) -> bool:
    if not value or value != value.strip() or "\x00" in value:
        return True

    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return True

    return (
        not parsed.scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    )


def _validated_hostname(value: str) -> str | None:
    try:
        hostname = urlsplit(value).hostname
    except ValueError:
        return None
    return hostname.lower().rstrip(".") if hostname is not None else None


def _is_restricted_literal_ip(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return not address.is_global


def _looks_like_alternate_ip_notation(hostname: str) -> bool:
    if hostname.isdecimal():
        return True
    return hostname.replace(".", "").isdecimal()


def _contains_restricted_address(addresses: tuple[str, ...]) -> bool:
    if not addresses:
        return True

    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            return True
        if not address.is_global:
            return True
    return False


def _validate_fixture(fixture: ExecutionPolicyFixtureV1) -> None:
    if fixture.schema_version != EXECUTION_POLICY_FIXTURE_SCHEMA_VERSION:
        raise ValueError(f"Unsupported fixture schema: {fixture.schema_version}")
    if not fixture.id.startswith("EXEC-POL-"):
        raise ValueError("Execution-policy fixture IDs must start with EXEC-POL-")
    if fixture.expected_resolver_calls != len(fixture.resolver_answers):
        raise ValueError("Resolver-answer count must equal expected resolver calls")


def _approved() -> ApprovalSnapshot:
    return ApprovalSnapshot(
        approved_plan_hash="approved-plan-sha256",
        current_plan_hash="approved-plan-sha256",
    )


def _request(
    url: str,
    *,
    headers: tuple[tuple[str, str], ...] = (),
    approval: ApprovalSnapshot | None = None,
    redirect_requested: bool = False,
    declared_response_bytes: int = 0,
) -> ExecutionPolicyRequest:
    return ExecutionPolicyRequest(
        url=url,
        headers=headers,
        approval=approval,
        redirect_requested=redirect_requested,
        declared_response_bytes=declared_response_bytes,
    )


FIXTURES: Final[tuple[ExecutionPolicyFixtureV1, ...]] = (
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-001",
        request=_request("https://"),
        expected_boundary=BlockingBoundary.MALFORMED_URL,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-002",
        request=_request("http://sandbox.example.test"),
        expected_boundary=BlockingBoundary.HTTPS_REQUIRED,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-003",
        request=_request("https://127.0.0.1/admin"),
        expected_boundary=BlockingBoundary.RESTRICTED_LITERAL_IP,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-004",
        request=_request("https://0177.0.0.1/admin"),
        expected_boundary=BlockingBoundary.ALTERNATE_IP_NOTATION,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-005",
        request=_request("https://[::1]/admin"),
        expected_boundary=BlockingBoundary.RESTRICTED_LITERAL_IP,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-006",
        request=_request("https://metadata.google.internal/computeMetadata/v1"),
        expected_boundary=BlockingBoundary.METADATA_TARGET,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-007",
        request=_request(
            "https://sandbox.example.test/orders",
            approval=_approved(),
            redirect_requested=True,
        ),
        expected_boundary=BlockingBoundary.REDIRECT_DISABLED,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-008",
        request=_request(
            "https://sandbox.example.test/orders",
            headers=(("Authorization", "secret"),),
            approval=_approved(),
        ),
        expected_boundary=BlockingBoundary.FORBIDDEN_HEADER,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-009",
        request=_request("https://sandbox.example.test/orders"),
        expected_boundary=BlockingBoundary.APPROVAL_MISSING,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-010",
        request=_request(
            "https://sandbox.example.test/orders",
            approval=ApprovalSnapshot(
                approved_plan_hash="approved-plan-sha256",
                current_plan_hash="mutated-plan-sha256",
            ),
        ),
        expected_boundary=BlockingBoundary.APPROVAL_MUTATED,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-011",
        request=_request(
            "https://sandbox.example.test/orders",
            approval=ApprovalSnapshot(
                approved_plan_hash="approved-plan-sha256",
                current_plan_hash="approved-plan-sha256",
                consumed=True,
            ),
        ),
        expected_boundary=BlockingBoundary.APPROVAL_REPLAY,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-012",
        request=_request(
            "https://sandbox.example.test/orders",
            approval=_approved(),
            declared_response_bytes=MAX_RESPONSE_BYTES + 1,
        ),
        expected_boundary=BlockingBoundary.RESPONSE_SIZE_LIMIT,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-013",
        request=_request(
            "https://sandbox.example.test/orders",
            approval=_approved(),
        ),
        expected_boundary=BlockingBoundary.RESOLVER_PRIVATE_ANSWER,
        resolver_answers=(("127.0.0.1",),),
        expected_resolver_calls=1,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-014",
        request=_request(
            "https://sandbox.example.test/orders",
            approval=_approved(),
        ),
        expected_boundary=BlockingBoundary.DNS_REBINDING,
        resolver_answers=(("8.8.8.8",), ("169.254.169.254",)),
        expected_resolver_calls=2,
    ),
    ExecutionPolicyFixtureV1(
        id="EXEC-POL-015",
        request=_request(
            "https://sandbox.example.test/orders",
            approval=_approved(),
        ),
        expected_boundary=BlockingBoundary.EXECUTOR_UNAVAILABLE,
        resolver_answers=(("8.8.8.8",), ("8.8.8.8",)),
        expected_resolver_calls=2,
    ),
)
