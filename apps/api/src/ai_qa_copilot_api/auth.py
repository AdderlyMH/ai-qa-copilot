"""Deterministic authentication and principal boundaries for the API."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Protocol
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException, Request, status
from jwt import PyJWK, PyJWKClient
from jwt.exceptions import PyJWTError


COGNITO_SIGNING_ALGORITHM: Final = "RS256"
COGNITO_TOKEN_USE: Final = "access"
JWKS_TIMEOUT_SECONDS: Final = 5.0
JWKS_CACHE_SECONDS: Final = 300.0
OWNER_REQUIRED_DETAIL: Final = "Owner access required"
INVALID_CREDENTIALS_DETAIL: Final = "Invalid or missing credentials"
GUEST_READ_ONLY_DETAIL: Final = "Guest access is read-only"


class AuthConfigurationError(RuntimeError):
    """Raised when authentication configuration is unsafe or incomplete."""


class InvalidCredentialsError(Exception):
    """Raised when a Cognito credential cannot be trusted."""


class OwnerResolutionFailure(Exception):
    """Trusted owner-resolution denial retained for API audit handling."""

    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        reason: str,
        actor_id: str | None = None,
    ) -> None:
        super().__init__(detail)
        if status_code not in {
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        }:
            raise ValueError("Owner resolution supports only 401 or 403 denials")
        self.status_code = status_code
        self.detail = detail
        self.reason = reason
        self.actor_id = actor_id

    def as_http_exception(self) -> HTTPException:
        headers = (
            {"WWW-Authenticate": "Bearer"}
            if self.status_code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        return HTTPException(
            status_code=self.status_code,
            detail=self.detail,
            headers=headers,
        )


class AppEnvironment(StrEnum):
    """Supported application deployment environments."""

    LOCAL = "local"
    PREVIEW = "preview"
    PRODUCTION = "production"


@dataclass(frozen=True)
class OwnerIdentity:
    """Immutable server-side Cognito identity mapping for the single owner."""

    issuer: str
    subject: str


@dataclass(frozen=True)
class CognitoSettings:
    """Server-side configuration needed to validate Cognito access tokens."""

    issuer: str
    client_id: str
    owner_subject: str

    @property
    def owner_identity(self) -> OwnerIdentity:
        return OwnerIdentity(issuer=self.issuer, subject=self.owner_subject)

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/.well-known/jwks.json"

    def validate(self) -> None:
        for name, value in (
            ("COGNITO_ISSUER", self.issuer),
            ("COGNITO_CLIENT_ID", self.client_id),
            ("COGNITO_OWNER_SUBJECT", self.owner_subject),
        ):
            if not value or value != value.strip():
                raise AuthConfigurationError(f"{name} must be a non-empty value")

        issuer = urlsplit(self.issuer)
        if (
            issuer.scheme != "https"
            or issuer.hostname is None
            or issuer.username is not None
            or issuer.password is not None
            or issuer.query
            or issuer.fragment
        ):
            raise AuthConfigurationError(
                "COGNITO_ISSUER must be an HTTPS issuer URL without credentials, "
                "query, or fragment"
            )


@dataclass(frozen=True)
class AuthSettings:
    """Complete server-side authentication configuration."""

    app_env: AppEnvironment
    local_auth_bypass_enabled: bool
    cognito: CognitoSettings | None

    @classmethod
    def from_environment(cls) -> AuthSettings:
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, environment: Mapping[str, str]) -> AuthSettings:
        raw_app_env = environment.get("APP_ENV", "").strip()
        if not raw_app_env:
            raise AuthConfigurationError("APP_ENV must be explicitly configured")
        try:
            app_env = AppEnvironment(raw_app_env)
        except ValueError as error:
            raise AuthConfigurationError(
                "APP_ENV must be one of: local, preview, production"
            ) from error

        raw_bypass = environment.get("LOCAL_AUTH_BYPASS_ENABLED", "false")
        normalized_bypass = raw_bypass.strip().lower()
        if normalized_bypass not in {"true", "false"}:
            raise AuthConfigurationError(
                "LOCAL_AUTH_BYPASS_ENABLED must be exactly true or false"
            )
        local_auth_bypass_enabled = normalized_bypass == "true"

        cognito_values = {
            "issuer": environment.get("COGNITO_ISSUER", "").strip(),
            "client_id": environment.get("COGNITO_CLIENT_ID", "").strip(),
            "owner_subject": environment.get("COGNITO_OWNER_SUBJECT", "").strip(),
        }
        configured_values = [bool(value) for value in cognito_values.values()]
        if any(configured_values) and not all(configured_values):
            raise AuthConfigurationError(
                "COGNITO_ISSUER, COGNITO_CLIENT_ID, and COGNITO_OWNER_SUBJECT "
                "must be configured together"
            )

        cognito = CognitoSettings(**cognito_values) if all(configured_values) else None
        settings = cls(
            app_env=app_env,
            local_auth_bypass_enabled=local_auth_bypass_enabled,
            cognito=cognito,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.local_auth_bypass_enabled and self.app_env is not AppEnvironment.LOCAL:
            raise AuthConfigurationError(
                "LOCAL_AUTH_BYPASS_ENABLED may be true only when APP_ENV=local"
            )
        if self.cognito is not None:
            self.cognito.validate()
        if self.app_env is not AppEnvironment.LOCAL and self.cognito is None:
            raise AuthConfigurationError(
                "Preview and production require complete Cognito configuration"
            )


@dataclass(frozen=True)
class CognitoIdentity:
    """Trusted immutable claims retained after full Cognito token validation."""

    issuer: str
    subject: str


@dataclass(frozen=True)
class CognitoOwnerPrincipal:
    """Owner principal authenticated through the configured Cognito mapping."""

    issuer: str
    subject: str
    principal_type: Literal["owner"] = "owner"
    authentication_source: Literal["cognito"] = "cognito"


@dataclass(frozen=True)
class LocalDevelopmentOwnerPrincipal:
    """Local-only development principal; never a Cognito identity."""

    principal_type: Literal["owner"] = "owner"
    authentication_source: Literal["local_bypass"] = "local_bypass"


OwnerPrincipal = CognitoOwnerPrincipal | LocalDevelopmentOwnerPrincipal


@dataclass(frozen=True)
class AnonymousGuestPrincipal:
    """Anonymous principal with no authority beyond a future demo read route."""

    principal_type: Literal["guest"] = "guest"
    authentication_source: Literal["anonymous"] = "anonymous"
    access_scope: Literal["server_selected_demo_publication"] = (
        "server_selected_demo_publication"
    )
    read_only: Literal[True] = True


PublicDemoPrincipal = OwnerPrincipal | AnonymousGuestPrincipal


class JwkProvider(Protocol):
    """Minimum JWKS key-resolution interface used by the validator."""

    def get_signing_key_from_jwt(self, token: str | bytes) -> PyJWK: ...


class TokenValidator(Protocol):
    """Authentication adapter that returns only trusted immutable identity."""

    def validate(self, token: str) -> CognitoIdentity: ...


class CognitoJwtValidator:
    """Validate Cognito access tokens against issuer-derived JWKS keys."""

    def __init__(
        self,
        settings: CognitoSettings,
        jwk_provider: JwkProvider | None = None,
    ) -> None:
        settings.validate()
        self._settings = settings
        self._jwk_provider = jwk_provider or PyJWKClient(
            settings.jwks_url,
            cache_jwk_set=True,
            lifespan=JWKS_CACHE_SECONDS,
            timeout=JWKS_TIMEOUT_SECONDS,
        )

    def validate(self, token: str) -> CognitoIdentity:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != COGNITO_SIGNING_ALGORITHM:
                raise InvalidCredentialsError("Unapproved token algorithm")
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid:
                raise InvalidCredentialsError("Missing token key identifier")

            signing_key = self._jwk_provider.get_signing_key_from_jwt(token)
            if signing_key.algorithm_name != COGNITO_SIGNING_ALGORITHM:
                raise InvalidCredentialsError("Unapproved JWKS signing algorithm")

            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[COGNITO_SIGNING_ALGORITHM],
                issuer=self._settings.issuer,
                options={
                    "require": ["exp", "iss", "sub", "client_id", "token_use"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    # Cognito access tokens bind the app client in client_id.
                    # An optional aud claim is a resource-server identifier.
                    "verify_aud": False,
                },
            )
        except InvalidCredentialsError:
            raise
        except (PyJWTError, TypeError, ValueError) as error:
            raise InvalidCredentialsError("Cognito token validation failed") from error

        issuer = self._required_string_claim(claims, "iss")
        subject = self._required_string_claim(claims, "sub")
        client_id = self._required_string_claim(claims, "client_id")
        token_use = self._required_string_claim(claims, "token_use")
        if client_id != self._settings.client_id:
            raise InvalidCredentialsError("Unexpected Cognito client ID")
        if token_use != COGNITO_TOKEN_USE:
            raise InvalidCredentialsError("Unexpected Cognito token use")
        return CognitoIdentity(issuer=issuer, subject=subject)

    @staticmethod
    def _required_string_claim(claims: Mapping[str, object], name: str) -> str:
        value = claims.get(name)
        if not isinstance(value, str) or not value:
            raise InvalidCredentialsError(f"Invalid {name} claim")
        return value


class AuthBoundary:
    """Deterministic server-side authentication and principal authorization."""

    def __init__(
        self,
        settings: AuthSettings,
        token_validator: TokenValidator | None = None,
    ) -> None:
        settings.validate()
        if token_validator is not None and settings.cognito is None:
            raise AuthConfigurationError(
                "A token validator requires complete Cognito configuration"
            )
        self._settings = settings
        self._token_validator = token_validator or (
            CognitoJwtValidator(settings.cognito)
            if settings.cognito is not None
            else None
        )

    def resolve_owner(self, request: Request) -> OwnerPrincipal:
        """Resolve an owner or raise an auditable trusted denial."""

        if self._settings.local_auth_bypass_enabled:
            return LocalDevelopmentOwnerPrincipal()

        token = self._bearer_token(request.headers.get("Authorization"))
        if token is None or self._token_validator is None:
            raise OwnerResolutionFailure(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=INVALID_CREDENTIALS_DETAIL,
                reason="invalid_or_missing_credentials",
            )

        try:
            identity = self._token_validator.validate(token)
        except InvalidCredentialsError:
            raise OwnerResolutionFailure(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=INVALID_CREDENTIALS_DETAIL,
                reason="invalid_or_missing_credentials",
            ) from None

        cognito = self._settings.cognito
        if cognito is None:
            raise OwnerResolutionFailure(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=INVALID_CREDENTIALS_DETAIL,
                reason="invalid_or_missing_credentials",
            )
        if OwnerIdentity(identity.issuer, identity.subject) != cognito.owner_identity:
            raise OwnerResolutionFailure(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=OWNER_REQUIRED_DETAIL,
                reason="valid_non_owner",
                actor_id=identity.subject,
            )
        return CognitoOwnerPrincipal(
            issuer=identity.issuer,
            subject=identity.subject,
        )

    def require_owner(self, request: Request) -> OwnerPrincipal:
        try:
            return self.resolve_owner(request)
        except OwnerResolutionFailure as error:
            raise error.as_http_exception() from None

    def resolve_public_demo_principal(self, request: Request) -> PublicDemoPrincipal:
        """Resolve an optional trusted owner; otherwise use the anonymous guest."""

        if self._settings.local_auth_bypass_enabled:
            return LocalDevelopmentOwnerPrincipal()
        if request.headers.get("Authorization") is None:
            return AnonymousGuestPrincipal()
        return self.resolve_owner(request)

    @staticmethod
    def require_anonymous_guest_read(request: Request) -> AnonymousGuestPrincipal:
        if request.method not in {"GET", "HEAD"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=GUEST_READ_ONLY_DETAIL,
            )
        return AnonymousGuestPrincipal()

    @staticmethod
    def _bearer_token(authorization: str | None) -> str | None:
        if authorization is None:
            return None
        scheme, separator, credentials = authorization.partition(" ")
        token = credentials.strip()
        if (
            not separator
            or scheme.lower() != "bearer"
            or not token
            or any(character.isspace() for character in token)
        ):
            return None
        return token


def _boundary_from_request(request: Request) -> AuthBoundary:
    boundary = getattr(request.app.state, "auth_boundary", None)
    if not isinstance(boundary, AuthBoundary):
        raise RuntimeError("Authentication boundary was not initialized at startup")
    return boundary


def require_owner(request: Request) -> OwnerPrincipal:
    """FastAPI dependency for deterministic owner-only authorization."""

    return _boundary_from_request(request).require_owner(request)


def require_anonymous_guest_read(request: Request) -> AnonymousGuestPrincipal:
    """FastAPI dependency for future read-only server-selected demo routes."""

    return _boundary_from_request(request).require_anonymous_guest_read(request)
