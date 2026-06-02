from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from moth.adapters.codegraph import run_status as run_codegraph_status
from moth.adapters.complexity import run_analysis as run_complexity_analysis
from moth.checks.dirty_worktree import git_status
from moth.checks.startup import check_profile
from moth.profiles.loader import RepoProfile


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
        "status": status,
        "profile": _jsonable(asdict(profile)),
        "issues": issues,
        "warnings": warnings,
        "dirty_worktree": dirty,
        "codegraph": _jsonable(codegraph),
        "complexity": _jsonable(complexity),
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
        f"- Status: `{report['status']}`",
        f"- Repo: `{profile.get('repo_path', '?')}`",
        f"- Name: `{profile.get('name', '?')}`",
        "",
    ]
    lines.append("## Profile")
    lines.append(f"- CodeGraph root: `{profile.get('codegraph_root', '?')}`")
    lines.append(f"- Complexity command: `{profile.get('complexity_command', [])}`")
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


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
