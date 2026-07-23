from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


GUIDANCE_SCHEMA_VERSION = "moth.guidance.v1"
_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_INVALID_PUBLIC_VALUE = "<invalid>"
_ACTIVATIONS = {"always", "manual", "substantive_judgment"}
_TYPED_VALUES = {
    "kind": {"collaboration_lens", "controller_protocol"},
    "requirement": {"optional", "required_when_active"},
    "scope": {"project", "user", "workspace"},
    "sensitivity": {"internal", "personal", "public"},
    "egress_policy": {"allow_body", "local_only", "metadata_only"},
}
_REQUIRED_SOURCE_FIELDS = (
    "id",
    "kind",
    "provider",
    "ref",
    "activation",
    "requirement",
    "scope",
    "owner",
    "sensitivity",
    "egress_policy",
)
_PUBLIC_LEGACY_KEYS = ("active", "ignored_by_default", "legacy_exception")


def _public_authored_source(raw: dict[str, Any]) -> dict[str, str]:
    values = {
        field: str(raw[field])
        for field in _REQUIRED_SOURCE_FIELDS
        if field in raw
    }
    source_id = values.get("id", "")
    validators = {
        "id": bool(_SKILL_ID_RE.fullmatch(source_id)),
        "kind": values.get("kind") in _TYPED_VALUES["kind"],
        "provider": values.get("provider") == "codex_skill",
        "ref": bool(_SKILL_ID_RE.fullmatch(source_id))
        and values.get("ref") == f"skill:{source_id}",
        "activation": values.get("activation") in _ACTIVATIONS,
        "requirement": values.get("requirement") in _TYPED_VALUES["requirement"],
        "scope": values.get("scope") in _TYPED_VALUES["scope"],
        "owner": bool(_OWNER_RE.fullmatch(values.get("owner", ""))),
        "sensitivity": values.get("sensitivity") in _TYPED_VALUES["sensitivity"],
        "egress_policy": values.get("egress_policy") in _TYPED_VALUES["egress_policy"],
    }
    return {
        field: value if validators[field] else _INVALID_PUBLIC_VALUE
        for field, value in values.items()
    }


def _skill_frontmatter(content: bytes) -> dict[str, Any]:
    text = content.decode("utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing YAML frontmatter")
    try:
        closing_index = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("unterminated YAML frontmatter") from exc
    data = yaml.safe_load("\n".join(lines[1:closing_index])) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter must contain a mapping")
    return data


def _source_mtime(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _skill_metadata(raw: dict[str, Any], codex_home: Path) -> tuple[dict[str, Any], list[str], list[str]]:
    source_id = str(raw.get("id", ""))
    source_label = source_id if _SKILL_ID_RE.fullmatch(source_id) else _INVALID_PUBLIC_VALUE
    ref = str(raw.get("ref", ""))
    issues: list[str] = []
    warnings: list[str] = []
    metadata = {
        "id": source_id,
        "kind": str(raw.get("kind", "")),
        "provider": str(raw.get("provider", "")),
        "ref": ref,
        "activation": str(raw.get("activation", "")),
        "requirement": str(raw.get("requirement", "")),
        "scope": str(raw.get("scope", "")),
        "owner": str(raw.get("owner", "")),
        "sensitivity": str(raw.get("sensitivity", "")),
        "egress_policy": str(raw.get("egress_policy", "")),
        "state": "UNAVAILABLE",
        "source_digest": None,
        "source_mtime": None,
        "body_exported": False,
        "issues": [],
    }

    missing_fields = [field for field in _REQUIRED_SOURCE_FIELDS if not metadata.get(field)]
    if missing_fields:
        issues.append(
            f"guidance source {source_label}: missing required fields: {', '.join(missing_fields)}"
        )
    if metadata["activation"] not in _ACTIVATIONS:
        issues.append(f"guidance source {source_label}: invalid activation")
    for field, allowed in _TYPED_VALUES.items():
        if metadata[field] not in allowed:
            issues.append(f"guidance source {source_label}: invalid {field}")
    if metadata["provider"] != "codex_skill":
        issues.append(f"guidance source {source_label}: unsupported provider")
    if not _SKILL_ID_RE.fullmatch(source_id):
        issues.append("guidance source has invalid id")
    if ref != f"skill:{source_id}":
        issues.append(f"guidance source {source_label}: ref must match its logical skill id")
    if not _OWNER_RE.fullmatch(metadata["owner"]):
        issues.append(f"guidance source {source_label}: invalid owner")
    if issues:
        metadata.update(_public_authored_source(raw))
        metadata["state"] = "INVALID"
        metadata["issues"] = list(issues)
        return metadata, issues, warnings

    skill_path = codex_home / "skills" / source_id / "SKILL.md"
    if not skill_path.is_file():
        warning = f"guidance source {source_id}: skill is unavailable"
        warnings.append(warning)
        metadata["issues"] = [warning]
        return metadata, issues, warnings

    try:
        with skill_path.open("rb") as handle:
            stat_before = os.fstat(handle.fileno())
            content = handle.read()
            stat_after = os.fstat(handle.fileno())
    except OSError:
        issue = f"guidance source {source_id}: skill read failed"
        issues.append(issue)
        metadata["state"] = "INVALID"
        metadata["issues"] = [issue]
        return metadata, issues, warnings

    if (
        stat_before.st_mtime_ns != stat_after.st_mtime_ns
        or stat_before.st_size != stat_after.st_size
    ):
        issue = f"guidance source {source_id}: skill changed during read"
        issues.append(issue)
        metadata["state"] = "INVALID"
        metadata["issues"] = [issue]
        return metadata, issues, warnings

    try:
        frontmatter = _skill_frontmatter(content)
    except (UnicodeError, ValueError, yaml.YAMLError):
        issue = f"guidance source {source_id}: invalid skill metadata"
        issues.append(issue)
        metadata["state"] = "INVALID"
        metadata["issues"] = [issue]
        return metadata, issues, warnings

    if str(frontmatter.get("name", "")) != source_id:
        issue = f"guidance source {source_id}: frontmatter name does not match"
        issues.append(issue)
        metadata["state"] = "INVALID"
        metadata["issues"] = [issue]
        return metadata, issues, warnings

    metadata["state"] = "DISCOVERED"
    metadata["source_digest"] = f"sha256:{hashlib.sha256(content).hexdigest()}"
    metadata["source_mtime"] = _source_mtime(stat_after.st_mtime)
    return metadata, issues, warnings


def resolve_guidance_sources(
    instruction_sources: dict[str, Any],
    *,
    codex_home: str | Path | None = None,
) -> dict[str, Any]:
    """Resolve typed guidance metadata without exporting paths or skill bodies."""

    configured = instruction_sources.get("sources") if isinstance(instruction_sources, dict) else None
    if configured is None:
        configured = []
    if not isinstance(configured, list):
        return {
            "schema_version": GUIDANCE_SCHEMA_VERSION,
            "verdict": "FAIL",
            "sources": [],
            "issues": ["instruction_sources.sources must be a list"],
            "warnings": [],
        }

    root = Path(codex_home) if codex_home is not None else Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    sources: list[dict[str, Any]] = []
    issues: list[str] = []
    warnings: list[str] = []
    seen_ids: set[str] = set()
    for raw in configured:
        if not isinstance(raw, dict):
            issues.append("guidance source must be a mapping")
            continue
        metadata, source_issues, source_warnings = _skill_metadata(raw, root)
        source_id = metadata["id"]
        if source_id in seen_ids:
            duplicate_issue = f"duplicate guidance source id: {source_id}"
            metadata["state"] = "INVALID"
            metadata["issues"] = [*metadata["issues"], duplicate_issue]
            source_issues = [*source_issues, duplicate_issue]
        seen_ids.add(source_id)
        sources.append(metadata)
        issues.extend(source_issues)
        warnings.extend(source_warnings)

    verdict = "FAIL" if issues else "WARN" if warnings else "PASS"
    return {
        "schema_version": GUIDANCE_SCHEMA_VERSION,
        "verdict": verdict,
        "sources": sources,
        "issues": issues,
        "warnings": warnings,
    }


def sanitize_instruction_sources(instruction_sources: dict[str, Any]) -> dict[str, Any]:
    """Preserve legacy metadata while limiting typed sources to their authored contract."""

    if not isinstance(instruction_sources, dict):
        return {}
    public = {
        key: instruction_sources[key]
        for key in _PUBLIC_LEGACY_KEYS
        if key in instruction_sources
    }
    configured = instruction_sources.get("sources")
    if configured is None:
        return public
    if not isinstance(configured, list):
        public["sources"] = []
        return public
    public["sources"] = [
        _public_authored_source(raw)
        for raw in configured
        if isinstance(raw, dict)
    ]
    return public
