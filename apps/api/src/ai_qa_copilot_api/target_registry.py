"""Server-side target registry and fake-only network validation for EXEC-002."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import ipaddress
from typing import Final, Protocol
from urllib.parse import SplitResult, urlsplit


TARGET_REGISTRY_SCHEMA_VERSION: Final = "target-registry/v1"
DEFAULT_HTTPS_PORT: Final = 443

_METADATA_HOSTS: Final = frozenset(
    {
        "instance-data",
        "instance-data.ec2.internal",
        "metadata.azure.internal",
        "metadata.google.internal",
    }
)


class TargetId(StrEnum):
    """Stable server-side identifiers; callers never supply a target URL."""

    SYNTHETIC_ORDER_API = "synthetic-order-api"


class TargetValidationBoundary(StrEnum):
    """The precise boundary that rejected a target or resolver response."""

    UNKNOWN_TARGET_ID = "unknown_target_id"
    DUPLICATE_TARGET_ID = "duplicate_target_id"
    EMPTY_REGISTRY = "empty_registry"
    MALFORMED_URL = "malformed_target_url"
    HTTPS_REQUIRED = "https_required"
    USERINFO_FORBIDDEN = "userinfo_forbidden"
    NONSTANDARD_PORT = "nonstandard_https_port"
    PATH_FORBIDDEN = "target_path_forbidden"
    QUERY_OR_FRAGMENT_FORBIDDEN = "query_or_fragment_forbidden"
    REDIRECTS_ENABLED = "redirects_must_be_disabled"
    METADATA_TARGET = "metadata_target_forbidden"
    LITERAL_IP = "literal_ip_forbidden"
    ALTERNATE_IP_NOTATION = "alternate_ip_notation_forbidden"
    EMPTY_RESOLVER_ANSWER = "empty_resolver_answer"
    INVALID_RESOLVER_ANSWER = "invalid_resolver_answer"
    RESTRICTED_RESOLVER_ANSWER = "restricted_resolver_answer"
    DNS_REBINDING = "dns_rebinding_detected"


class TargetValidationError(ValueError):
    """Raised when a target cannot pass the default-deny network policy."""

    def __init__(
        self,
        boundary: TargetValidationBoundary,
        message: str,
    ) -> None:
        super().__init__(message)
        self.boundary = boundary


class AddressResolver(Protocol):
    """Injected resolver contract; implementations must not be created here."""

    def resolve(self, hostname: str) -> tuple[str, ...]:
        """Return the addresses currently associated with one hostname."""


@dataclass(frozen=True)
class TargetConfiguration:
    """One immutable, server-maintained target definition."""

    id: TargetId
    base_url: str
    redirects_allowed: bool = False
    schema_version: str = TARGET_REGISTRY_SCHEMA_VERSION


@dataclass(frozen=True)
class TargetRegistry:
    """A closed registry of fixed server-side target definitions."""

    targets: tuple[TargetConfiguration, ...]

    def __post_init__(self) -> None:
        if not self.targets:
            raise TargetValidationError(
                TargetValidationBoundary.EMPTY_REGISTRY,
                "Target registry must contain at least one target.",
            )

        target_ids = tuple(target.id for target in self.targets)
        if len(set(target_ids)) != len(target_ids):
            raise TargetValidationError(
                TargetValidationBoundary.DUPLICATE_TARGET_ID,
                "Target registry contains duplicate target identifiers.",
            )

        for target in self.targets:
            _parse_target_origin(target)

    def get(self, target_id: str) -> TargetConfiguration:
        """Return one configured target without accepting a caller-provided URL."""

        try:
            expected_id = TargetId(target_id)
        except ValueError as error:
            raise TargetValidationError(
                TargetValidationBoundary.UNKNOWN_TARGET_ID,
                "Target identifier is not registered.",
            ) from error

        for target in self.targets:
            if target.id is expected_id:
                return target

        raise TargetValidationError(
            TargetValidationBoundary.UNKNOWN_TARGET_ID,
            "Target identifier is not registered.",
        )


@dataclass(frozen=True)
class ValidatedTarget:
    """A target proven eligible for a future executor, but never contacted."""

    id: TargetId
    origin: str
    hostname: str
    port: int
    resolved_addresses: tuple[str, ...]
    redirects_allowed: bool = False


@dataclass(frozen=True)
class _TargetOrigin:
    """Internal canonical representation of one configured target URL."""

    hostname: str
    port: int
    origin: str


def _parse_target_origin(target: TargetConfiguration) -> _TargetOrigin:
    if target.schema_version != TARGET_REGISTRY_SCHEMA_VERSION:
        raise TargetValidationError(
            TargetValidationBoundary.MALFORMED_URL,
            "Target configuration has an unsupported schema version.",
        )
    if target.redirects_allowed:
        raise TargetValidationError(
            TargetValidationBoundary.REDIRECTS_ENABLED,
            "Target redirects must remain disabled.",
        )

    parsed = _parse_url(target.base_url)

    if parsed.scheme != "https":
        raise TargetValidationError(
            TargetValidationBoundary.HTTPS_REQUIRED,
            "Target URL must use HTTPS.",
        )
    if parsed.username is not None or parsed.password is not None:
        raise TargetValidationError(
            TargetValidationBoundary.USERINFO_FORBIDDEN,
            "Target URL must not include user information.",
        )
    if parsed.query or parsed.fragment:
        raise TargetValidationError(
            TargetValidationBoundary.QUERY_OR_FRAGMENT_FORBIDDEN,
            "Target URL must not include a query string or fragment.",
        )
    if parsed.path not in ("", "/"):
        raise TargetValidationError(
            TargetValidationBoundary.PATH_FORBIDDEN,
            "Target URL must identify an origin, not a resource path.",
        )

    hostname = _normalized_hostname(parsed)
    _validate_hostname(hostname)

    try:
        port = parsed.port or DEFAULT_HTTPS_PORT
    except ValueError as error:
        raise TargetValidationError(
            TargetValidationBoundary.MALFORMED_URL,
            "Target URL has an invalid port.",
        ) from error

    if port != DEFAULT_HTTPS_PORT:
        raise TargetValidationError(
            TargetValidationBoundary.NONSTANDARD_PORT,
            "Target URL must use the standard HTTPS port.",
        )

    return _TargetOrigin(
        hostname=hostname,
        port=port,
        origin=f"https://{hostname}",
    )


def _parse_url(value: str) -> SplitResult:
    if not value or value != value.strip() or "\x00" in value:
        raise TargetValidationError(
            TargetValidationBoundary.MALFORMED_URL,
            "Target URL is malformed.",
        )

    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise TargetValidationError(
            TargetValidationBoundary.MALFORMED_URL,
            "Target URL is malformed.",
        ) from error

    if not parsed.scheme or not parsed.netloc or parsed.hostname is None:
        raise TargetValidationError(
            TargetValidationBoundary.MALFORMED_URL,
            "Target URL must include a scheme and hostname.",
        )
    return parsed


def _normalized_hostname(parsed: SplitResult) -> str:
    hostname = parsed.hostname
    if hostname is None:
        raise TargetValidationError(
            TargetValidationBoundary.MALFORMED_URL,
            "Target URL must include a hostname.",
        )
    return hostname.lower().rstrip(".")


def _validate_hostname(hostname: str) -> None:
    if hostname in _METADATA_HOSTS:
        raise TargetValidationError(
            TargetValidationBoundary.METADATA_TARGET,
            "Metadata targets are forbidden.",
        )
    if _is_literal_ip(hostname):
        raise TargetValidationError(
            TargetValidationBoundary.LITERAL_IP,
            "Literal IP target hosts are forbidden.",
        )
    if _looks_like_alternate_ip_notation(hostname):
        raise TargetValidationError(
            TargetValidationBoundary.ALTERNATE_IP_NOTATION,
            "Alternate IP notation is forbidden.",
        )


def _is_literal_ip(hostname: str) -> bool:
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return True


def _looks_like_alternate_ip_notation(hostname: str) -> bool:
    if hostname.lower().startswith("0x"):
        return True
    if hostname.isdecimal():
        return True

    labels = hostname.split(".")
    return (
        len(labels) == 4
        and all(label.isdecimal() for label in labels)
        and any(len(label) > 1 and label.startswith("0") for label in labels)
    )


def _validated_public_answers(addresses: tuple[str, ...]) -> tuple[str, ...]:
    if not addresses:
        raise TargetValidationError(
            TargetValidationBoundary.EMPTY_RESOLVER_ANSWER,
            "Resolver returned no addresses for the target.",
        )

    normalized_addresses: list[str] = []
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise TargetValidationError(
                TargetValidationBoundary.INVALID_RESOLVER_ANSWER,
                "Resolver returned a non-IP address.",
            ) from error

        if not address.is_global:
            raise TargetValidationError(
                TargetValidationBoundary.RESTRICTED_RESOLVER_ANSWER,
                "Resolver returned a private, loopback, metadata, or reserved address.",
            )
        normalized_addresses.append(address.compressed)

    return tuple(sorted(set(normalized_addresses)))


DEFAULT_TARGET_REGISTRY: Final = TargetRegistry(
    targets=(
        TargetConfiguration(
            id=TargetId.SYNTHETIC_ORDER_API,
            base_url="https://mock-order-api.synthetic.test",
        ),
    )
)


def validate_registered_target(
    target_id: str,
    *,
    resolver: AddressResolver,
    registry: TargetRegistry = DEFAULT_TARGET_REGISTRY,
) -> ValidatedTarget:
    """Resolve and revalidate one server-side target without sending traffic."""

    target = registry.get(target_id)
    origin = _parse_target_origin(target)

    first_answers = _validated_public_answers(resolver.resolve(origin.hostname))
    second_answers = _validated_public_answers(resolver.resolve(origin.hostname))

    if first_answers != second_answers:
        raise TargetValidationError(
            TargetValidationBoundary.DNS_REBINDING,
            "Target DNS answers changed during validation.",
        )

    return ValidatedTarget(
        id=target.id,
        origin=origin.origin,
        hostname=origin.hostname,
        port=origin.port,
        resolved_addresses=first_answers,
        redirects_allowed=False,
    )
