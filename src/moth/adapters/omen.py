"""Contract-driven, evidence-only adapter for Omen."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from moth.tool_contracts import load_tool_contract
from moth.safe_process import OutputLimitExceeded, run_safe_process


_CONTRACT = load_tool_contract("omen")
_VERSION_RE = re.compile(r"^\s*omen\s+(\d+)\.(\d+)\.(\d+)\s*$")
_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_GIT_OCTAL_ESCAPE_RE = re.compile(r"\\[0-7]{3}")


def _bounds() -> dict[str, int]:
    return _CONTRACT["bounds"]


def _bounded_limit(value: Any) -> int:
    maximum = int(_bounds()["max_findings"])
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = 1
    return max(1, min(parsed, maximum))


def _bounded_timeout(value: Any) -> float:
    bounds = _bounds()
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        parsed = float(bounds["default_timeout_seconds"])
    if not math.isfinite(parsed) or parsed <= 0:
        parsed = float(bounds["default_timeout_seconds"])
    return min(parsed, float(bounds["max_timeout_seconds"]))


def _render_argv(template: list[Any], **values: Any) -> list[str]:
    rendered: list[str] = []
    substitutions = {key: str(value) for key, value in values.items()}
    for part in template:
        rendered.append(str(part).format_map(substitutions))
    return rendered


def _capability_command(
    capability: str,
    repo_path: str | Path,
    config_path: str | Path,
    *,
    binary: str,
    limit: int | None = None,
    target: str | None = None,
) -> list[str]:
    spec = _CONTRACT["capabilities"][capability]
    values = {
        "binary": binary,
        "repo": Path(repo_path),
        "config": Path(config_path),
        "limit": _bounded_limit(limit),
        "target": target or "",
    }
    return _render_argv(spec["argv"], **values)


def hotspot_command(
    repo_path: str | Path,
    config_path: str | Path,
    *,
    top: int | None = None,
    binary: str = "omen",
) -> list[str]:
    return _capability_command(
        "hotspot",
        repo_path,
        config_path,
        binary=binary,
        limit=_bounds()["max_findings"] if top is None else top,
    )


def changes_command(
    repo_path: str | Path,
    config_path: str | Path,
    *,
    top: int | None = None,
    binary: str = "omen",
) -> list[str]:
    return _capability_command(
        "changes",
        repo_path,
        config_path,
        binary=binary,
        limit=_bounds()["max_findings"] if top is None else top,
    )


def diff_command(
    repo_path: str | Path,
    config_path: str | Path,
    *,
    target: str,
    binary: str = "omen",
) -> list[str]:
    if not isinstance(target, str) or not target.strip():
        raise ValueError("an explicit diff target is required")
    return _capability_command(
        "diff", repo_path, config_path, binary=binary, target=target
    )


def _allowed_environment() -> dict[str, str]:
    allowed = _CONTRACT["process"]["environment_allowlist"]
    return {
        str(key): os.environ[str(key)]
        for key in allowed
        if str(key) in os.environ
    }


def _run_process(
    command: list[str],
    *,
    timeout_seconds: float,
    environment: dict[str, str],
) -> tuple[str, subprocess.CompletedProcess[str] | None]:
    try:
        completed = run_safe_process(
            command,
            timeout_seconds=timeout_seconds,
            environment=environment,
        )
    except FileNotFoundError:
        return "BINARY_UNAVAILABLE", None
    except subprocess.TimeoutExpired:
        return "TIMEOUT", None
    except OutputLimitExceeded:
        return "OUTPUT_LIMIT", None
    except (OSError, ValueError):
        return "PROCESS_ERROR", None
    return "COMPLETE", completed


def _observe_version(
    *,
    binary: str,
    timeout_seconds: float,
    environment: dict[str, str],
) -> tuple[str, str | None, str]:
    template = _CONTRACT["compatibility"]["version"]["argv"]
    state, completed = _run_process(
        _render_argv(template, binary=binary),
        timeout_seconds=timeout_seconds,
        environment=environment,
    )
    if state != "COMPLETE":
        return state, None, "UNAVAILABLE"
    assert completed is not None
    if completed.returncode != 0:
        return "COMPLETE", None, "UNAVAILABLE"
    match = _VERSION_RE.fullmatch(completed.stdout or "")
    if match is None:
        return "COMPLETE", None, "UNPARSED"
    return "COMPLETE", ".".join(match.groups()), "PARSED"


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _number_map(value: Any, field_key: str) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    allowed = _CONTRACT["fields"][field_key]
    result: dict[str, int | float] = {}
    for key in sorted(str(item) for item in allowed):
        number = _number(value.get(key))
        if number is not None:
            result[key] = number
    return result


def _enum_text(value: Any, vocabulary_key: str) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.lower()
    allowed = {
        str(item).lower() for item in _CONTRACT["vocabulary"][vocabulary_key]
    }
    return normalized if normalized in allowed else None


def _safe_repo_path(value: Any, repo_path: Path) -> str | None:
    if not isinstance(value, str) or not value or "\x00" in value or len(value) > 512:
        return None
    if (
        (value.startswith('"') and value.endswith('"'))
        or _GIT_OCTAL_ESCAPE_RE.search(value)
    ):
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve(strict=False).relative_to(repo_path)
        except ValueError:
            return None
    if ".." in candidate.parts:
        return None
    normalized = candidate.as_posix()
    return None if normalized in {"", "."} else normalized


def normalize_hotspots(
    payload: dict[str, Any],
    repo_path: str | Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    raw_findings = payload.get("hotspots")
    if not isinstance(raw_findings, list):
        raise ValueError("Omen hotspot output has no hotspots list")
    repo = Path(repo_path).resolve()
    bounded = _bounded_limit(
        _bounds()["max_findings"] if limit is None else limit
    )
    findings: list[dict[str, Any]] = []
    for raw in raw_findings[:bounded]:
        if not isinstance(raw, dict):
            raise ValueError("Omen hotspot record is not an object")
        file_path = _safe_repo_path(raw.get("file"), repo)
        severity = _enum_text(raw.get("severity"), "hotspot_severities")
        score = _number(raw.get("score"))
        if file_path is None or severity is None or score is None:
            raise ValueError("Omen hotspot record lacks required evidence")
        item: dict[str, Any] = {"file": file_path, "severity": severity}
        item.update(_number_map(raw, "hotspot_numeric"))
        findings.append(item)
    omitted = _number(payload.get("hotspots_omitted"))
    omitted_count = int(omitted) if omitted is not None and omitted > 0 else 0
    return {
        "kind": "hotspot",
        "state": "COMPLETE",
        "findings": findings,
        "summary": _number_map(payload.get("summary"), "hotspot_summary"),
        "truncated": len(raw_findings) > bounded or omitted_count > 0,
        "omitted_count": omitted_count,
    }


def normalize_changes(
    payload: dict[str, Any],
    repo_path: str | Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    raw_findings = payload.get("commits")
    if not isinstance(raw_findings, list):
        raise ValueError("Omen changes output has no commits list")
    repo = Path(repo_path).resolve()
    bounded = _bounded_limit(
        _bounds()["max_findings"] if limit is None else limit
    )
    findings: list[dict[str, Any]] = []
    for raw in raw_findings[:bounded]:
        if not isinstance(raw, dict):
            raise ValueError("Omen changes record is not an object")
        commit_hash = raw.get("commit_hash")
        risk_level = _enum_text(raw.get("risk_level"), "risk_levels")
        risk_score = _number(raw.get("risk_score"))
        if (
            not isinstance(commit_hash, str)
            or _COMMIT_RE.fullmatch(commit_hash) is None
            or risk_level is None
            or risk_score is None
        ):
            raise ValueError("Omen changes record lacks required evidence")
        item: dict[str, Any] = {
            "commit_hash": commit_hash.lower(),
            "risk_level": risk_level,
            "risk_score": risk_score,
        }
        files = raw.get("files_modified")
        if isinstance(files, list):
            item["files_modified"] = [
                normalized
                for value in files[: int(_bounds()["max_findings"])]
                if (normalized := _safe_repo_path(value, repo)) is not None
            ]
        factors = _number_map(raw.get("contributing_factors"), "change_factors")
        if factors:
            item["contributing_factors"] = factors
        file_risk = _number_map(raw.get("file_risk"), "file_risk")
        if file_risk:
            item["file_risk"] = file_risk
        findings.append(item)
    omitted = _number(payload.get("commits_omitted"))
    omitted_count = int(omitted) if omitted is not None and omitted > 0 else 0
    result: dict[str, Any] = {
        "kind": "changes",
        "state": "COMPLETE",
        "findings": findings,
        "summary": _number_map(payload.get("summary"), "changes_summary"),
        "truncated": len(raw_findings) > bounded or omitted_count > 0,
        "omitted_count": omitted_count,
    }
    period_days = _number(payload.get("period_days"))
    if period_days is not None:
        result["period_days"] = period_days
    return result


def normalize_diff(payload: dict[str, Any]) -> dict[str, Any]:
    finding = _number_map(payload, "diff_numeric")
    level = _enum_text(payload.get("level"), "risk_levels")
    if level is None or _number(payload.get("score")) is None:
        raise ValueError("Omen diff output lacks required evidence")
    finding["level"] = level
    factors = _number_map(payload.get("factors"), "change_factors")
    if factors:
        finding["factors"] = factors
    file_risk = _number_map(payload.get("file_risk"), "file_risk")
    if file_risk:
        finding["file_risk"] = file_risk
    return {"kind": "diff", "state": "COMPLETE", "finding": finding}


_NORMALIZERS: dict[str, Callable[..., dict[str, Any]]] = {
    "hotspot_v1": normalize_hotspots,
    "changes_v1": normalize_changes,
    "diff_v1": normalize_diff,
}


def _run_capability(
    name: str,
    command: list[str],
    normalizer: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    repo: Path,
    limit: int,
    timeout_seconds: float,
    environment: dict[str, str],
) -> dict[str, Any]:
    process_state, completed = _run_process(
        command,
        timeout_seconds=timeout_seconds,
        environment=environment,
    )
    if process_state != "COMPLETE":
        return {"kind": name, "state": process_state}
    assert completed is not None
    if completed.returncode != 0:
        return {
            "kind": name,
            "state": "COMMAND_FAILED",
            "exit_code": completed.returncode,
        }
    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        return {"kind": name, "state": "MALFORMED_OUTPUT"}
    if not isinstance(payload, dict):
        return {"kind": name, "state": "UNSUPPORTED_OUTPUT"}
    try:
        if name == "diff":
            return normalizer(payload)
        return normalizer(payload, repo, limit=limit)
    except (TypeError, ValueError):
        return {"kind": name, "state": "UNSUPPORTED_OUTPUT"}


def _base_result() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool": "omen",
        "scope": "evidence_only",
        "state": "PENDING",
        "version": None,
        "version_state": "UNAVAILABLE",
        "compatible": None,
        "compatibility_basis": _CONTRACT["compatibility"]["strategy"],
        "evidence": [],
        "issues": [],
    }


def _shadow_configs(repo: Path, explicit_config: Path) -> list[str]:
    shadows: list[str] = []
    for authored in _CONTRACT["process"]["shadow_config_paths"]:
        relative = Path(str(authored))
        candidate = repo / relative
        if candidate.exists() and candidate.resolve(strict=False) != explicit_config:
            shadows.append(relative.as_posix())
    return shadows


def run_evidence(
    repo_path: str | Path,
    config_path: str | Path,
    *,
    top: int | None = None,
    diff_target: str | None = None,
    timeout_seconds: float | None = None,
    binary: str = "omen",
) -> dict[str, Any]:
    """Probe declared capabilities and return normalized evidence."""

    result = _base_result()
    repo = Path(repo_path).resolve()
    config = Path(config_path).resolve()
    if not repo.is_dir():
        result["state"] = "INVALID_REQUEST"
        result["issues"] = ["repository path is not a directory"]
        return result
    if not config.is_file():
        result["state"] = "INVALID_REQUEST"
        result["issues"] = ["explicit Omen config is not a file"]
        return result
    shadows = _shadow_configs(repo, config)
    if shadows:
        result["state"] = "BLOCKED_SHADOW_CONFIG"
        result["issues"] = [
            f"unconfigured Omen config detected: {relative}" for relative in shadows
        ]
        return result

    limit = _bounded_limit(
        _bounds()["max_findings"] if top is None else top
    )
    timeout = _bounded_timeout(
        _bounds()["default_timeout_seconds"]
        if timeout_seconds is None
        else timeout_seconds
    )
    environment = _allowed_environment()

    version_process_state, version, version_state = _observe_version(
        binary=binary,
        timeout_seconds=timeout,
        environment=environment,
    )
    result["version"] = version
    result["version_state"] = version_state
    if version_process_state == "BINARY_UNAVAILABLE":
        result["state"] = version_process_state
        result["issues"] = ["unable to observe Omen version"]
        return result

    capabilities = _CONTRACT["capabilities"]
    selected = [
        name
        for name, spec in capabilities.items()
        if bool(spec["required"]) or (name == "diff" and diff_target is not None)
    ]
    required_completed: set[str] = set()
    for name in selected:
        spec = capabilities[name]
        normalizer = _NORMALIZERS.get(str(spec["normalizer"]))
        if normalizer is None:
            result["state"] = "FAILED"
            result["compatible"] = False
            result["issues"] = [f"Omen {name} normalizer contract is unsupported"]
            return result
        if name == "diff":
            try:
                command = diff_command(
                    repo, config, target=diff_target or "", binary=binary
                )
            except ValueError:
                result["state"] = "INVALID_REQUEST"
                result["issues"] = ["diff target must be an explicit non-empty ref"]
                return result
        else:
            command = _capability_command(
                name,
                repo,
                config,
                binary=binary,
                limit=limit,
            )
        evidence = _run_capability(
            name,
            command,
            normalizer,
            repo=repo,
            limit=limit,
            timeout_seconds=timeout,
            environment=environment,
        )
        result["evidence"].append(evidence)
        state = evidence["state"]
        if state in {"BINARY_UNAVAILABLE", "TIMEOUT", "PROCESS_ERROR", "OUTPUT_LIMIT"}:
            result["state"] = state
            result["issues"] = [f"Omen {name} process failed"]
            return result
        if state != "COMPLETE":
            result["state"] = "FAILED"
            if state in {"MALFORMED_OUTPUT", "UNSUPPORTED_OUTPUT"}:
                result["compatible"] = False
            result["issues"] = [f"Omen {name} evidence collection failed"]
            return result
        if bool(spec["required"]):
            required_completed.add(name)

    required = {
        name for name, spec in capabilities.items() if bool(spec["required"])
    }
    result["compatible"] = required_completed == required
    result["state"] = "COMPLETE" if result["compatible"] else "FAILED"
    if not result["compatible"]:
        result["issues"] = ["Omen required capability contract is incomplete"]
    return result
