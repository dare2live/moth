"""Portable one-call inspection for plugin and CLI consumers."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from moth.orchestration import prepare_task_context
from moth.snapshot import build_snapshot


_URL_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"`<>()\[\]{}]+")
_WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:[A-Z]:[\\/]|\\\\)[^\s'\"`<>()\[\]{},;]+"
)
_POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_:/])/[^\s'\"`<>()\[\]{},;]+"
)
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)


def sanitize_public_text(value: Any) -> str:
    text = str(value)
    preserved_urls: list[str] = []

    def preserve_url(match: re.Match[str]) -> str:
        preserved_urls.append(match.group(0))
        return f"\ue000moth-url-{len(preserved_urls) - 1}\ue001"

    text = _URL_RE.sub(preserve_url, text)
    text = _WINDOWS_ABSOLUTE_PATH_RE.sub("<private-path>", text)
    text = _POSIX_ABSOLUTE_PATH_RE.sub("<private-path>", text)
    for index, url in enumerate(preserved_urls):
        text = text.replace(f"\ue000moth-url-{index}\ue001", url)
    return _EMAIL_RE.sub("<private-email>", text)


def sanitize_public_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_public_text(value)
    if isinstance(value, dict):
        return {key: sanitize_public_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize_public_value(item) for item in value]
    return value


def _portable_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Whitelist public summaries; never forward raw commands, streams, or paths."""

    codegraph = snapshot.get("codegraph") or {}
    complexity = snapshot.get("complexity") or {}
    coupling = snapshot.get("coupling") or {}
    assertions = snapshot.get("assertions") or {}
    public_snapshot = {
        "schema_version": snapshot.get("schema_version"),
        "status": snapshot.get("status"),
        "issues": [sanitize_public_text(item) for item in snapshot.get("issues") or []],
        "warnings": [sanitize_public_text(item) for item in snapshot.get("warnings") or []],
        "dirty_worktree_count": len(snapshot.get("dirty_worktree") or []),
        "project_model": snapshot.get("project_model"),
        "codegraph": {
            "verdict": codegraph.get("verdict"),
            "state": codegraph.get("state"),
            "index_up_to_date": codegraph.get("index_up_to_date"),
            "index_statistics": codegraph.get("index_statistics"),
        },
        "complexity": {
            "verdict": complexity.get("verdict"),
            "summary": complexity.get("summary"),
            "diff": complexity.get("diff"),
        },
        "coupling": {
            "verdict": coupling.get("verdict"),
            "fail_count": len(coupling.get("fails") or []),
            "warn_count": len(coupling.get("warns") or []),
        },
        "import_cycles": snapshot.get("import_cycles"),
        "tool_evidence": snapshot.get("tool_evidence"),
        "assertions": {
            "verdict": assertions.get("verdict"),
            "totals": assertions.get("totals"),
        },
    }
    return sanitize_public_value(public_snapshot)


def build_inspection(profile: Any, *, task_kind: str, run_id: str, receipts: list[dict[str, Any]], codex_home: str | Path) -> dict[str, Any]:
    raw_snapshot = build_snapshot(profile)
    orchestration = prepare_task_context(
        profile.instruction_sources,
        task_kind=task_kind,
        run_id=run_id,
        receipts=receipts,
        codex_home=codex_home,
    )
    project_health = str(raw_snapshot.get("status", "FAIL"))
    readiness = orchestration["decision_context"]["context_readiness"]
    status = (
        "FAIL"
        if project_health == "FAIL"
        else "NEEDS_EXECUTOR"
        if readiness == "BLOCKED"
        else "CONTEXT_SELF_ATTESTED"
        if readiness == "SELF_ATTESTED"
        else project_health
    )
    inspection = {
        "schema_version": "moth.inspection.v1",
        "status": status,
        "project_health": project_health,
        "context_readiness": readiness,
        "snapshot": _portable_snapshot(raw_snapshot),
        "orchestration": orchestration,
    }
    return sanitize_public_value(inspection)


def build_failed_inspection(error: Any) -> dict[str, Any]:
    """Return one portable failure shape shared by every inspection renderer."""

    message = f"inspection failed: {sanitize_public_text(error)}"
    return {
        "schema_version": "moth.inspection.v1",
        "status": "FAIL",
        "project_health": "UNKNOWN",
        "context_readiness": "BLOCKED",
        "issues": [message],
        "snapshot": {
            "schema_version": None,
            "status": "FAIL",
            "issues": [message],
            "warnings": [],
            "dirty_worktree_count": 0,
        },
        "orchestration": {
            "decision_context": {
                "context_readiness": "BLOCKED",
                "ordered_guidance_sources": [],
                "missing_required_sources": [],
            }
        },
    }


def render_inspection_markdown(result: dict[str, Any]) -> str:
    orchestration = result.get("orchestration")
    if not isinstance(orchestration, dict):
        orchestration = {}
    context = orchestration.get("decision_context")
    if not isinstance(context, dict):
        context = {}
    lines = [
        "# Moth inspection", "",
        f"- Status: `{result.get('status', 'FAIL')}`",
        f"- Project health: `{result.get('project_health', 'UNKNOWN')}`",
        f"- Context readiness: `{result.get('context_readiness', 'BLOCKED')}`",
    ]
    if context.get("ordered_guidance_sources"):
        lines.append("- Guidance order: " + " -> ".join(context["ordered_guidance_sources"]))
    if context.get("missing_required_sources"):
        lines.append("- Missing verified sources: " + ", ".join(context["missing_required_sources"]))
    issues = result.get("issues")
    if isinstance(issues, list) and issues:
        lines.extend(["", "## Issues"])
        lines.extend(f"- {sanitize_public_text(item)}" for item in issues)
    return "\n".join(lines) + "\n"
