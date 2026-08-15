"""Configuration boundary for the local Moth Web Console."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from moth.profiles.loader import RepoProfile, build_default_profile, load_profile


@dataclass(frozen=True, slots=True)
class WebProject:
    id: str
    name: str
    description: str
    repo_path: Path
    profile: RepoProfile
    profile_state: str
    profile_path: Path | None = None

    def public_metadata(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "profile_state": self.profile_state,
        }


@dataclass(frozen=True, slots=True)
class WebConsoleConfig:
    host: str
    port: int
    projects: tuple[WebProject, ...]

    def project(self, project_id: str) -> WebProject:
        for project in self.projects:
            if project.id == project_id:
                return project
        raise KeyError(project_id)


@lru_cache(maxsize=1)
def load_web_policy() -> dict[str, Any]:
    payload = yaml.safe_load(
        files("moth").joinpath("web_policy.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict) or payload.get("kind") != "moth_web_policy":
        raise ValueError("web policy must be a moth_web_policy mapping")
    if not isinstance(payload.get("config"), dict):
        raise ValueError("web policy config must be a mapping")
    if not isinstance(payload.get("network"), dict):
        raise ValueError("web policy network must be a mapping")
    if not isinstance(payload.get("api"), dict):
        raise ValueError("web policy api must be a mapping")
    return payload


def _schema() -> dict[str, Any]:
    return json.loads(
        files("moth.schemas")
        .joinpath("moth.web-console.schema.json")
        .read_text(encoding="utf-8")
    )


def _resolve_path(base: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _load_implicit_profile(repo: Path) -> tuple[RepoProfile, Path | None, str]:
    profile_path = repo / ".moth" / "profile.yaml"
    if not profile_path.exists():
        return build_default_profile(repo), None, "ephemeral"
    if profile_path.is_symlink():
        return build_default_profile(repo), profile_path, "invalid"
    try:
        profile = load_profile(profile_path)
    except (OSError, ValueError):
        try:
            payload = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            return build_default_profile(repo), profile_path, "invalid"
        if not isinstance(payload, dict):
            return build_default_profile(repo), profile_path, "invalid"
        evidence_paths: dict[str, Path] = {}
        for label, raw_path in (payload.get("evidence_paths") or {}).items():
            if not isinstance(raw_path, str) or not raw_path:
                continue
            candidate = Path(raw_path).expanduser()
            candidate = (
                (repo / candidate).resolve()
                if not candidate.is_absolute()
                else candidate.resolve()
            )
            try:
                candidate.relative_to(repo)
            except ValueError:
                continue
            evidence_paths[str(label)] = candidate
        instruction_sources = payload.get("instruction_sources")
        profile = replace(
            build_default_profile(repo),
            name=str(payload.get("name") or repo.name),
            evidence_paths=evidence_paths,
            instruction_sources=(
                {str(key): value for key, value in instruction_sources.items()}
                if isinstance(instruction_sources, dict)
                else {"sources": []}
            ),
            complexity_excludes=[
                str(item)
                for item in payload.get("complexity_excludes") or []
                if isinstance(item, str)
            ],
            notes="Safe projection of a local profile that requires migration.",
        )
        return profile, profile_path, "partial"
    if profile.repo_path.resolve() != repo:
        return build_default_profile(repo), profile_path, "invalid"
    return profile, profile_path, "configured"


def load_web_console_config(path: str | Path) -> WebConsoleConfig:
    declared_path = Path(path).expanduser()
    policy = load_web_policy()
    if declared_path.is_symlink():
        raise ValueError("web console config cannot be a symlink")
    config_path = declared_path.resolve()
    try:
        with config_path.open("rb") as handle:
            raw = handle.read(int(policy["config"]["max_bytes"]) + 1)
    except OSError:
        raise ValueError("web console config is unavailable") from None
    if len(raw) > int(policy["config"]["max_bytes"]):
        raise ValueError("web console config exceeds configured bound")
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError):
        raise ValueError("web console config is malformed") from None
    errors = sorted(
        Draft202012Validator(_schema()).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        location = ".".join(str(part) for part in errors[0].absolute_path) or "<root>"
        raise ValueError(f"web console config schema: {location}: {errors[0].message}")
    assert isinstance(payload, dict)
    host = str(payload["server"]["host"])
    if host not in set(map(str, policy["network"]["loopback_hosts"])):
        raise ValueError("web console server host must be loopback")
    project_specs = payload["projects"]
    if len(project_specs) > int(policy["config"]["max_projects"]):
        raise ValueError("web console project count exceeds configured bound")
    ids = [str(item["id"]) for item in project_specs]
    if len(ids) != len(set(ids)):
        raise ValueError("web console project ids must be unique")

    base = config_path.parent
    projects: list[WebProject] = []
    for item in project_specs:
        repo = _resolve_path(base, str(item["repo"]))
        if not repo.is_dir():
            raise ValueError(f"web console project {item['id']} repo is unavailable")
        profile_value = item.get("profile")
        profile = _resolve_path(repo, str(profile_value)) if profile_value else None
        loaded_profile: RepoProfile
        profile_state: str
        if profile is not None:
            try:
                profile.relative_to(repo)
            except ValueError:
                raise ValueError(
                    f"web console project {item['id']} profile must stay inside its repo"
                ) from None
            if not profile.is_file():
                raise ValueError(
                    f"web console project {item['id']} profile is unavailable"
                )
            loaded_profile = load_profile(profile)
            profile_state = "configured"
        else:
            loaded_profile, profile, profile_state = _load_implicit_profile(repo)
        if loaded_profile.repo_path.resolve() != repo:
            raise ValueError(
                f"web console project {item['id']} profile must describe its declared repo"
            )
        projects.append(
            WebProject(
                id=str(item["id"]),
                name=str(item["name"]),
                description=str(item.get("description") or ""),
                repo_path=repo,
                profile=loaded_profile,
                profile_state=profile_state,
                profile_path=profile,
            )
        )
    return WebConsoleConfig(
        host=host,
        port=int(payload["server"]["port"]),
        projects=tuple(projects),
    )
