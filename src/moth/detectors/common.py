"""Bounded, path-safe helpers shared by filesystem-only detectors."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

import yaml
from jsonschema import Draft202012Validator


def load_platform_rules() -> dict[str, Any]:
    rules_path = Path(__file__).with_name("platform_rules.yaml")
    schema_path = Path(__file__).with_name("platform_rules.schema.json")
    data = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if errors:
        raise ValueError("platform detector rules are invalid")
    for section_name, dependency_field in (
        ("web", "framework_dependencies"),
        ("data_ai", "dependency_capabilities"),
    ):
        section = data[section_name]
        known_capabilities = set(section["capabilities"])
        referenced_capabilities = {
            item["capability"] for item in section[dependency_field].values()
        }
        if not referenced_capabilities <= known_capabilities:
            raise ValueError(
                f"{section_name} detector rules reference unknown capabilities"
            )
    if data["data_ai"]["notebook_capability"] not in data["data_ai"]["capabilities"]:
        raise ValueError("data_ai notebook capability is not configured")
    return data


def detector_result(
    detector_id: str,
    state: str,
    *,
    applications: Iterable[dict[str, Any]] = (),
    runtimes: Iterable[dict[str, Any]] = (),
    modules: Iterable[dict[str, Any]] = (),
    evidence: Iterable[dict[str, Any]] = (),
    issues: Iterable[str] = (),
    warnings: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "detector": {"id": detector_id, "state": state},
        "project": None,
        "applications": list(applications),
        "runtimes": list(runtimes),
        "modules": list(modules),
        "evidence": list(evidence),
        "issues": list(issues),
        "warnings": list(warnings),
    }


def bounded_manifest_paths(
    repo_path: str | Path,
    globs: Iterable[str],
    *,
    limits: dict[str, Any],
) -> tuple[list[Path], bool]:
    """Return matching files without following symlinks or scanning without bounds."""

    root = Path(repo_path)
    max_depth = int(limits["max_depth"])
    max_entries = int(limits["max_entries"])
    excluded = set(limits["excluded_directories"])
    patterns = tuple(globs)
    matches: list[Path] = []
    scanned = 0
    incomplete = False

    def onerror(_error: OSError) -> None:
        nonlocal incomplete
        incomplete = True

    for current, directories, files in os.walk(root, topdown=True, onerror=onerror, followlinks=False):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        directories[:] = sorted(
            name
            for name in directories
            if name not in excluded and not (current_path / name).is_symlink()
        )
        if depth >= max_depth:
            directories[:] = []
        for name in sorted(files):
            scanned += 1
            if scanned > max_entries:
                incomplete = True
                return matches, incomplete
            path = current_path / name
            if path.is_symlink():
                continue
            relative = path.relative_to(root)
            locator = relative.as_posix()
            if any(fnmatch.fnmatch(locator, pattern) for pattern in patterns):
                matches.append(relative)
    return matches, incomplete


def read_manifest(
    repo_path: str | Path,
    relative_path: Path,
    *,
    max_bytes: int,
) -> tuple[bytes | None, str | None]:
    path = Path(repo_path) / relative_path
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        return None, "unreadable"
    if len(raw) > max_bytes:
        return None, "oversized"
    return raw, None


def manifest_evidence(relative_path: Path, raw: bytes) -> dict[str, str]:
    locator = relative_path.as_posix()
    return {
        "id": f"manifest:{locator}",
        "kind": "manifest",
        "locator": locator,
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }
