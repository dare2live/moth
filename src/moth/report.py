from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

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


def build_report(profile: RepoProfile) -> dict[str, Any]:
    issues = check_profile(profile)
    dirty = git_status(profile.repo_path)
    status = "PASS"
    if issues or dirty:
        status = "WARN" if not issues else "FAIL"
    return {
        "status": status,
        "profile": _jsonable(asdict(profile)),
        "issues": issues,
        "dirty_worktree": dirty,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Moth report",
        "",
        f"- Status: `{report['status']}`",
        f"- Repo: `{report['profile']['repo_path']}`",
        f"- Name: `{report['profile']['name']}`",
        "",
        "## Issues",
    ]
    issues = report.get("issues") or []
    if issues:
        lines.extend(f"- {item}" for item in issues)
    else:
        lines.append("- none")
    lines.extend(["", "## Dirty worktree"])
    dirty = report.get("dirty_worktree") or []
    if dirty:
        lines.extend(f"- {item}" for item in dirty)
    else:
        lines.append("- clean")
    return "\n".join(lines) + "\n"


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
