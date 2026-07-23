"""Generic orchestration for registered external-tool evidence."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Callable

from moth.adapters.omen import run_evidence as run_omen_evidence
from moth.schema import TOOL_EVIDENCE_SCHEMA_VERSION
from moth.tool_contracts import load_tool_contract
from moth.tool_installations import load_tool_installations


Collector = Callable[[Any, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]


def _options(raw: dict[str, Any], contract: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    spec = contract["profile"]
    unknown = sorted(set(raw) - set(spec["allowed_keys"]))
    if unknown:
        return None, [f"unsupported profile option(s): {', '.join(unknown)}"]
    value = {**spec["defaults"], **raw}
    if not isinstance(value.get("enabled"), bool) or not isinstance(value.get("required"), bool):
        return None, ["enabled and required must be booleans"]
    if value["enabled"]:
        missing = [key for key in spec["required_when_enabled"] if value.get(key) in (None, "")]
        if missing:
            return None, [f"missing required option(s): {', '.join(sorted(missing))}"]
    if isinstance(value.get("top"), bool):
        return None, ["top must be an integer"]
    try:
        value["top"] = max(1, min(int(value["top"]), int(contract["bounds"]["max_findings"])))
    except (TypeError, ValueError, OverflowError):
        return None, ["top must be an integer"]
    try:
        timeout = float(value["timeout_seconds"])
    except (TypeError, ValueError, OverflowError):
        timeout = float(contract["bounds"]["default_timeout_seconds"])
    if not math.isfinite(timeout) or timeout <= 0:
        timeout = float(contract["bounds"]["default_timeout_seconds"])
    value["timeout_seconds"] = min(timeout, float(contract["bounds"]["max_timeout_seconds"]))
    if value.get("config_path") is not None and not isinstance(value["config_path"], Path):
        return None, ["config_path must resolve to a repository-local path"]
    return value, []


def _collect_omen(profile: Any, options: dict[str, Any], contract: dict[str, Any], installation: dict[str, Any]) -> dict[str, Any]:
    del contract
    return run_omen_evidence(
        profile.repo_path,
        options["config_path"],
        top=options["top"],
        diff_target=options["diff_target"],
        timeout_seconds=options["timeout_seconds"],
        binary=installation["executable"],
    )


_ADAPTERS: dict[str, Collector] = {"omen": _collect_omen}


def collect_tool_evidence(profile: Any, *, installations: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    bundle: dict[str, Any] = {"schema_version": TOOL_EVIDENCE_SCHEMA_VERSION, "tools": {}}
    configured = getattr(profile, "tools", {})
    if not isinstance(configured, dict):
        return bundle
    try:
        trusted = load_tool_installations() if installations is None else installations
    except ValueError:
        trusted = {}
        registry_invalid = True
    else:
        registry_invalid = False
    for tool_id, raw in sorted(configured.items()):
        required = bool(raw.get("required")) if isinstance(raw, dict) else False
        base = {
            "schema_version": 1, "tool": tool_id, "scope": "evidence_only",
            "state": "INVALID_CONFIG", "required": required, "version": None,
            "compatible": None, "evidence": [], "issues": [],
        }
        try:
            contract = load_tool_contract(tool_id)
        except ValueError:
            base.update(state="ADAPTER_UNAVAILABLE", issues=["no registered Moth adapter contract"])
            bundle["tools"][tool_id] = base
            continue
        if not isinstance(raw, dict):
            base["issues"] = ["tool profile options must be a mapping"]
            bundle["tools"][tool_id] = base
            continue
        options, option_issues = _options(raw, contract)
        if option_issues:
            base["issues"] = option_issues
            bundle["tools"][tool_id] = base
            continue
        assert options is not None
        base["required"] = bool(options["required"])
        config_path = options.get("config_path")
        if isinstance(config_path, Path):
            try:
                config_path.resolve().relative_to(Path(profile.repo_path).resolve())
            except ValueError:
                base["issues"] = ["config_path escapes repository"]
                bundle["tools"][tool_id] = base
                continue
        if not options["enabled"]:
            base.update(state="DISABLED", issues=[])
            bundle["tools"][tool_id] = base
            continue
        installation = trusted.get(tool_id)
        if not isinstance(installation, dict) or not installation.get("executable"):
            base.update(
                state="BINARY_UNAVAILABLE",
                issues=["trusted user installation registry is invalid" if registry_invalid else "trusted user installation is not registered"],
            )
            bundle["tools"][tool_id] = base
            continue
        adapter = _ADAPTERS.get(tool_id)
        if adapter is None:
            base.update(state="ADAPTER_UNAVAILABLE", issues=["no registered Moth adapter implementation"])
            bundle["tools"][tool_id] = base
            continue
        bundle["tools"][tool_id] = {**base, **adapter(profile, options, contract, installation), "required": base["required"]}
    return bundle


def tool_health_messages(bundle: dict[str, Any]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    for tool_id, evidence in sorted((bundle.get("tools") or {}).items()):
        state = str(evidence.get("state", "FAILED"))
        if state in {"COMPLETE", "DISABLED"}:
            continue
        message = f"{tool_id} evidence unavailable: {state}"
        (issues if evidence.get("required") else warnings).append(
            f"required {message}" if evidence.get("required") else message
        )
    return issues, warnings
