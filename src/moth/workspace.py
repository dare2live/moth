from __future__ import annotations

from typing import Any

from moth.profiles.loader import discover_profiles
from moth.report import build_profiles_report
from moth.snapshot import build_snapshot
from moth.schema import SNAPSHOT_SCHEMA_VERSION
from moth.schema import utc_now_iso


def _count_status(items: list[dict[str, Any]]) -> tuple[int, int, int]:
    pass_count = sum(1 for item in items if item.get("status") == "PASS")
    warn_count = sum(1 for item in items if item.get("status") == "WARN")
    fail_count = sum(1 for item in items if item.get("status") == "FAIL")
    return pass_count, warn_count, fail_count


def build_workspace_report(workspace_root: str) -> dict[str, Any]:
    profiles_report = build_profiles_report(workspace_root)
    workspace_profiles = discover_profiles(workspace_root)
    snapshots: list[dict[str, Any]] = []
    for profile in workspace_profiles:
        snapshot = build_snapshot(profile)
        snapshots.append(
            {
                "profile": {
                    "kind": profile.kind,
                    "name": profile.name,
                    "repo_path": str(profile.repo_path),
                    "codegraph_root": str(profile.codegraph_root),
                },
                "snapshot": snapshot,
                "status": snapshot.get("status", "UNKNOWN"),
                "issues": snapshot.get("issues") or [],
                "warnings": snapshot.get("warnings") or [],
            }
        )

    snapshot_pass_count, snapshot_warn_count, snapshot_fail_count = _count_status(snapshots)
    issues: list[str] = list(profiles_report.get("issues") or [])
    warnings: list[str] = list(profiles_report.get("warnings") or [])
    if snapshot_fail_count:
        warnings.append(f"{snapshot_fail_count} workspace snapshot(s) failed")
    elif not snapshots and workspace_root:
        warnings.append(f"no workspace snapshots found under {workspace_root}")

    status = "PASS"
    if issues:
        status = "FAIL"
    elif warnings or snapshot_warn_count or snapshot_fail_count:
        status = "WARN"

    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "status": status,
        "workspace_root": workspace_root,
        "profiles_report": profiles_report,
        "snapshots": snapshots,
        "summary": {
            "snapshot_total": len(snapshots),
            "snapshot_pass_count": snapshot_pass_count,
            "snapshot_warn_count": snapshot_warn_count,
            "snapshot_fail_count": snapshot_fail_count,
        },
        "issues": issues,
        "warnings": warnings,
    }


def render_workspace_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Moth workspace",
        "",
        f"- Schema version: `{report.get('schema_version', '?')}`",
        f"- Generated at: `{report.get('generated_at', '?')}`",
        f"- Status: `{report.get('status', '?')}`",
        f"- Workspace root: `{report.get('workspace_root', '?')}`",
        f"- Snapshot total: `{report.get('summary', {}).get('snapshot_total', 0)}`",
        f"- Snapshot PASS: `{report.get('summary', {}).get('snapshot_pass_count', 0)}`",
        f"- Snapshot WARN: `{report.get('summary', {}).get('snapshot_warn_count', 0)}`",
        f"- Snapshot FAIL: `{report.get('summary', {}).get('snapshot_fail_count', 0)}`",
        "",
    ]
    issues = report.get("issues") or []
    warnings = report.get("warnings") or []
    lines.append("## Issues")
    lines.extend(f"- {item}" for item in issues) if issues else lines.append("- none")
    lines.append("")
    lines.append("## Warnings")
    lines.extend(f"- {item}" for item in warnings) if warnings else lines.append("- none")
    lines.append("")
    lines.append("## Workspace snapshots")
    snapshots = report.get("snapshots") or []
    if not snapshots:
        lines.append("- none")
        return "\n".join(lines) + "\n"
    for item in snapshots:
        profile = item.get("profile") or {}
        snapshot = item.get("snapshot") or {}
        lines.append(f"- `{profile.get('name', '?')}` [{item.get('status', '?')}]")
        lines.append(f"  - Repo: `{profile.get('repo_path', '?')}`")
        lines.append(f"  - CodeGraph root: `{profile.get('codegraph_root', '?')}`")
        if snapshot.get("issues"):
            lines.append(f"  - Snapshot issues: {', '.join(snapshot['issues'])}")
        if snapshot.get("warnings"):
            lines.append(f"  - Snapshot warnings: {', '.join(snapshot['warnings'])}")
    return "\n".join(lines) + "\n"
