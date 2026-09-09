"""Pinned, bounded HTTPS transport for the restricted execution seam."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
import ipaddress
import ssl
from time import monotonic
from typing import Final

import httpcore
from httpcore._backends.base import SOCKET_OPTION
import httpx

from ai_qa_copilot_api.generated_tests import HttpMethod
from ai_qa_copilot_api.restricted_execution import TransportResponse


_FORBIDDEN_REQUEST_HEADERS: Final = frozenset(
    {
        "authorization",
        "cookie",
        "host",
        "proxy-authorization",
        "set-cookie",
        "x-forwarded-for",
    }
)


class RestrictedHttpTransportError(RuntimeError):
    """Raised when the pinned transport cannot safely send one request."""


class RestrictedHttpTransportTimeout(TimeoutError):
    """Raised when the pinned transport reaches its approved time limit."""


class PinnedAddressNetworkBackend(httpcore.NetworkBackend):
    """Route one approved hostname to one already-validated numeric address."""

    def __init__(
        self,
        *,
        hostname: str,
        port: int,
        address: str,
        delegate: httpcore.NetworkBackend,
    ) -> None:
        self._hostname = hostname
        self._port = port
        self._address = str(ipaddress.ip_address(address))
        self._delegate = delegate

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        if host != self._hostname or port != self._port:
            raise httpcore.ConnectError("Pinned transport origin did not match")

        return self._delegate.connect_tcp(
            host=self._address,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        del path, timeout, socket_options
        raise httpcore.ConnectError("Unix sockets are forbidden")

    def sleep(self, seconds: float) -> None:
        self._delegate.sleep(seconds)


class _DeadlineNetworkStream(httpcore.NetworkStream):
    """Apply one total request deadline to every network operation."""

    def __init__(
        self,
        *,
        delegate: httpcore.NetworkStream,
        deadline: float,
        clock: Callable[[], float],
    ) -> None:
        self._delegate = delegate
        self._deadline = deadline
        self._clock = clock

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._delegate.read(
            max_bytes,
            timeout=self._remaining_timeout(timeout),
        )

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._delegate.write(
            buffer,
            timeout=self._remaining_timeout(timeout),
        )

    def close(self) -> None:
        self._delegate.close()

    def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore.NetworkStream:
        stream = self._delegate.start_tls(
            ssl_context,
            server_hostname=server_hostname,
            timeout=self._remaining_timeout(timeout),
        )
        return _DeadlineNetworkStream(
            delegate=stream,
            deadline=self._deadline,
            clock=self._clock,
        )

    def get_extra_info(self, info: str) -> object | None:
        value: object = self._delegate.get_extra_info(info)
        return value

    def _remaining_timeout(self, requested_timeout: float | None) -> float:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise httpcore.ReadTimeout("Restricted execution deadline exceeded")
        return (
            min(requested_timeout, remaining)
            if requested_timeout is not None
            else remaining
        )


class DeadlineNetworkBackend(httpcore.NetworkBackend):
    """Wrap a network backend so its TCP connection shares one total deadline."""

    def __init__(
        self,
        *,
        delegate: httpcore.NetworkBackend,
        deadline: float,
        clock: Callable[[], float],
    ) -> None:
        self._delegate = delegate
        self._deadline = deadline
        self._clock = clock

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        stream = self._delegate.connect_tcp(
            host=host,
            port=port,
            timeout=self._remaining_timeout(timeout),
            local_address=local_address,
            socket_options=socket_options,
        )
        return _DeadlineNetworkStream(
            delegate=stream,
            deadline=self._deadline,
            clock=self._clock,
        )

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        stream = self._delegate.connect_unix_socket(
            path=path,
            timeout=self._remaining_timeout(timeout),
            socket_options=socket_options,
        )
        return _DeadlineNetworkStream(
            delegate=stream,
            deadline=self._deadline,
            clock=self._clock,
        )

    def sleep(self, seconds: float) -> None:
        if self._deadline - self._clock() <= 0:
            raise httpcore.ConnectTimeout("Restricted execution deadline exceeded")
        self._delegate.sleep(seconds)

    def _remaining_timeout(self, requested_timeout: float | None) -> float:
        remaining = self._deadline - self._clock()
        if remaining <= 0:
            raise httpcore.ConnectTimeout("Restricted execution deadline exceeded")
        return (
            min(requested_timeout, remaining)
            if requested_timeout is not None
            else remaining
        )


class _HttpcoreResponseStream(httpx.SyncByteStream):
    """Convert HTTP core stream failures into HTTPX transport failures."""

    def __init__(
        self,
        stream: Iterable[bytes],
        request: httpx.Request,
    ) -> None:
        self._stream = stream
        self._request = request

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self._stream
        except httpcore.TimeoutException as error:
            raise httpx.ReadTimeout(str(error), request=self._request) from error
        except httpcore.NetworkError as error:
            raise httpx.ReadError(str(error), request=self._request) from error
        except httpcore.ProtocolError as error:
            raise httpx.RemoteProtocolError(
                str(error), request=self._request
            ) from error

    def close(self) -> None:
        close = getattr(self._stream, "close", None)
        if callable(close):
            close()


class _PinnedHttpxTransport(httpx.BaseTransport):
    """HTTPX transport that preserves hostname TLS while pinning TCP by address."""

    def __init__(
        self,
        *,
        hostname: str,
        port: int,
        address: str,
        deadline: float,
        clock: Callable[[], float],
        network_backend_factory: Callable[[], httpcore.NetworkBackend],
    ) -> None:
        self._hostname = hostname
        self._port = port
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(
                verify=True,
                trust_env=False,
            ),
            max_connections=1,
            max_keepalive_connections=0,
            keepalive_expiry=0.0,
            http1=True,
            http2=False,
            retries=0,
            network_backend=DeadlineNetworkBackend(
                deadline=deadline,
                clock=clock,
                delegate=PinnedAddressNetworkBackend(
                    hostname=hostname,
                    port=port,
                    address=address,
                    delegate=network_backend_factory(),
                ),
            ),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.scheme != "https"
            or request.url.host != self._hostname
            or (request.url.port if request.url.port is not None else 443) != self._port
            or bool(request.url.userinfo)
            or bool(request.url.fragment)
        ):
            raise httpx.ConnectError(
                "Pinned transport request origin did not match",
                request=request,
            )

        if not isinstance(request.stream, httpx.SyncByteStream):
            raise httpx.TransportError(
                "Pinned transport requires a synchronous request stream",
                request=request,
            )

        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=self._port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )

        try:
            core_response = self._pool.handle_request(core_request)
        except httpcore.TimeoutException as error:
            raise httpx.ConnectTimeout(str(error), request=request) from error
        except httpcore.NetworkError as error:
            raise httpx.ConnectError(str(error), request=request) from error
        except httpcore.ProtocolError as error:
            raise httpx.RemoteProtocolError(str(error), request=request) from error

        stream = core_response.stream
        if not isinstance(stream, Iterable):
            raise httpx.TransportError(
                "Pinned transport requires a synchronous response stream",
                request=request,
            )

        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_HttpcoreResponseStream(stream, request),
            extensions=core_response.extensions,
            request=request,
        )

    def close(self) -> None:
        self._pool.close()


class PinnedHttpxExecutionTransport:
    """Send one bounded HTTPS request through the validated pinned address only."""

    def __init__(
        self,
        *,
        network_backend_factory: Callable[
            [], httpcore.NetworkBackend
        ] = httpcore.SyncBackend,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._network_backend_factory = network_backend_factory
        self._clock = clock

    def send(
        self,
        *,
        method: HttpMethod,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes | None,
        timeout_ms: int,
        max_response_bytes: int,
        follow_redirects: bool,
        resolved_address: str,
    ) -> TransportResponse:
        hostname, port = _validated_origin(url)
        _validate_request(
            headers=headers,
            body=body,
            timeout_ms=timeout_ms,
            max_response_bytes=max_response_bytes,
            follow_redirects=follow_redirects,
            resolved_address=resolved_address,
        )
        started_at = self._clock()
        timeout_seconds = timeout_ms / 1_000
        deadline = started_at + timeout_seconds

        transport = _PinnedHttpxTransport(
            hostname=hostname,
            port=port,
            address=resolved_address,
            deadline=deadline,
            clock=self._clock,
            network_backend_factory=self._network_backend_factory,
        )

        try:
            with httpx.Client(
                transport=transport,
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    method.value,
                    url,
                    headers=headers,
                    content=body,
                ) as response:
                    _require_identity_content_encoding(response)
                    response_body = _read_bounded_raw_body(
                        response=response,
                        max_response_bytes=max_response_bytes,
                    )
                    response_headers = tuple(response.headers.multi_items())
        except httpx.TimeoutException as error:
            raise RestrictedHttpTransportTimeout from error
        except httpx.HTTPError as error:
            raise RestrictedHttpTransportError from error

        elapsed_ms = max(0, round((self._clock() - started_at) * 1_000))
        return TransportResponse(
            status_code=response.status_code,
            headers=response_headers,
            body=response_body,
            elapsed_ms=elapsed_ms,
        )


def _validated_origin(url: str) -> tuple[str, int]:
    try:
        parsed = httpx.URL(url)
    except httpx.InvalidURL as error:
        raise RestrictedHttpTransportError("Request URL is invalid") from error

    if (
        parsed.scheme != "https"
        or parsed.host != "ai-qa-sandbox.onrender.com"
        or parsed.port not in (None, 443)
        or bool(parsed.userinfo)
        or bool(parsed.fragment)
    ):
        raise RestrictedHttpTransportError(
            "Pinned transport accepts only the registered HTTPS sandbox"
        )

    return parsed.host, 443


def _validate_request(
    *,
    headers: tuple[tuple[str, str], ...],
    body: bytes | None,
    timeout_ms: int,
    max_response_bytes: int,
    follow_redirects: bool,
    resolved_address: str,
) -> None:
    if follow_redirects:
        raise RestrictedHttpTransportError("Redirects are forbidden")
    if (
        not isinstance(timeout_ms, int)
        or isinstance(timeout_ms, bool)
        or timeout_ms <= 0
    ):
        raise RestrictedHttpTransportError("Request timeout is invalid")
    if (
        not isinstance(max_response_bytes, int)
        or isinstance(max_response_bytes, bool)
        or max_response_bytes <= 0
    ):
        raise RestrictedHttpTransportError("Response limit is invalid")
    if body is not None and not isinstance(body, bytes):
        raise RestrictedHttpTransportError("Request body is invalid")

    try:
        ipaddress.ip_address(resolved_address)
    except ValueError as error:
        raise RestrictedHttpTransportError("Pinned address is not numeric") from error

    for name, value in headers:
        if (
            not isinstance(name, str)
            or not isinstance(value, str)
            or name.lower() in _FORBIDDEN_REQUEST_HEADERS
        ):
            raise RestrictedHttpTransportError(
                "Request headers are not permitted by the pinned transport"
            )


def _require_identity_content_encoding(response: httpx.Response) -> None:
    content_encoding = response.headers.get("content-encoding", "identity")
    if content_encoding.strip().lower() not in ("", "identity"):
        raise RestrictedHttpTransportError("Compressed response bodies are forbidden")


def _read_bounded_raw_body(
    *,
    response: httpx.Response,
    max_response_bytes: int,
) -> bytes:
    limit = max_response_bytes + 1
    body = bytearray()

    for chunk in response.iter_raw():
        remaining = limit - len(body)
        if remaining <= 0:
            break
        body.extend(chunk[:remaining])
        if len(body) == limit:
            break

    return bytes(body)
