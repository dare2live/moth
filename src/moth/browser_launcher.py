"""Capability-safe browser launch adapters."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from moth.web_config import load_web_policy


class ProjectSelectionError(RuntimeError):
    """The native picker failed rather than being cancelled by the user."""


def _platform_spec(policy: dict[str, Any], capability: str) -> dict[str, Any] | None:
    settings = policy.get(capability)
    if not isinstance(settings, dict):
        return None
    platforms = settings.get("platforms")
    if not isinstance(platforms, dict):
        return None
    spec = platforms.get(sys.platform)
    return spec if isinstance(spec, dict) else None


def open_capability_url(url: str) -> bool:
    """Open a loopback capability URL without placing it in process arguments."""
    policy = load_web_policy()
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in set(map(str, policy["network"]["loopback_hosts"]))
        or not parsed.fragment.startswith("token=")
    ):
        return False
    spec = _platform_spec(policy, "browser_launch")
    if spec is None or spec.get("transport") != "stdin_applescript":
        return False
    command = [str(item) for item in spec.get("command", [])]
    if command != ["/usr/bin/osascript"]:
        return False
    script = f"open location {json.dumps(url)}\n"
    try:
        completed = subprocess.run(
            command,
            input=script,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=float(spec["timeout_seconds"]),
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return completed.returncode == 0


def project_selection_available() -> bool:
    """Return whether the current platform has the constrained native adapter."""

    policy = load_web_policy()
    spec = _platform_spec(policy, "project_selection")
    if spec is None or spec.get("transport") != "stdin_applescript":
        return False
    return [str(item) for item in spec.get("command", [])] == ["/usr/bin/osascript"]


def select_project_directory() -> Path | None:
    """Ask macOS for a project directory without accepting a browser-supplied path."""

    policy = load_web_policy()
    settings = policy.get("project_selection")
    if not isinstance(settings, dict):
        raise ProjectSelectionError("project selection policy is unavailable")
    spec = _platform_spec(policy, "project_selection")
    if not project_selection_available() or spec is None:
        raise ProjectSelectionError("native project selection is unavailable")
    command = [str(item) for item in spec.get("command", [])]
    if command != ["/usr/bin/osascript"]:
        raise ProjectSelectionError("native project selection command is invalid")
    script = (
        "try\n"
        '  set selectedFolder to choose folder with prompt "Choose a project folder for Moth"\n'
        '  return "SELECTED\\n" & POSIX path of selectedFolder\n'
        "on error number -128\n"
        '  return "CANCELLED"\n'
        "end try\n"
    )
    try:
        completed = subprocess.run(
            command,
            input=script,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=float(spec["timeout_seconds"]),
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ProjectSelectionError("native project selection failed") from None
    if completed.returncode != 0 or not isinstance(completed.stdout, str):
        raise ProjectSelectionError("native project selection failed")
    output = completed.stdout.strip()
    if output == "CANCELLED":
        return None
    prefix = "SELECTED\n"
    if not output.startswith(prefix):
        raise ProjectSelectionError("native project selection returned invalid output")
    raw_path = output[len(prefix) :].strip()
    if (
        not raw_path
        or "\x00" in raw_path
        or len(raw_path.encode("utf-8")) > int(settings["max_path_bytes"])
    ):
        raise ProjectSelectionError("native project selection returned an invalid path")
    selected = Path(raw_path).expanduser().resolve()
    if not selected.is_dir():
        raise ProjectSelectionError("selected project directory is unavailable")
    return selected
