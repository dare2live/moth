"""User-scoped Web Console project registration."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback keeps process safety.
    fcntl = None

from moth.web_config import load_web_console_config


_PROCESS_REGISTRY_LOCK = threading.RLock()


def default_web_config_path() -> Path:
    override = os.environ.get("MOTH_WEB_CONFIG")
    if override:
        return Path(override).expanduser().absolute()
    config_root = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_root).expanduser() if config_root else Path.home() / ".config"
    return (base / "moth" / "web.yaml").absolute()


def _project_id(name: str, repo: Path) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_") or "project"
    return slug[:48] + "-" + hashlib.sha256(str(repo).encode()).hexdigest()[:10]


@contextmanager
def _registry_lock(path: Path):
    lock_path = path.with_name(f".{path.name}.lock")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    with _PROCESS_REGISTRY_LOCK:
        descriptor = os.open(lock_path, flags, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


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
    path = declared_path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _registry_lock(path):
        if declared_path.is_symlink():
            raise ValueError("web project registry cannot be a symlink")
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
                "description": "Registered for safe-view inspection",
                "repo": str(repo),
            }
        )
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
