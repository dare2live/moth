"""Capability-safe browser launch adapters."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any
from urllib.parse import urlsplit

from moth.web_config import load_web_policy


def _platform_spec(policy: dict[str, Any]) -> dict[str, Any] | None:
    launch = policy.get("browser_launch")
    if not isinstance(launch, dict):
        return None
    platforms = launch.get("platforms")
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
    spec = _platform_spec(policy)
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
