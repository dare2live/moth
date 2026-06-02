from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = ROOT / "profiles"


@dataclass(slots=True)
class RepoProfile:
    name: str
    repo_path: Path
    goal_path: Path
    handoff_path: Path
    workflow_checkpoint_path: Path
    quickstart_path: Path
    docs_root: Path
    codegraph_root: Path
    complexity_command: list[str]
    notes: str = ""


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping")
    return raw


def _resolve(base: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base / path).resolve()


def load_profile(ref: str | Path) -> RepoProfile:
    path = Path(ref)
    if not path.is_absolute():
        if path.suffix:
            path = (ROOT / path).resolve()
        else:
            path = (PROFILES_DIR / f"{path.name}.yaml").resolve()
    data = _load_yaml(path)
    base = Path(str(data["repo_path"]))
    return RepoProfile(
        name=str(data["name"]),
        repo_path=base,
        goal_path=_resolve(base, data["goal_path"]),
        handoff_path=_resolve(base, data["handoff_path"]),
        workflow_checkpoint_path=_resolve(base, data["workflow_checkpoint_path"]),
        quickstart_path=_resolve(base, data["quickstart_path"]),
        docs_root=_resolve(base, data["docs_root"]),
        codegraph_root=_resolve(base, data["codegraph_root"]),
        complexity_command=[str(part) for part in data.get("complexity_command", [])],
        notes=str(data.get("notes", "")),
    )


def list_profiles() -> list[RepoProfile]:
    if not PROFILES_DIR.exists():
        return []
    return [load_profile(path) for path in sorted(PROFILES_DIR.glob("*.yaml"))]


def match_profile(repo_path: str | Path) -> RepoProfile | None:
    target = Path(repo_path).resolve()
    for profile in list_profiles():
        if profile.repo_path.resolve() == target:
            return profile
    return None
