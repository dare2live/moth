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
    if profile.complexity_baseline_path and not Path(profile.complexity_baseline_path).exists():
        issues.append(f"missing complexity baseline: {profile.complexity_baseline_path}")
    for label, path in profile.evidence_paths.items():
        if not Path(path).exists():
            issues.append(f"missing {label}: {path}")
    for pack_path in profile.assertion_packs:
        if not Path(pack_path).exists():
            issues.append(f"missing assertion pack: {pack_path}")
    if not profile.complexity_command:
        issues.append("missing complexity command")
    return issues
