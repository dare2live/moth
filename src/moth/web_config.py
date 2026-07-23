"""Configuration boundary for the local Moth Web Console."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
    profile_path: Path | None = None

    def public_metadata(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
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
        else:
            loaded_profile = build_default_profile(repo)
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
                profile_path=profile,
            )
        )
    return WebConsoleConfig(
        host=host,
        port=int(payload["server"]["port"]),
        projects=tuple(projects),
    )
