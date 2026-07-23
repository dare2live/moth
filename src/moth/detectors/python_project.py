"""Truth-source-first detector for Python project manifests."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any


def _empty(state: str, *, issue: str | None = None, warning: str | None = None) -> dict[str, Any]:
    return {
        "detector": {"id": "python-project", "state": state},
        "project": None, "applications": [], "runtimes": [], "modules": [],
        "evidence": [], "issues": [issue] if issue else [], "warnings": [warning] if warning else [],
    }


def detect_python_project(repo_path: str | Path) -> dict[str, Any]:
    manifest = Path(repo_path) / "pyproject.toml"
    if not manifest.is_file():
        return _empty("NOT_DETECTED")
    try:
        raw = manifest.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return _empty("INVALID", issue="python project manifest invalid: pyproject.toml is malformed")
    project = data.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str) or not project["name"].strip():
        return _empty("INVALID", issue="python project manifest invalid: pyproject.toml requires project.name")
    name = project["name"].strip()
    for key in ("version", "description"):
        if key in project and not isinstance(project[key], str):
            return _empty("INVALID", issue=f"python project manifest invalid: project.{key} must be a string")
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        return _empty("INVALID", issue="python project manifest invalid: project.dependencies must be a list")
    if not all(isinstance(item, str) for item in dependencies):
        return _empty("INVALID", issue="python project manifest invalid: project.dependencies values must be strings")
    constraint = project.get("requires-python")
    if constraint is not None and not isinstance(constraint, str):
        return _empty("INVALID", issue="python project manifest invalid: project.requires-python must be a string")
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict):
        return _empty("INVALID", issue="python project manifest invalid: project.scripts must be a mapping")
    if not all(isinstance(value, str) for value in scripts.values()):
        return _empty("INVALID", issue="python project manifest invalid: project.scripts values must be strings")
    evidence_id = "manifest:pyproject.toml"
    evidence = [{"id": evidence_id, "kind": "manifest", "locator": "pyproject.toml", "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}]
    applications = [
        {
            "id": f"python-console:{script}", "name": script, "kind": "application",
            "subtype": "python_console_script", "entrypoint": entrypoint,
            "runtime_id": "python", "evidence_ids": [evidence_id],
        }
        for script, entrypoint in sorted(scripts.items())
    ]
    warnings = [] if constraint is not None else ["python runtime coverage partial: project.requires-python is missing"]
    return {
        "detector": {"id": "python-project", "state": "DETECTED"},
        "project": {
            "id": f"python:{name}", "name": name, "version": project.get("version"),
            "description": project.get("description"), "evidence_ids": [evidence_id],
        },
        "applications": applications,
        "runtimes": [{
            "id": "python", "kind": "runtime", "constraint": constraint,
            "dependencies": sorted(dependencies), "evidence_ids": [evidence_id],
        }],
        "modules": [], "evidence": evidence, "issues": [], "warnings": warnings,
    }
