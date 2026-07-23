"""User-scoped Web Console project registration."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from moth.web_config import load_web_console_config


def default_web_config_path() -> Path:
    override = os.environ.get("MOTH_WEB_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    config_root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_root).expanduser() if config_root else Path.home() / ".config"
    return (base / "moth" / "web.yaml").resolve()


def _project_id(name: str, repo: Path) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_") or "project"
    return slug[:48] + "-" + hashlib.sha256(str(repo).encode()).hexdigest()[:10]


def register_web_project(
    repo_path: str | Path,
    *,
    name: str | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    repo = Path(repo_path).expanduser().resolve()
    if not repo.is_dir():
        raise ValueError("web project repository is unavailable")
    declared_path = (
        Path(config_path).expanduser()
        if config_path is not None
        else default_web_config_path()
    )
    if declared_path.is_symlink():
        raise ValueError("web project registry cannot be a symlink")
    path = declared_path.resolve()
    if path.exists():
        config = load_web_console_config(path)
        for project in config.projects:
            if project.repo_path == repo:
                return {
                    "config_path": str(path),
                    "project_id": project.id,
                    "created": False,
                }
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("web project registry must contain a mapping")
    else:
        payload = {
            "schema_version": "moth.web-console.v1",
            "server": {"host": "127.0.0.1", "port": 8765},
            "projects": [],
        }
    projects = payload["projects"]
    display_name = name or repo.name
    project_id = _project_id(display_name, repo)
    projects.append(
        {
            "id": project_id,
            "name": display_name,
            "description": "Registered by moth init for safe-view inspection",
            "repo": str(repo),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".web-",
        suffix=".yaml",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
    try:
        load_web_console_config(temporary)
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"config_path": str(path), "project_id": project_id, "created": True}
