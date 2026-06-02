from __future__ import annotations

from pathlib import Path

from moth.profiles.loader import RepoProfile


def check_profile(profile: RepoProfile) -> list[str]:
    issues: list[str] = []
    for label, path in (
        ("repo", profile.repo_path),
        ("codegraph_root", profile.codegraph_root),
    ):
        if not Path(path).exists():
            issues.append(f"missing {label}: {path}")
    for label, path in profile.evidence_paths.items():
        if not Path(path).exists():
            issues.append(f"missing {label}: {path}")
    if not profile.complexity_command:
        issues.append("missing complexity command")
    return issues
