"""Shared bounded subprocess boundary for trusted registered executables."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import BinaryIO
from typing import Mapping, Sequence


DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_OUTPUT_BYTES = 2_000_000
DEFAULT_ENVIRONMENT_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
_READ_CHUNK_BYTES = 64 * 1024
_PROCESS_POLL_SECONDS = 0.02


class OutputLimitExceeded(RuntimeError):
    pass


def minimal_environment(
    allowlist: Sequence[str] = DEFAULT_ENVIRONMENT_ALLOWLIST,
    *,
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    values = os.environ if source is None else source
    return {key: values[key] for key in allowlist if key in values}


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        elif process.poll() is None:
            process.kill()
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait()


def _decode_output(value: bytearray) -> str:
    return bytes(value).decode("utf-8", errors="replace")


def _close_pipe_reads(process: subprocess.Popen[bytes]) -> None:
    """Release Moth's pipe ends without waiting for escaped descendants."""

    for stream in (process.stdout, process.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def run_safe_process(
    command: Sequence[str],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    environment: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
) -> subprocess.CompletedProcess[str]:
    """Run a registered executable behind a bounded process boundary.

    Stdout and stderr are drained concurrently, but Moth retains at most
    ``max_output_bytes`` across both streams. The process group is terminated
    as soon as that shared byte budget or the timeout is exceeded.
    """
    argv = list(command)
    if not argv:
        raise ValueError("external tool command must not be empty")
    if timeout_seconds <= 0:
        raise ValueError("external tool timeout must be positive")
    if max_output_bytes <= 0:
        raise ValueError("external tool output limit must be positive")

    process = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        env=dict(environment) if environment is not None else minimal_environment(),
        cwd=str(cwd) if cwd is not None else None,
        start_new_session=os.name == "posix",
    )
    assert process.stdout is not None
    assert process.stderr is not None

    stdout = bytearray()
    stderr = bytearray()
    output_lock = threading.Lock()
    output_limit_exceeded = threading.Event()
    retained_bytes = 0

    def drain(stream: BinaryIO, destination: bytearray) -> None:
        nonlocal retained_bytes
        while True:
            try:
                chunk = stream.read(_READ_CHUNK_BYTES)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            with output_lock:
                remaining = max_output_bytes - retained_bytes
                if remaining <= 0:
                    output_limit_exceeded.set()
                    return
                destination.extend(chunk[:remaining])
                retained_bytes += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    output_limit_exceeded.set()
                    return

    readers = [
        threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()

    deadline = time.monotonic() + timeout_seconds
    timed_out = False
    while process.poll() is None:
        if output_limit_exceeded.is_set():
            _stop_process_group(process)
            _close_pipe_reads(process)
            break
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            timed_out = True
            _stop_process_group(process)
            _close_pipe_reads(process)
            break
        output_limit_exceeded.wait(min(_PROCESS_POLL_SECONDS, remaining_seconds))

    while any(reader.is_alive() for reader in readers):
        if output_limit_exceeded.is_set():
            _stop_process_group(process)
            _close_pipe_reads(process)
            break
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            timed_out = True
            _stop_process_group(process)
            _close_pipe_reads(process)
            break
        for reader in readers:
            reader.join(timeout=min(_PROCESS_POLL_SECONDS, remaining_seconds))

    for reader in readers:
        reader.join(timeout=_PROCESS_POLL_SECONDS)

    decoded_stdout = _decode_output(stdout)
    decoded_stderr = _decode_output(stderr)
    if output_limit_exceeded.is_set():
        raise OutputLimitExceeded("external tool output exceeded Moth safety limit")
    if timed_out:
        raise subprocess.TimeoutExpired(
            argv,
            timeout_seconds,
            output=decoded_stdout,
            stderr=decoded_stderr,
        )
    return subprocess.CompletedProcess(
        argv,
        process.returncode,
        stdout=decoded_stdout,
        stderr=decoded_stderr,
    )
