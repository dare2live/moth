"""Merge project guidance declarations with the user-owned Moth registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_guidance_registry(profile_sources: dict[str, Any], *, codex_home: str | Path) -> dict[str, Any]:
    issues: list[str] = []
    profile = profile_sources.get("sources", []) if isinstance(profile_sources, dict) else []
    if not isinstance(profile, list):
        issues.append("profile guidance sources must be a list")
        profile = []
    registry_path = Path(codex_home) / "moth" / "guidance.yaml"
    user: list[Any] = []
    if registry_path.is_file():
        try:
            payload = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            issues.append("user guidance registry is invalid")
            payload = {}
        if payload.get("kind") != "moth_guidance_registry" or not isinstance(payload.get("sources"), list):
            issues.append("user guidance registry sources must be a list")
        else:
            user = payload["sources"]
    if any(not isinstance(item, dict) for item in user):
        issues.append("user guidance registry sources must contain mappings")
        user = [item for item in user if isinstance(item, dict)]
    if any(not isinstance(item, dict) for item in profile):
        issues.append("profile guidance sources must contain mappings")
        profile = [item for item in profile if isinstance(item, dict)]
    merged: list[dict[str, Any]] = []
    origins: dict[str, str] = {}
    seen: dict[str, dict[str, Any]] = {}
    for origin, items in (("user_registry", user), ("profile", profile)):
        for raw in items:
            item = {str(key): value for key, value in raw.items()}
            source_id = str(item.get("id", ""))
            if source_id in seen:
                if seen[source_id] != item:
                    issues.append(f"conflicting guidance source id: {source_id}")
                continue
            seen[source_id] = item
            merged.append(item)
            origins[source_id] = origin
    return {
        "schema_version": "moth.guidance-registry.v1",
        "verdict": "FAIL" if issues else "PASS",
        "sources": merged,
        "origins": origins,
        "issues": issues,
    }
