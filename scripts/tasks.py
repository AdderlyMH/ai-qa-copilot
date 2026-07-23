"""Run the repository's stable engineering-command contract."""

from __future__ import annotations

import argparse
import os
import signal
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NODE_MAJOR = 24
EXECUTABLE_OVERRIDE_PREFIX = "AI_QA_COPILOT"
DEV_SHUTDOWN_TIMEOUT_SECONDS = 5.0
WINDOWS_CREATE_NEW_PROCESS_GROUP = 0x00000200
WINDOWS_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_CLOSE = 0x00002000
WINDOWS_WAIT_OBJECT_0 = 0x00000000
WINDOWS_PROCESS_WRAPPER = (
    "import subprocess, sys; "
    "gate = sys.stdin.buffer.read(1); "
    "raise SystemExit(subprocess.call(sys.argv[1:]) if gate == b'\\0' else 1)"
)
POSIX_FORCE_KILL_SIGNAL = 9


@dataclass
class ManagedProcess:
    """A development process leader and its platform ownership handle."""

    process: subprocess.Popen[bytes]
    windows_job_handle: int | None = None


def run(*command: str, env: dict[str, str] | None = None) -> None:
    """Run one repository command and propagate a nonzero exit status."""

    subprocess.run(command, cwd=ROOT, check=True, env=env)


def require_executable(command: str, override_name: str) -> str:
    """Resolve one required executable or fail with an actionable message."""

    configured = os.environ.get(override_name)
    if configured is not None:
        configured_path = Path(configured).resolve()
        if not configured_path.is_file():
            raise RuntimeError(
                f"Configured executable does not exist: {override_name}={configured}"
            )
        return str(configured_path)
    executable = shutil.which(command)
    if executable is None:
        raise RuntimeError(f"Required executable is not on PATH: {command}")
    return executable


def uv() -> str:
    """Return the required uv executable."""

    return require_executable("uv", f"{EXECUTABLE_OVERRIDE_PREFIX}_UV")


def npm() -> str:
    """Return npm's executable, accounting for its Windows command shim."""

    return require_executable(
        "npm.cmd" if os.name == "nt" else "npm",
        f"{EXECUTABLE_OVERRIDE_PREFIX}_NPM",
    )


def node() -> str:
    """Return the Node.js executable."""

    return require_executable("node", f"{EXECUTABLE_OVERRIDE_PREFIX}_NODE")


def verify_node_major() -> None:
    """Fail when commands are not running on the supported Node.js major."""

    completed = subprocess.run(
        (node(), "--version"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    version = completed.stdout.strip().removeprefix("v")
    major_text, _, _ = version.partition(".")
    if not major_text.isdigit() or int(major_text) != EXPECTED_NODE_MAJOR:
        raise RuntimeError(
            f"Node.js {EXPECTED_NODE_MAJOR}.x is required; found {version or 'unknown'}"
        )


def node_environment() -> dict[str, str]:
    """Put the selected Node.js executable first for npm child scripts."""

    environment = os.environ.copy()
    node_directory = str(Path(node()).resolve().parent)
    current_path = environment.get("PATH")
    environment["PATH"] = (
        os.pathsep.join((node_directory, current_path))
        if current_path
        else node_directory
    )
    return environment


def uv_run(*command: str) -> None:
    """Run a command in the locked Python project environment."""

    run(uv(), "run", "--locked", *command)


def npm_run(script: str) -> None:
    """Run one pinned root npm script with the supported Node.js major."""

    verify_node_major()
    run(npm(), "run", script, env=node_environment())


def bootstrap() -> None:
    """Synchronize the locked Python and JavaScript dependencies."""

    verify_node_major()
    run(uv(), "sync", "--locked")
    run(npm(), "ci", env=node_environment())


def format_code() -> None:
    """Format Python and frontend code, then refresh the repository manifest."""

    uv_run("ruff", "format", "scripts", "apps/api")
    npm_run("format:web")
    uv_run("python", "scripts/generate_manifest.py", "--write")


def lint() -> None:
    """Run the repository Python and frontend lint gates."""

    uv_run("ruff", "check", "scripts", "apps/api")
    npm_run("lint:web")


def typecheck() -> None:
    """Run strict Python and TypeScript type checking."""

    uv_run("mypy")
    npm_run("typecheck:web")


def test() -> None:
    """Run documentation self-tests and backend tests."""

    docs_self_test()
    uv_run("pytest")


def docs_check() -> None:
    """Check manifest freshness and validate canonical documentation."""

    uv_run("python", "scripts/generate_manifest.py", "--check")
    uv_run("python", "scripts/validate_docs.py")


def docs_self_test() -> None:
    """Run the validator's isolated negative checks directly."""

    uv_run("python", "scripts/validate_docs.py", "--self-test")


def ci() -> None:
    """Run all noninteractive repository checks."""

    lint()
    typecheck()
    test()
    docs_check()


def windows_kernel32() -> object:
    """Load kernel32 without importing Windows-only ctypes names elsewhere."""

    import ctypes

    return getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)


def windows_error(operation: str) -> OSError:
    """Build an OSError for the most recent Windows API failure."""

    import ctypes

    error_code = int(getattr(ctypes, "get_last_error")())
    return OSError(error_code, f"{operation} failed")


def create_windows_kill_on_close_job() -> int:
    """Create a Job Object that terminates all members when its handle closes."""

    import ctypes
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = (
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        )

    class IoCounters(ctypes.Structure):
        _fields_ = (
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        )

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = (
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        )

    kernel32 = windows_kernel32()
    create_job_object = getattr(kernel32, "CreateJobObjectW")
    create_job_object.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p)
    create_job_object.restype = wintypes.HANDLE
    job_handle = create_job_object(None, None)
    if not job_handle:
        raise windows_error("CreateJobObjectW")

    information = ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = (
        WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_CLOSE
    )
    set_information = getattr(kernel32, "SetInformationJobObject")
    set_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    set_information.restype = wintypes.BOOL
    configured = set_information(
        job_handle,
        WINDOWS_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(information),
        ctypes.sizeof(information),
    )
    if not configured:
        close_windows_handle(int(job_handle))
        raise windows_error("SetInformationJobObject")
    return int(job_handle)


def close_windows_handle(handle: int) -> None:
    """Close one Windows kernel handle."""

    from ctypes import wintypes

    kernel32 = windows_kernel32()
    close_handle = getattr(kernel32, "CloseHandle")
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    if not close_handle(handle):
        raise windows_error("CloseHandle")


def terminate_windows_job(job_handle: int) -> None:
    """Terminate every process in a Job Object and wait for full exit."""

    from ctypes import wintypes

    kernel32 = windows_kernel32()
    terminate_job = getattr(kernel32, "TerminateJobObject")
    terminate_job.argtypes = (wintypes.HANDLE, wintypes.UINT)
    terminate_job.restype = wintypes.BOOL
    if not terminate_job(job_handle, 1):
        raise windows_error("TerminateJobObject")

    wait_for_single_object = getattr(kernel32, "WaitForSingleObject")
    wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait_for_single_object.restype = wintypes.DWORD
    wait_result = wait_for_single_object(
        job_handle, int(DEV_SHUTDOWN_TIMEOUT_SECONDS * 1000)
    )
    if wait_result != WINDOWS_WAIT_OBJECT_0:
        raise RuntimeError(
            "Timed out waiting for a Windows development process tree to stop"
        )


def assign_windows_process_to_job(
    process: subprocess.Popen[bytes], job_handle: int
) -> None:
    """Assign a blocked process to a Job Object and verify membership."""

    import ctypes
    from ctypes import wintypes

    kernel32 = windows_kernel32()
    process_handle = int(getattr(process, "_handle"))

    assign_process = getattr(kernel32, "AssignProcessToJobObject")
    assign_process.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    assign_process.restype = wintypes.BOOL
    if not assign_process(job_handle, process_handle):
        raise windows_error("AssignProcessToJobObject")

    is_process_in_job = getattr(kernel32, "IsProcessInJob")
    is_process_in_job.argtypes = (
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.c_void_p,
    )
    is_process_in_job.restype = wintypes.BOOL
    membership = wintypes.BOOL()
    if not is_process_in_job(
        process_handle,
        job_handle,
        ctypes.byref(membership),
    ):
        raise windows_error("IsProcessInJob")
    if not membership.value:
        raise RuntimeError("Development process was not assigned to its Job Object")


def start_managed_process(
    command: tuple[str, ...], environment: dict[str, str] | None
) -> ManagedProcess:
    """Start a development process in its own managed group."""

    if os.name == "nt":
        job_handle = create_windows_kill_on_close_job()
        wrapper_command = (
            sys.executable,
            "-c",
            WINDOWS_PROCESS_WRAPPER,
            *command,
        )
        try:
            process = subprocess.Popen(
                wrapper_command,
                cwd=ROOT,
                env=environment,
                stdin=subprocess.PIPE,
                creationflags=WINDOWS_CREATE_NEW_PROCESS_GROUP,
            )
        except BaseException:
            close_windows_handle(job_handle)
            raise
        try:
            assign_windows_process_to_job(process, job_handle)
            if process.stdin is None:
                raise RuntimeError("Windows development process gate is unavailable")
            process.stdin.write(b"\0")
            process.stdin.close()
        except BaseException:
            process.kill()
            process.wait()
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            close_windows_handle(job_handle)
            raise
        return ManagedProcess(process, job_handle)
    return ManagedProcess(
        subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            start_new_session=True,
        )
    )


def send_posix_process_group_signal(process_id: int, process_signal: int) -> None:
    """Send a signal to a POSIX process group without importing platform stubs."""

    killpg = getattr(os, "killpg")
    killpg(process_id, process_signal)


def terminate_process_tree(managed_process: ManagedProcess) -> None:
    """Request termination of one complete managed process tree."""

    process = managed_process.process
    if os.name == "nt":
        job_handle = managed_process.windows_job_handle
        if job_handle is not None:
            managed_process.windows_job_handle = None
            try:
                terminate_windows_job(job_handle)
            finally:
                close_windows_handle(job_handle)
        elif process.poll() is None:
            process.kill()
        return

    try:
        send_posix_process_group_signal(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def process_group_exists(managed_process: ManagedProcess) -> bool:
    """Return whether a POSIX development process group still has members."""

    process = managed_process.process
    try:
        send_posix_process_group_signal(process.pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_process_group(managed_process: ManagedProcess) -> None:
    """Force any remaining POSIX development process-group members to exit."""

    process = managed_process.process
    try:
        send_posix_process_group_signal(process.pid, POSIX_FORCE_KILL_SIGNAL)
    except ProcessLookupError:
        pass


def stop_processes(processes: list[ManagedProcess]) -> None:
    """Stop complete development process groups and wait for their leaders."""

    cleanup_errors: list[Exception] = []
    for managed_process in processes:
        try:
            terminate_process_tree(managed_process)
        except Exception as error:
            cleanup_errors.append(error)

    deadline = time.monotonic() + DEV_SHUTDOWN_TIMEOUT_SECONDS
    if os.name != "nt":
        while time.monotonic() < deadline:
            for managed_process in processes:
                managed_process.process.poll()
            if not any(
                process_group_exists(managed_process) for managed_process in processes
            ):
                break
            time.sleep(0.05)
        for managed_process in processes:
            if process_group_exists(managed_process):
                kill_process_group(managed_process)

    for managed_process in processes:
        process = managed_process.process
        try:
            if process.poll() is not None:
                continue
            try:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        except Exception as error:
            cleanup_errors.append(error)

    if cleanup_errors:
        raise RuntimeError(
            f"Development cleanup failed in {len(cleanup_errors)} operation(s)"
        ) from cleanup_errors[0]


def dev(api_port: int, web_port: int) -> None:
    """Start the FastAPI and Next.js development servers together."""

    verify_node_major()
    windows_break_signal = getattr(signal, "SIGBREAK", None)
    previous_break_handler = None
    if windows_break_signal is not None:
        previous_break_handler = signal.signal(
            windows_break_signal, signal.default_int_handler
        )
    commands = (
        (
            uv(),
            "run",
            "--locked",
            "uvicorn",
            "ai_qa_copilot_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
            "--reload",
        ),
        (
            npm(),
            "run",
            "dev",
            "--workspace",
            "@ai-qa-copilot/web",
            "--",
            "--hostname",
            "localhost",
            "--port",
            str(web_port),
        ),
    )
    environments = (None, node_environment())
    processes: list[ManagedProcess] = []
    try:
        for command, environment in zip(commands, environments, strict=True):
            processes.append(start_managed_process(command, environment))
        print(
            f"API: http://127.0.0.1:{api_port} | "
            f"Web: http://localhost:{web_port} | press Ctrl+C to stop",
            flush=True,
        )
        while True:
            for managed_process in processes:
                process = managed_process.process
                return_code = process.poll()
                if return_code is not None:
                    raise RuntimeError(
                        f"Development server exited unexpectedly with {return_code}"
                    )
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("Stopping development servers...", flush=True)
    finally:
        stop_processes(processes)
        if windows_break_signal is not None and previous_break_handler is not None:
            signal.signal(windows_break_signal, previous_break_handler)


def print_help() -> None:
    """Print the stable target names without relying on Make availability."""

    print("Available targets:")
    print("  bootstrap format lint typecheck test dev docs-check docs-self-test ci")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse one stable target and optional development-server ports."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        choices=(
            "help",
            "bootstrap",
            "format",
            "lint",
            "typecheck",
            "test",
            "dev",
            "docs-check",
            "docs-self-test",
            "ci",
        ),
        nargs="?",
        default="help",
    )
    parser.add_argument("--port", type=int, default=8000, help="FastAPI port")
    parser.add_argument("--web-port", type=int, default=3000, help="Next.js port")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Dispatch the requested target."""

    args = parse_args(argv)
    commands: dict[str, Callable[[], None]] = {
        "bootstrap": bootstrap,
        "format": format_code,
        "lint": lint,
        "typecheck": typecheck,
        "test": test,
        "docs-check": docs_check,
        "docs-self-test": docs_self_test,
        "ci": ci,
    }
    if args.target == "help":
        print_help()
    elif args.target == "dev":
        dev(args.port, args.web_port)
    else:
        commands[args.target]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
