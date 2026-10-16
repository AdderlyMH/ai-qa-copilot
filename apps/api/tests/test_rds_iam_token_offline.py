"""RDS IAM authentication tokens are signed locally (ADR-020, ADR-018).

ADR-018 assumed that the parser can generate its RDS IAM database
authentication token without a network call, because the parser subnet has
no route to AWS APIs. This test proves only that boto3's
``generate_db_auth_token`` signs the token locally with SigV4 and opens no
connection and resolves no host. It does not show that IAM authentication is
stable on a 1 GiB db.t4g.micro instance (ADR-020: unverified; AWS states 300 to
1000 MiB extra memory is needed), and it does not connect to any database.
Wiring the token into the parser engine is INFRA-008 scope.

The credentials are fake and deliberately not shaped like AWS keys.
"""

from __future__ import annotations

from pathlib import Path
import socket
from typing import Any
from urllib.parse import parse_qs

import boto3
import pytest


FAKE_HOST = "parser-db.example-instance.us-east-1.rds.amazonaws.com"
FAKE_PORT = 5432
FAKE_USER = "parser_reader"
REGION = "us-east-1"


@pytest.fixture
def network_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """Block every outbound connection and DNS lookup, recording any attempt."""

    attempts: list[str] = []

    def refuse_connect(self: socket.socket, address: Any) -> None:
        del self, address
        attempts.append("connect")
        raise OSError("network access is blocked in this test")

    def refuse_getaddrinfo(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        attempts.append("getaddrinfo")
        raise OSError("DNS resolution is blocked in this test")

    for name in (
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ENDPOINT_URL",
        "AWS_ENDPOINT_URL_RDS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "missing-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "missing-creds"))
    monkeypatch.setattr(socket.socket, "connect", refuse_connect)
    monkeypatch.setattr(socket, "getaddrinfo", refuse_getaddrinfo)
    return attempts


def offline_rds_client() -> Any:
    session = boto3.session.Session(
        aws_access_key_id="fake-access-key-id-for-offline-test",
        aws_secret_access_key="fake-secret-key-for-offline-test",
        aws_session_token="fake-session-token-for-offline-test",
        region_name=REGION,
    )
    return session.client("rds")


def token_query(token: str) -> dict[str, list[str]]:
    prefix, separator, query = token.partition("?")
    assert separator == "?"
    assert prefix == f"{FAKE_HOST}:{FAKE_PORT}/"
    return parse_qs(query)


def test_token_is_generated_with_no_network_call(network_blocked: list[str]) -> None:
    client = offline_rds_client()

    token = client.generate_db_auth_token(
        DBHostname=FAKE_HOST, Port=FAKE_PORT, DBUsername=FAKE_USER, Region=REGION
    )

    assert isinstance(token, str) and token
    assert network_blocked == []


def test_token_carries_the_sigv4_query_parameters_host_and_user(
    network_blocked: list[str],
) -> None:
    token = offline_rds_client().generate_db_auth_token(
        DBHostname=FAKE_HOST, Port=FAKE_PORT, DBUsername=FAKE_USER, Region=REGION
    )
    query = token_query(token)

    assert token.startswith(f"{FAKE_HOST}:{FAKE_PORT}/?")
    assert query["Action"] == ["connect"]
    assert query["DBUser"] == [FAKE_USER]
    for parameter in (
        "X-Amz-Algorithm",
        "X-Amz-Credential",
        "X-Amz-Expires",
        "X-Amz-Signature",
        "X-Amz-Date",
        "X-Amz-SignedHeaders",
        "X-Amz-Security-Token",
    ):
        assert parameter in query, parameter
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert query["X-Amz-Credential"][0].endswith(f"/{REGION}/rds-db/aws4_request")
    assert query["X-Amz-Expires"] == ["900"]
    assert len(query["X-Amz-Signature"][0]) == 64
    assert network_blocked == []


def test_tokens_for_different_users_differ_and_stay_offline(
    network_blocked: list[str],
) -> None:
    client = offline_rds_client()

    first = client.generate_db_auth_token(
        DBHostname=FAKE_HOST, Port=FAKE_PORT, DBUsername=FAKE_USER, Region=REGION
    )
    second = client.generate_db_auth_token(
        DBHostname=FAKE_HOST, Port=FAKE_PORT, DBUsername="another_user", Region=REGION
    )

    assert token_query(first)["DBUser"] == [FAKE_USER]
    assert token_query(second)["DBUser"] == ["another_user"]
    assert (
        token_query(first)["X-Amz-Signature"] != token_query(second)["X-Amz-Signature"]
    )
    assert network_blocked == []


def test_the_block_is_effective(network_blocked: list[str]) -> None:
    with pytest.raises(OSError):
        socket.getaddrinfo(FAKE_HOST, FAKE_PORT)
    with socket.socket() as probe, pytest.raises(OSError):
        probe.connect(("192.0.2.1", FAKE_PORT))

    assert network_blocked == ["getaddrinfo", "connect"]
