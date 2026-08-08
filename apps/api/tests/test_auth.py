from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, cast

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jwt import PyJWK
from jwt.algorithms import RSAAlgorithm

from ai_qa_copilot_api.auth import (
    AnonymousGuestPrincipal,
    AppEnvironment,
    AuthConfigurationError,
    AuthSettings,
    CognitoJwtValidator,
    CognitoOwnerPrincipal,
    CognitoSettings,
    LocalDevelopmentOwnerPrincipal,
    OwnerPrincipal,
    require_anonymous_guest_read,
    require_owner,
)
from ai_qa_copilot_api.main import create_app


ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_example"
CLIENT_ID = "client-id-example"
OWNER_SUBJECT = "owner-subject"
KEY_ID = "test-key"


class StaticJwkProvider:
    def __init__(self, key: PyJWK) -> None:
        self._key = key

    def get_signing_key_from_jwt(self, token: str | bytes) -> PyJWK:
        return self._key


def cognito_settings() -> CognitoSettings:
    return CognitoSettings(
        issuer=ISSUER,
        client_id=CLIENT_ID,
        owner_subject=OWNER_SUBJECT,
    )


def auth_settings(
    *,
    app_env: AppEnvironment = AppEnvironment.LOCAL,
    local_bypass: bool = False,
) -> AuthSettings:
    return AuthSettings(
        app_env=app_env,
        local_auth_bypass_enabled=local_bypass,
        cognito=cognito_settings(),
    )


def pyjwk(public_key: rsa.RSAPublicKey) -> PyJWK:
    raw_jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    return PyJWK.from_dict(raw_jwk, algorithm="RS256")


def access_token(
    private_key: rsa.RSAPrivateKey,
    **claim_overrides: object,
) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": OWNER_SUBJECT,
        "client_id": CLIENT_ID,
        "token_use": "access",
        "iat": now,
        "nbf": now - timedelta(seconds=1),
        "exp": now + timedelta(minutes=5),
    }
    claims.update(claim_overrides)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )


def validator(private_key: rsa.RSAPrivateKey) -> CognitoJwtValidator:
    return CognitoJwtValidator(
        cognito_settings(),
        StaticJwkProvider(pyjwk(private_key.public_key())),
    )


def app_with_auth(
    settings: AuthSettings,
    token_validator: CognitoJwtValidator | None,
) -> FastAPI:
    app = create_app(settings, token_validator)

    @app.get("/_test/owner")
    def owner_probe(
        principal: Annotated[OwnerPrincipal, Depends(require_owner)],
    ) -> dict[str, str]:
        return {
            "principal_type": principal.principal_type,
            "authentication_source": principal.authentication_source,
        }

    @app.api_route("/_test/guest", methods=["GET", "POST"])
    def guest_probe(
        principal: Annotated[
            AnonymousGuestPrincipal, Depends(require_anonymous_guest_read)
        ],
    ) -> dict[str, str | bool]:
        return {
            "principal_type": principal.principal_type,
            "access_scope": principal.access_scope,
            "read_only": principal.read_only,
        }

    return app


def test_owner_is_bound_only_to_configured_issuer_and_subject() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = app_with_auth(auth_settings(), validator(private_key))

    with TestClient(app) as client:
        response = client.get(
            "/_test/owner",
            headers={"Authorization": f"Bearer {access_token(private_key)}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "principal_type": "owner",
        "authentication_source": "cognito",
    }


def test_valid_non_owner_is_forbidden_even_with_owner_profile_claims() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = access_token(
        private_key,
        sub="different-subject",
        email="owner@example.invalid",
        name="Owner",
        **{"custom:role": "owner", "cognito:groups": ["owner"]},
    )
    app = app_with_auth(auth_settings(), validator(private_key))

    with TestClient(app) as client:
        response = client.get(
            "/_test/owner", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 403
    assert response.json() == {"detail": "Owner access required"}


def test_missing_credentials_are_unauthorized_and_identity_headers_are_ignored() -> (
    None
):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = app_with_auth(auth_settings(), validator(private_key))

    with TestClient(app) as client:
        response = client.get(
            "/_test/owner",
            headers={
                "X-Role": "owner",
                "X-User-Id": OWNER_SUBJECT,
                "X-Email": "owner@example.invalid",
            },
        )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid or missing credentials"}


@pytest.mark.parametrize(
    ("token_factory", "case"),
    (
        (lambda key: "not-a-jwt", "malformed"),
        (
            lambda key: access_token(key, iss="https://issuer.example.invalid/pool"),
            "issuer",
        ),
        (lambda key: access_token(key, client_id="wrong-client"), "client_id"),
        (lambda key: access_token(key, token_use="id"), "token_use"),
        (
            lambda key: access_token(
                key, exp=datetime.now(timezone.utc) - timedelta(minutes=1)
            ),
            "expired",
        ),
        (
            lambda key: access_token(
                key, nbf=datetime.now(timezone.utc) + timedelta(minutes=1)
            ),
            "not_before",
        ),
    ),
)
def test_invalid_cognito_credentials_are_unauthorized(
    token_factory: Any,
    case: str,
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = app_with_auth(auth_settings(), validator(private_key))
    token = cast(str, token_factory(private_key))

    with TestClient(app) as client:
        response = client.get(
            "/_test/owner", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 401, case


def test_invalid_signature_is_unauthorized() -> None:
    trusted_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = app_with_auth(auth_settings(), validator(trusted_key))

    with TestClient(app) as client:
        response = client.get(
            "/_test/owner",
            headers={"Authorization": f"Bearer {access_token(attacker_key)}"},
        )

    assert response.status_code == 401


def test_unapproved_algorithm_is_unauthorized() -> None:
    trusted_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "iss": ISSUER,
            "sub": OWNER_SUBJECT,
            "client_id": CLIENT_ID,
            "token_use": "access",
            "exp": now + timedelta(minutes=5),
        },
        "not-a-cognito-key-with-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": KEY_ID},
    )
    app = app_with_auth(auth_settings(), validator(trusted_key))

    with TestClient(app) as client:
        response = client.get(
            "/_test/owner", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 401


def test_anonymous_guest_boundary_is_server_scoped_and_read_only() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app = app_with_auth(auth_settings(), validator(private_key))

    with TestClient(app) as client:
        read_response = client.get("/_test/guest")
        write_response = client.post("/_test/guest")

    assert read_response.status_code == 200
    assert read_response.json() == {
        "principal_type": "guest",
        "access_scope": "server_selected_demo_publication",
        "read_only": True,
    }
    assert write_response.status_code == 403
    assert write_response.json() == {"detail": "Guest access is read-only"}


def test_local_bypass_creates_only_a_local_development_owner() -> None:
    settings = AuthSettings(
        app_env=AppEnvironment.LOCAL,
        local_auth_bypass_enabled=True,
        cognito=None,
    )
    app = app_with_auth(settings, None)

    with TestClient(app) as client:
        response = client.get("/_test/owner")

    assert response.status_code == 200
    assert response.json() == {
        "principal_type": "owner",
        "authentication_source": "local_bypass",
    }


@pytest.mark.parametrize("app_env", (AppEnvironment.PREVIEW, AppEnvironment.PRODUCTION))
def test_non_local_environment_rejects_local_bypass_at_startup(
    app_env: AppEnvironment,
) -> None:
    settings = AuthSettings(
        app_env=app_env,
        local_auth_bypass_enabled=True,
        cognito=cognito_settings(),
    )
    app = create_app(settings)

    with pytest.raises(
        AuthConfigurationError,
        match="LOCAL_AUTH_BYPASS_ENABLED may be true only when APP_ENV=local",
    ):
        with TestClient(app):
            pass


def test_app_env_is_required_for_environment_configuration() -> None:
    app = create_app()

    with pytest.MonkeyPatch.context() as monkeypatch:
        for name in (
            "APP_ENV",
            "LOCAL_AUTH_BYPASS_ENABLED",
            "COGNITO_ISSUER",
            "COGNITO_CLIENT_ID",
            "COGNITO_OWNER_SUBJECT",
        ):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(AuthConfigurationError, match="APP_ENV must be explicitly"):
            with TestClient(app):
                pass


def test_principal_types_do_not_accept_client_identity_fields() -> None:
    owner_fields = set(CognitoOwnerPrincipal.__dataclass_fields__)
    local_fields = set(LocalDevelopmentOwnerPrincipal.__dataclass_fields__)

    assert owner_fields == {
        "issuer",
        "subject",
        "principal_type",
        "authentication_source",
    }
    assert local_fields == {"principal_type", "authentication_source"}
