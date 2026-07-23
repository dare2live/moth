import json
import subprocess
import sys
import time

import pytest

from moth.safe_process import OutputLimitExceeded, minimal_environment, run_safe_process


def test_minimal_environment_does_not_forward_secrets(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("PRIVATE_TOKEN", "secret")

    environment = minimal_environment()

    assert environment["PATH"] == "/usr/bin"
    assert "PRIVATE_TOKEN" not in environment


def test_safe_process_applies_environment_and_cwd(tmp_path) -> None:
    completed = run_safe_process(
        [
            sys.executable,
            "-c",
            (
                "import json, os; "
                "print(json.dumps({'cwd': os.getcwd(), 'path': os.environ.get('PATH'), "
                "'secret': os.environ.get('PRIVATE_TOKEN')}))"
            ),
        ],
        timeout_seconds=7,
        environment={"PATH": "/usr/bin"},
        cwd=tmp_path,
    )

    payload = json.loads(completed.stdout)
    assert payload == {"cwd": str(tmp_path), "path": "/usr/bin", "secret": None}


def test_safe_process_enforces_output_limit_while_process_is_running() -> None:
    with pytest.raises(OutputLimitExceeded):
        run_safe_process(
            [
                sys.executable,
                "-c",
                "import sys, time; sys.stdout.buffer.write(b'x' * 10000000); sys.stdout.flush(); time.sleep(5)",
            ],
            timeout_seconds=7,
            max_output_bytes=1024,
        )


def test_safe_process_timeout_uses_subprocess_contract() -> None:
    with pytest.raises(subprocess.TimeoutExpired):
        run_safe_process(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout_seconds=0.05,
        )


def test_safe_process_timeout_covers_descendant_that_keeps_pipes_open() -> None:
    started = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired):
        run_safe_process(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess, sys; "
                    "subprocess.Popen("
                    "[sys.executable, '-c', 'import time; time.sleep(2)'], "
                    "stdout=sys.stdout, stderr=sys.stderr)"
                ),
            ],
            timeout_seconds=0.1,
        )

    assert time.monotonic() - started < 1


def test_safe_process_timeout_is_bounded_when_descendant_leaves_process_group() -> None:
    started = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired):
        run_safe_process(
            [
                sys.executable,
                "-c",
                (
                    "import subprocess, sys; "
                    "subprocess.Popen("
                    "[sys.executable, '-c', 'import time; time.sleep(2)'], "
                    "stdout=sys.stdout, stderr=sys.stderr, start_new_session=True)"
                ),
            ],
            timeout_seconds=0.1,
        )

    assert time.monotonic() - started < 1
