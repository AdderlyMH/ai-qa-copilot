from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import httpcore
import pytest

from ai_qa_copilot_api.generated_tests import HttpMethod
from ai_qa_copilot_api.restricted_http_transport import (
    DeadlineNetworkBackend,
    PinnedAddressNetworkBackend,
    PinnedHttpxExecutionTransport,
    RestrictedHttpTransportError,
)


@dataclass
class RecordingStream(httpcore.NetworkStream):
    buffers: list[bytes]
    tls_hostnames: list[str | None]
    closed: bool = False

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        del max_bytes, timeout
        return self.buffers.pop(0) if self.buffers else b""

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        del buffer, timeout

    def close(self) -> None:
        self.closed = True

    def start_tls(
        self,
        ssl_context: object,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        del ssl_context, timeout
        self.tls_hostnames.append(server_hostname)
        return self

    def get_extra_info(self, info: str) -> object | None:
        if info == "ssl_object":
            return _HttpOneSslObject()
        return None


class _HttpOneSslObject:
    def selected_alpn_protocol(self) -> str:
        return "http/1.1"


@dataclass
class RecordingBackend(httpcore.NetworkBackend):
    buffers: list[bytes]
    tcp_calls: list[tuple[str, int]] = field(default_factory=list)
    tls_hostnames: list[str | None] = field(default_factory=list)

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[object] | None = None,
    ) -> httpcore.NetworkStream:
        del timeout, local_address, socket_options
        self.tcp_calls.append((host, port))
        return RecordingStream(list(self.buffers), self.tls_hostnames)

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[object] | None = None,
    ) -> httpcore.NetworkStream:
        del path, timeout, socket_options
        raise AssertionError("Unix sockets must not be used")

    def sleep(self, seconds: float) -> None:
        del seconds


def test_pinned_backend_uses_only_the_validated_numeric_address() -> None:
    delegate = RecordingBackend(buffers=[])
    backend = PinnedAddressNetworkBackend(
        hostname="ai-qa-sandbox.onrender.com",
        port=443,
        address="8.8.8.8",
        delegate=delegate,
    )

    backend.connect_tcp(host="ai-qa-sandbox.onrender.com", port=443)

    assert delegate.tcp_calls == [("8.8.8.8", 443)]

    with pytest.raises(httpcore.ConnectError):
        backend.connect_tcp(host="other.onrender.com", port=443)

    assert delegate.tcp_calls == [("8.8.8.8", 443)]


def test_pinned_http_transport_preserves_tls_hostname_and_bounds_response() -> None:
    backend = RecordingBackend(
        buffers=[
            b"HTTP/1.1 201 Created\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 20\r\n"
            b"\r\n"
            b"01234567890123456789"
        ]
    )
    transport = PinnedHttpxExecutionTransport(network_backend_factory=lambda: backend)

    response = transport.send(
        method=HttpMethod.POST,
        url="https://ai-qa-sandbox.onrender.com/api/orders",
        headers=(),
        body=b'{"quantity":2}',
        timeout_ms=500,
        max_response_bytes=10,
        follow_redirects=False,
        resolved_address="8.8.8.8",
    )

    assert backend.tcp_calls == [("8.8.8.8", 443)]
    assert backend.tls_hostnames == ["ai-qa-sandbox.onrender.com"]
    assert response.status_code == 201
    assert response.body == b"01234567890"
    assert response.elapsed_ms >= 0


def test_pinned_http_transport_rejects_redirects_before_connecting() -> None:
    backend = RecordingBackend(buffers=[])
    transport = PinnedHttpxExecutionTransport(network_backend_factory=lambda: backend)

    with pytest.raises(RestrictedHttpTransportError):
        transport.send(
            method=HttpMethod.GET,
            url="https://ai-qa-sandbox.onrender.com/api/products/missing",
            headers=(),
            body=None,
            timeout_ms=500,
            max_response_bytes=1_000,
            follow_redirects=True,
            resolved_address="8.8.8.8",
        )

    assert backend.tcp_calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://other.onrender.com/api/orders",
        "https://ai-qa-sandbox.onrender.com.attacker.test/api/orders",
        "https://*.onrender.com/api/orders",
        "http://ai-qa-sandbox.onrender.com/api/orders",
        "https://ai-qa-sandbox.onrender.com:8443/api/orders",
        "https://user:password@ai-qa-sandbox.onrender.com/api/orders",
        "https://ai-qa-sandbox.onrender.com/api/orders#fragment",
    ],
)
def test_unregistered_origins_and_url_overrides_never_connect(url: str) -> None:
    backend = RecordingBackend(buffers=[])
    transport = PinnedHttpxExecutionTransport(network_backend_factory=lambda: backend)

    with pytest.raises(RestrictedHttpTransportError):
        transport.send(
            method=HttpMethod.GET,
            url=url,
            headers=(),
            body=None,
            timeout_ms=500,
            max_response_bytes=1_000,
            follow_redirects=False,
            resolved_address="8.8.8.8",
        )

    assert backend.tcp_calls == []


@dataclass
class SequenceClock:
    values: tuple[float, ...]
    calls: int = 0

    def __call__(self) -> float:
        value = self.values[self.calls]
        self.calls += 1
        return value


@dataclass
class TimeoutRecordingStream(httpcore.NetworkStream):
    read_timeouts: list[float | None] = field(default_factory=list)

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        del max_bytes
        self.read_timeouts.append(timeout)
        return b""

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        del buffer, timeout

    def close(self) -> None:
        pass

    def start_tls(
        self,
        ssl_context: object,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        del ssl_context, server_hostname, timeout
        return self

    def get_extra_info(self, info: str) -> object | None:
        del info
        return None


@dataclass
class TimeoutRecordingBackend(httpcore.NetworkBackend):
    stream: TimeoutRecordingStream
    connect_timeouts: list[float | None] = field(default_factory=list)

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[object] | None = None,
    ) -> httpcore.NetworkStream:
        del host, port, local_address, socket_options
        self.connect_timeouts.append(timeout)
        return self.stream

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[object] | None = None,
    ) -> httpcore.NetworkStream:
        del path, timeout, socket_options
        raise AssertionError("Unix sockets must not be used")

    def sleep(self, seconds: float) -> None:
        del seconds


def test_deadline_backend_uses_remaining_budget_for_each_read() -> None:
    clock = SequenceClock((0.0, 0.25, 0.5))
    stream = TimeoutRecordingStream()
    delegate = TimeoutRecordingBackend(stream=stream)
    backend = DeadlineNetworkBackend(
        delegate=delegate,
        deadline=0.5,
        clock=clock,
    )

    wrapped = backend.connect_tcp(
        host="ai-qa-sandbox.onrender.com",
        port=443,
        timeout=1.0,
    )
    assert delegate.connect_timeouts == [0.5]

    assert wrapped.read(1, timeout=1.0) == b""
    assert stream.read_timeouts == [0.25]

    with pytest.raises(httpcore.ReadTimeout):
        wrapped.read(1, timeout=1.0)


def test_pinned_transport_rejects_compressed_response_before_body_decoding() -> None:
    backend = RecordingBackend(
        buffers=[
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Encoding: gzip\r\n"
            b"Content-Length: 20\r\n"
            b"\r\n"
            b"not-a-decoded-body"
        ]
    )
    transport = PinnedHttpxExecutionTransport(network_backend_factory=lambda: backend)

    with pytest.raises(RestrictedHttpTransportError):
        transport.send(
            method=HttpMethod.GET,
            url="https://ai-qa-sandbox.onrender.com/api/products/missing",
            headers=(),
            body=None,
            timeout_ms=500,
            max_response_bytes=1_000,
            follow_redirects=False,
            resolved_address="8.8.8.8",
        )

    assert backend.tcp_calls == [("8.8.8.8", 443)]
