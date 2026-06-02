from __future__ import annotations

from pathlib import Path

from moth.profiles.loader import RepoProfile


def check_profile(profile: RepoProfile) -> list[str]:
    issues: list[str] = []
    for label, path in (
        ("goal", profile.goal_path),
        ("handoff", profile.handoff_path),
        ("workflow_checkpoint", profile.workflow_checkpoint_path),
        ("quickstart", profile.quickstart_path),
        ("docs_root", profile.docs_root),
    ):
        if not Path(path).exists():
            issues.append(f"missing {label}: {path}")
    if not profile.complexity_command:
        issues.append("missing complexity command")
    return issues
