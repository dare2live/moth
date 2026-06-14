from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = ROOT / "profiles"


@dataclass(slots=True)
class RepoProfile:
    kind: str
    name: str
    repo_path: Path
    codegraph_root: Path
    complexity_command: list[str]
    complexity_baseline_path: Path | None = None
    evidence_paths: dict[str, Path] = field(default_factory=dict)
    instruction_sources: dict[str, Any] = field(default_factory=dict)
    assertion_packs: list[Path] = field(default_factory=list)
    notes: str = ""


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping")
    return raw


def _resolve(base: Path, value: Any) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (base / path).resolve()


def _load_evidence_paths(data: dict[str, Any], base: Path) -> dict[str, Path]:
    raw = data.get("evidence_paths")
    if isinstance(raw, dict):
        return {str(label): _resolve(base, value) for label, value in raw.items()}

    legacy_keys = {
        "goal": data.get("goal_path"),
        "handoff": data.get("handoff_path"),
        "workflow_checkpoint": data.get("workflow_checkpoint_path"),
        "quickstart": data.get("quickstart_path"),
        "docs": data.get("docs_root"),
    }
    return {
        label: _resolve(base, value)
        for label, value in legacy_keys.items()
        if value is not None
    }


def _load_instruction_sources(data: dict[str, Any]) -> dict[str, Any]:
    """Preserve policy-source metadata as authored in the profile."""

    raw = data.get("instruction_sources")
    if not isinstance(raw, dict):
        return {}
    return {str(label): value for label, value in raw.items()}


def load_profile(ref: str | Path) -> RepoProfile:
    path = Path(ref)
    if not path.is_absolute():
        if path.suffix:
            # 相对的文件路径 (e.g. `.moth/profile.yaml`) 相对**调用者 cwd** 解析,
            # 不是 moth 仓 ROOT (修: 否则 `moth profile .moth/profile.yaml` 在别的项目下
            # 会读成 moth 仓的同名文件, 须用绝对路径才正常 — lifehack 2026-06-14 反例)。
            path = (Path.cwd() / path).resolve()
        else:
            path = (PROFILES_DIR / f"{path.name}.yaml").resolve()
    data = _load_yaml(path)
    base = Path(str(data["repo_path"]))
    baseline_path = data.get("complexity_baseline_path")
    return RepoProfile(
        kind=str(data.get("kind", "profile")),
        name=str(data["name"]),
        repo_path=base,
        codegraph_root=_resolve(base, data["codegraph_root"]),
        complexity_command=[str(part) for part in data.get("complexity_command", [])],
        complexity_baseline_path=_resolve(base, baseline_path) if baseline_path else None,
        evidence_paths=_load_evidence_paths(data, base),
        instruction_sources=_load_instruction_sources(data),
        assertion_packs=[_resolve(base, item) for item in (data.get("assertion_packs") or [])],
        notes=str(data.get("notes", "")),
    )


def list_profiles() -> list[RepoProfile]:
    if not PROFILES_DIR.exists():
        return []
    profiles = [load_profile(path) for path in sorted(PROFILES_DIR.glob("*.yaml"))]
    return [profile for profile in profiles if profile.kind == "profile"]


def discover_profiles(search_root: str | Path) -> list[RepoProfile]:
    root = Path(search_root).resolve()
    if not root.exists():
        return []
    profile_paths = sorted(
        {
            path.resolve()
            for path in root.rglob("profile.yaml")
            if path.parent.name == ".moth"
        }
    )
    profiles = [load_profile(path) for path in profile_paths]
    return [profile for profile in profiles if profile.kind == "profile"]


def match_profile(repo_path: str | Path) -> RepoProfile | None:
    target = Path(repo_path).resolve()
    local_profile_path = target / ".moth" / "profile.yaml"
    if local_profile_path.exists():
        return load_profile(local_profile_path)
    for profile in list_profiles():
        if profile.repo_path.resolve() == target:
            return profile
    return None
