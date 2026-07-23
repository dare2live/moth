"""Validated packaged contracts for registered external tool adapters."""

from __future__ import annotations

import json
import re
from importlib.resources import files
from typing import Any

import yaml
from jsonschema import Draft202012Validator


_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


def validate_tool_contract(payload: Any, *, expected_id: str | None = None) -> dict[str, Any]:
    schema = json.loads(files(__package__).joinpath("schema.json").read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise ValueError(f"invalid tool contract at {location}: {errors[0].message}")
    assert isinstance(payload, dict)
    if expected_id is not None and payload["id"] != expected_id:
        raise ValueError(f"invalid tool contract: expected {expected_id}")
    bounds = payload["bounds"]
    if bounds["default_timeout_seconds"] > bounds["max_timeout_seconds"]:
        raise ValueError("invalid tool contract: default timeout exceeds maximum")
    profile = payload["profile"]
    allowed = set(profile["allowed_keys"])
    if not set(profile["defaults"]) <= allowed:
        raise ValueError("invalid tool contract: defaults are not allowed options")
    if not set(profile["required_when_enabled"]) <= allowed:
        raise ValueError("invalid tool contract: required options are not allowed")
    return payload


def load_tool_contract(tool_id: str) -> dict[str, Any]:
    if not _TOOL_ID_RE.fullmatch(tool_id):
        raise ValueError("unknown tool contract")
    resource = files(__package__).joinpath(f"{tool_id}.yaml")
    if not resource.is_file():
        raise ValueError(f"unknown tool contract: {tool_id}")
    try:
        payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid tool contract: {tool_id}") from exc
    return validate_tool_contract(payload, expected_id=tool_id)
