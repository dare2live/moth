from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from moth.adapters.codegraph import run_status as run_codegraph_status
from moth.adapters.codegraph import run_sync as run_codegraph_sync
from moth.adapters.complexity import build_complexity_diff_report
from moth.adapters.complexity import run_analysis as run_complexity_analysis
from moth.adapters.complexity import load_complexity_baseline
from moth.checks.dirty_worktree import git_status
from moth.checks.startup import check_profile
from moth.profiles.loader import RepoProfile
from moth.profiles.loader import discover_profiles
from moth.profiles.loader import list_profiles
from moth.schema import SNAPSHOT_SCHEMA_VERSION
from moth.schema import utc_now_iso


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "as_posix"):
        return str(value)
    return value


def _warnings_from_dirty(dirty: list[str]) -> list[str]:
    if not dirty:
        return []
    return [f"dirty worktree: {len(dirty)} path(s)"]


def _warnings_from_codegraph(codegraph: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    state = str(codegraph.get("state") or "").lower().replace("_", " ")
    if state and state != "up to date":
        warnings.append(f"codegraph: {state}")
    for item in codegraph.get("issues") or []:
        warnings.append(f"codegraph: {item}")
    return warnings


def _warnings_from_complexity(complexity: dict[str, Any]) -> list[str]:
    diff = complexity.get("diff") or {}
    if diff.get("status") == "compared" and int(diff.get("new_high_count") or 0):
        return [
            f"complexity new high findings: {diff.get('new_high_count')} (baseline compared)",
        ]
    summary = complexity.get("summary") or {}
    finding_count = int(summary.get("finding_count") or 0)
    if not finding_count:
        return []
    severity_counts = summary.get("severity_counts") or {}
    high = int(severity_counts.get("high") or 0)
    medium = int(severity_counts.get("medium") or 0)
    info = int(severity_counts.get("info") or 0)
    return [f"complexity hotspots: {finding_count} findings ({high} high, {medium} medium, {info} info)"]


def _empty_complexity_report() -> dict[str, Any]:
    return {
        "command": [],
        "returncode": 0,
        "stdout": "",
        "stderr": "",
        "verdict": "SKIP",
        "issues": ["missing complexity command"],
        "findings": [],
        "summary": {
            "finding_count": 0,
            "severity_counts": {},
            "kind_counts": {},
            "high_count": 0,
            "medium_count": 0,
            "info_count": 0,
        },
    }


def build_report(profile: RepoProfile) -> dict[str, Any]:
    issues = check_profile(profile)
    dirty = git_status(profile.repo_path)
    codegraph = run_codegraph_status(profile.codegraph_root)
    complexity = _empty_complexity_report()
    if profile.complexity_command:
        complexity = run_complexity_analysis(profile.repo_path, profile.complexity_command)
    baseline_findings, baseline_status = load_complexity_baseline(profile.complexity_baseline_path)
    complexity_diff = build_complexity_diff_report(
        complexity.get("findings") or [],
        baseline_findings,
        baseline_status=baseline_status,
    )
    complexity["baseline"] = {
        "path": str(profile.complexity_baseline_path) if profile.complexity_baseline_path else None,
        "status": baseline_status,
    }
    complexity["diff"] = complexity_diff

    warnings = []
    warnings.extend(_warnings_from_dirty(dirty))
    warnings.extend(_warnings_from_codegraph(codegraph))
    warnings.extend(_warnings_from_complexity(complexity))

    if codegraph.get("verdict") == "FAIL":
        issues.extend(codegraph.get("issues") or ["codegraph status failed"])
    if complexity.get("verdict") == "FAIL":
        issues.extend(complexity.get("issues") or ["complexity analysis failed"])
    status = "PASS"
    if issues:
        status = "FAIL"
    elif warnings:
        status = "WARN"

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "status": status,
        "profile": _jsonable(asdict(profile)),
        "issues": issues,
        "warnings": warnings,
        "dirty_worktree": dirty,
        "codegraph": _jsonable(codegraph),
        "complexity": _jsonable(complexity),
    }


def build_sync_report(profile: RepoProfile) -> dict[str, Any]:
    sync = run_codegraph_sync(profile.codegraph_root)
    snapshot = build_report(profile)
    issues = list(snapshot.get("issues") or [])
    warnings = list(snapshot.get("warnings") or [])
    if sync.get("verdict") == "FAIL":
        issues = [*issues, *(sync.get("issues") or ["codegraph sync failed"])]
    elif sync.get("verdict") == "WARN":
        warnings = [*warnings, *(sync.get("issues") or ["codegraph sync returned warning"])]

    status = snapshot.get("status", "PASS")
    if issues:
        status = "FAIL"
    elif warnings or sync.get("verdict") == "WARN":
        status = "WARN"

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "status": status,
        "profile": snapshot["profile"],
        "sync": _jsonable(sync),
        "snapshot": snapshot,
        "issues": issues,
        "warnings": warnings,
    }


def _serialize_profile(profile: RepoProfile) -> dict[str, Any]:
    issues = check_profile(profile)
    status = "PASS" if not issues else "WARN"
    return {
        "kind": profile.kind,
        "name": profile.name,
        "repo_path": str(profile.repo_path),
        "codegraph_root": str(profile.codegraph_root),
        "complexity_command": profile.complexity_command,
        "complexity_baseline_path": str(profile.complexity_baseline_path) if profile.complexity_baseline_path else None,
        "evidence_paths": {label: str(path) for label, path in profile.evidence_paths.items()},
        "notes": profile.notes,
        "status": status,
        "issues": issues,
    }


def _count_status(items: list[dict[str, Any]]) -> tuple[int, int]:
    pass_count = sum(1 for item in items if item.get("status") == "PASS")
    warn_count = sum(1 for item in items if item.get("status") != "PASS")
    return pass_count, warn_count


def build_profiles_report(workspace_root: str | Path | None = None) -> dict[str, Any]:
    registry_profiles = [_serialize_profile(profile) for profile in list_profiles()]
    workspace_profiles = (
        [_serialize_profile(profile) for profile in discover_profiles(workspace_root)]
        if workspace_root is not None
        else []
    )

    issues: list[str] = []
    warnings: list[str] = []
    if not registry_profiles:
        warnings.append("no bundled profiles found")
    if workspace_root is not None and not workspace_profiles:
        warnings.append(f"no workspace-local profiles found under {workspace_root}")

    registry_pass_count, registry_warn_count = _count_status(registry_profiles)
    workspace_pass_count, workspace_warn_count = _count_status(workspace_profiles)
    total_warn_count = registry_warn_count + workspace_warn_count

    status = "PASS"
    if issues:
        status = "FAIL"
    elif warnings or total_warn_count:
        if total_warn_count:
            warnings.append(f"{total_warn_count} profile(s) need attention")
        status = "WARN"

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "status": status,
        "workspace_root": str(workspace_root) if workspace_root is not None else None,
        "registry_profiles": registry_profiles,
        "workspace_profiles": workspace_profiles,
        "summary": {
            "registry_total": len(registry_profiles),
            "registry_pass_count": registry_pass_count,
            "registry_warn_count": registry_warn_count,
            "workspace_total": len(workspace_profiles),
            "workspace_pass_count": workspace_pass_count,
            "workspace_warn_count": workspace_warn_count,
        },
        "issues": issues,
        "warnings": warnings,
    }


def _render_list(title: str, items: list[str]) -> list[str]:
    lines = [f"## {title}"]
    if items:
        lines.extend(f"- {item}" for item in items)
    else:
        lines.append("- none")
    return lines


def _render_mapping(title: str, values: dict[str, Any], limit: int = 10) -> list[str]:
    lines = [f"## {title}"]
    if not values:
        lines.append("- none")
        return lines
    for key, value in list(values.items())[:limit]:
        lines.append(f"- {key}: `{value}`")
    if len(values) > limit:
        lines.append(f"- ... {len(values) - limit} more")
    return lines


def _render_findings(findings: list[dict[str, Any]], limit: int = 5) -> list[str]:
    lines = ["## Complexity top findings"]
    if not findings:
        lines.append("- none")
        return lines
    for finding in findings[:limit]:
        path = finding.get("path", "?")
        line = finding.get("line", "?")
        severity = str(finding.get("severity", "")).upper()
        kind = finding.get("kind", "finding")
        message = finding.get("message", "")
        lines.append(f"- `{path}:{line}` [{severity}] {kind}: {message}")
    if len(findings) > limit:
        lines.append(f"- ... {len(findings) - limit} more")
    return lines


def render_markdown(report: dict[str, Any]) -> str:
    profile = report.get("profile") or {}
    lines = [
        "# Moth report",
        "",
        f"- Schema version: `{report.get('schema_version', '?')}`",
        f"- Generated at: `{report.get('generated_at', '?')}`",
        f"- Status: `{report['status']}`",
        f"- Repo: `{profile.get('repo_path', '?')}`",
        f"- Name: `{profile.get('name', '?')}`",
        "",
    ]
    lines.append("## Profile")
    lines.append(f"- CodeGraph root: `{profile.get('codegraph_root', '?')}`")
    lines.append(f"- Complexity command: `{profile.get('complexity_command', [])}`")
    if profile.get("complexity_baseline_path"):
        lines.append(f"- Complexity baseline path: `{profile['complexity_baseline_path']}`")
    if profile.get("evidence_paths"):
        lines.extend(_render_mapping("Evidence paths", profile["evidence_paths"]))
    lines.append("")
    lines.extend(_render_list("Issues", report.get("issues") or []))
    lines.append("")
    lines.extend(_render_list("Warnings", report.get("warnings") or []))
    lines.append("")
    lines.extend(_render_list("Dirty worktree", report.get("dirty_worktree") or []))
    lines.append("")
    codegraph = report.get("codegraph") or {}
    lines.append("## CodeGraph")
    lines.append(f"- Verdict: `{codegraph.get('verdict', 'UNKNOWN')}`")
    lines.append(f"- State: `{codegraph.get('state', 'UNKNOWN')}`")
    lines.append(f"- Index up to date: `{codegraph.get('index_up_to_date', False)}`")
    if codegraph.get("index_statistics"):
        lines.extend(_render_mapping("Index statistics", codegraph["index_statistics"]))
    if codegraph.get("nodes_by_kind"):
        lines.extend(_render_mapping("Nodes by kind", codegraph["nodes_by_kind"]))
    if codegraph.get("files_by_language"):
        lines.extend(_render_mapping("Files by language", codegraph["files_by_language"]))
    if codegraph.get("issues"):
        lines.extend(_render_list("CodeGraph issues", codegraph["issues"]))
    lines.append("")
    complexity = report.get("complexity") or {}
    lines.append("## Complexity")
    lines.append(f"- Verdict: `{complexity.get('verdict', 'UNKNOWN')}`")
    baseline = complexity.get("baseline") or {}
    lines.append(f"- Baseline status: `{baseline.get('status', 'UNKNOWN')}`")
    if baseline.get("path"):
        lines.append(f"- Baseline path: `{baseline.get('path')}`")
    diff = complexity.get("diff") or {}
    if diff:
        lines.append(f"- Diff status: `{diff.get('status', 'UNKNOWN')}`")
        lines.append(f"- New high findings: `{diff.get('new_high_count', 0)}`")
        lines.append(f"- New findings: `{diff.get('new_count', 0)}`")
        lines.append(f"- Resolved findings: `{diff.get('resolved_count', 0)}`")
    summary = complexity.get("summary") or {}
    lines.append(f"- Findings: `{summary.get('finding_count', 0)}`")
    if summary.get("severity_counts"):
        lines.extend(_render_mapping("Severity counts", summary["severity_counts"]))
    if summary.get("kind_counts"):
        lines.extend(_render_mapping("Kind counts", summary["kind_counts"]))
    if complexity.get("issues"):
        lines.extend(_render_list("Complexity issues", complexity["issues"]))
    lines.extend(_render_findings(complexity.get("findings") or []))
    return "\n".join(lines) + "\n"


def render_profiles_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Moth profiles",
        "",
        f"- Schema version: `{report.get('schema_version', '?')}`",
        f"- Generated at: `{report.get('generated_at', '?')}`",
        f"- Status: `{report.get('status', '?')}`",
        f"- Workspace root: `{report.get('workspace_root') or 'none'}`",
        f"- Bundled total: `{report.get('summary', {}).get('registry_total', 0)}`",
        f"- Bundled PASS: `{report.get('summary', {}).get('registry_pass_count', 0)}`",
        f"- Bundled WARN: `{report.get('summary', {}).get('registry_warn_count', 0)}`",
        f"- Workspace total: `{report.get('summary', {}).get('workspace_total', 0)}`",
        f"- Workspace PASS: `{report.get('summary', {}).get('workspace_pass_count', 0)}`",
        f"- Workspace WARN: `{report.get('summary', {}).get('workspace_warn_count', 0)}`",
        "",
    ]
    lines.extend(_render_list("Issues", report.get("issues") or []))
    lines.append("")
    lines.extend(_render_list("Warnings", report.get("warnings") or []))
    lines.append("")
    for title, items in (
        ("Bundled profiles", report.get("registry_profiles") or []),
        ("Workspace profiles", report.get("workspace_profiles") or []),
    ):
        lines.append(f"## {title}")
        if not items:
            lines.append("- none")
            lines.append("")
            continue
        for item in items:
            lines.append(f"- `{item.get('name', '?')}` [{item.get('status', '?')}]")
            lines.append(f"  - Repo: `{item.get('repo_path', '?')}`")
            lines.append(f"  - CodeGraph root: `{item.get('codegraph_root', '?')}`")
            if item.get("complexity_baseline_path"):
                lines.append(f"  - Complexity baseline: `{item['complexity_baseline_path']}`")
            if item.get("notes"):
                lines.append(f"  - Notes: {item['notes']}")
            if item.get("issues"):
                lines.append(f"  - Issues: {', '.join(item['issues'])}")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
