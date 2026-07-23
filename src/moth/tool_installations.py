"""Trusted user-owned installation registry for external executables."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")


def default_installation_registry_path() -> Path:
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return root / "moth" / "tools.yaml"


def load_tool_installations(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    registry = Path(path) if path is not None else default_installation_registry_path()
    if not registry.is_file():
        return {}
    try:
        payload = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("invalid Moth tool installation registry") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "moth_tool_installations" or payload.get("schema_version") != 1 or not isinstance(payload.get("tools"), dict):
        raise ValueError("invalid Moth tool installation registry")
    result: dict[str, dict[str, Any]] = {}
    for raw_id, raw in payload["tools"].items():
        tool_id = str(raw_id)
        if not _ID_RE.fullmatch(tool_id) or not isinstance(raw, dict):
            raise ValueError("invalid Moth tool installation registry")
        if set(raw) - {"executable", "update_strategy"}:
            raise ValueError(f"unsupported installation keys for {tool_id}")
        executable = raw.get("executable")
        if not isinstance(executable, str) or not executable:
            raise ValueError(f"missing executable for {tool_id}")
        if "/" in executable:
            path_value = Path(executable)
            if not path_value.is_absolute() or not os.access(path_value, os.X_OK):
                raise ValueError(f"executable for {tool_id} must be an executable absolute path")
        elif not _NAME_RE.fullmatch(executable):
            raise ValueError(f"invalid executable for {tool_id}")
        strategy = raw.get("update_strategy", "latest_stable")
        if strategy != "latest_stable":
            raise ValueError(f"unsupported update strategy for {tool_id}")
        result[tool_id] = {"executable": executable, "update_strategy": strategy}
    return result
