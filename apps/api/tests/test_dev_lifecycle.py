from __future__ import annotations

import importlib
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[3]
STARTUP_TIMEOUT_SECONDS = 45.0
SHUTDOWN_TIMEOUT_SECONDS = 15.0
PORT_RELEASE_TIMEOUT_SECONDS = 1.0
WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
POSIX_FORCE_KILL_SIGNAL = 9


def load_task_runner() -> ModuleType:
    scripts_path = str(ROOT / "scripts")
    sys.path.insert(0, scripts_path)
    try:
        return importlib.import_module("tasks")
    finally:
        sys.path.remove(scripts_path)


TASK_RUNNER = load_task_runner()


def available_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def read_log(log_path: Path) -> str:
    return log_path.read_text(encoding="utf-8", errors="replace")


def send_posix_process_group_signal(process_id: int, process_signal: int) -> None:
    killpg = getattr(os, "killpg")
    killpg(process_id, process_signal)


def send_windows_break(process: subprocess.Popen[bytes]) -> None:
    break_event = getattr(signal, "CTRL_BREAK_EVENT")
    process.send_signal(break_event)


def start_dev(api_port: int, web_port: int, log_path: Path) -> subprocess.Popen[bytes]:
    command = (
        sys.executable,
        str(ROOT / "scripts" / "tasks.py"),
        "dev",
        "--port",
        str(api_port),
        "--web-port",
        str(web_port),
    )
    log = log_path.open("ab")
    try:
        if os.name == "nt":
            return subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=WINDOWS_CREATE_NEW_PROCESS_GROUP,
            )
        return subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log.close()


def wait_for_response(
    process: subprocess.Popen[bytes],
    url: str,
    expected_texts: tuple[str, ...],
    log_path: Path,
) -> None:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise AssertionError(
                f"dev exited with {return_code} before {url} was ready:\n"
                f"{read_log(log_path)}"
            )
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                body = response.read().decode()
            if response.status == 200 and all(
                expected_text in body for expected_text in expected_texts
            ):
                return
        except (OSError, TimeoutError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise AssertionError(
        f"dev did not make {url} ready within {STARTUP_TIMEOUT_SECONDS} seconds:\n"
        f"{read_log(log_path)}"
    )


def stop_dev(process: subprocess.Popen[bytes], log_path: Path) -> None:
    if process.poll() is not None:
        raise AssertionError(
            f"dev exited before shutdown was requested:\n{read_log(log_path)}"
        )
    if os.name == "nt":
        send_windows_break(process)
    else:
        send_posix_process_group_signal(process.pid, signal.SIGINT)
    try:
        return_code = process.wait(timeout=SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ("taskkill.exe", "/PID", str(process.pid), "/T", "/F"),
                check=False,
                capture_output=True,
            )
        else:
            send_posix_process_group_signal(process.pid, POSIX_FORCE_KILL_SIGNAL)
        process.wait()
        raise AssertionError(
            f"dev did not stop within {SHUTDOWN_TIMEOUT_SECONDS} seconds:\n"
            f"{read_log(log_path)}"
        )
    assert return_code == 0, read_log(log_path)


def port_accepts_connections(host: str, port: int) -> bool:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for family, socket_type, protocol, _, address in addresses:
        with socket.socket(family, socket_type, protocol) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(address) == 0:
                return True
    return False


def assert_port_released(host: str, port: int) -> None:
    deadline = time.monotonic() + PORT_RELEASE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not port_accepts_connections(host, port):
            return
        time.sleep(0.05)
    raise AssertionError(f"{host}:{port} remained in use after dev stopped")


def force_stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ("taskkill.exe", "/PID", str(process.pid), "/T", "/F"),
            check=False,
            capture_output=True,
        )
    else:
        send_posix_process_group_signal(process.pid, POSIX_FORCE_KILL_SIGNAL)
    process.wait()


def test_windows_assignment_failure_does_not_release_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if os.name != "nt":
        pytest.skip("Windows Job Object failure path")

    marker = tmp_path / "target-started"

    def fail_assignment(process: subprocess.Popen[bytes], job_handle: int) -> None:
        del process, job_handle
        raise RuntimeError("injected assignment failure")

    monkeypatch.setattr(
        TASK_RUNNER,
        "assign_windows_process_to_job",
        fail_assignment,
    )
    command = (
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
        str(marker),
    )

    with pytest.raises(RuntimeError, match="injected assignment failure"):
        start_managed_process = getattr(TASK_RUNNER, "start_managed_process")
        start_managed_process(command, None)

    time.sleep(0.2)
    assert not marker.exists()


def test_dev_releases_both_ports_and_restarts(tmp_path: Path) -> None:
    api_port = available_port()
    web_port = available_port()
    while web_port == api_port:
        web_port = available_port()

    for attempt in range(2):
        log_path = tmp_path / f"dev-{attempt}.log"
        process = start_dev(api_port, web_port, log_path)
        try:
            wait_for_response(
                process,
                f"http://127.0.0.1:{api_port}/health",
                ('"status":"ok"', '"service":"ai-qa-copilot-api"'),
                log_path,
            )
            wait_for_response(
                process,
                f"http://localhost:{web_port}/",
                ("AI Quality Engineering Copilot", "Walking skeleton"),
                log_path,
            )
            stop_dev(process, log_path)
        finally:
            force_stop(process)

        assert_port_released("127.0.0.1", api_port)
        assert_port_released("localhost", web_port)
