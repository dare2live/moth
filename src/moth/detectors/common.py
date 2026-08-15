"""Bounded, path-safe helpers shared by filesystem-only detectors."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
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
        ("web", "python_framework_dependencies"),
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
    """Resolve configured manifest patterns without walking unrelated file trees."""

    root = Path(repo_path).resolve()
    max_depth = int(limits["max_depth"])
    max_entries = int(limits["max_entries"])
    excluded = set(limits["excluded_directories"])
    patterns = tuple(str(pattern) for pattern in globs)
    matches: dict[str, Path] = {}
    scanned = 0
    incomplete = False

    def consume() -> bool:
        nonlocal scanned, incomplete
        scanned += 1
        if scanned > max_entries:
            incomplete = True
            return False
        return True

    def directory_names(current: Path, pattern: str) -> list[str]:
        nonlocal incomplete
        names: list[str] = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if not consume():
                        break
                    if (
                        entry.name in excluded
                        or not fnmatch.fnmatch(entry.name, pattern)
                        or not entry.is_dir(follow_symlinks=False)
                    ):
                        continue
                    names.append(entry.name)
        except OSError:
            incomplete = True
        return sorted(names)

    def file_names(current: Path, pattern: str) -> list[str]:
        nonlocal incomplete
        names: list[str] = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if not consume():
                        break
                    if not fnmatch.fnmatch(entry.name, pattern):
                        continue
                    if entry.is_file(follow_symlinks=False):
                        names.append(entry.name)
        except OSError:
            incomplete = True
        return sorted(names)

    def walk_pattern(current: Path, parts: tuple[str, ...], relative: Path) -> None:
        nonlocal incomplete
        if incomplete or not parts:
            return
        part = parts[0]
        final = len(parts) == 1
        if part == "**":
            walk_pattern(current, parts[1:], relative)
            if len(relative.parts) >= max_depth:
                return
            for name in directory_names(current, "*"):
                walk_pattern(current / name, parts, relative / name)
            return
        has_magic = any(character in part for character in "*?[")
        if final:
            names = file_names(current, part) if has_magic else []
            if not has_magic:
                if not consume():
                    return
                candidate = current / part
                if not candidate.is_symlink() and candidate.is_file():
                    names = [part]
            for name in names:
                candidate = current / name
                if candidate.is_symlink() or not candidate.is_file():
                    continue
                locator = (relative / name).as_posix()
                matches[locator] = Path(locator)
            return

        if len(relative.parts) >= max_depth:
            incomplete = True
            return
        names = directory_names(current, part) if has_magic else [part]
        for name in names:
            if not has_magic and not consume():
                return
            directory = current / name
            if directory.is_symlink() or not directory.is_dir() or name in excluded:
                continue
            walk_pattern(directory, parts[1:], relative / name)

    for pattern in patterns:
        path = PurePosixPath(pattern)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            incomplete = True
            continue
        if len(path.parts) - 1 > max_depth:
            incomplete = True
            continue
        walk_pattern(root, tuple(path.parts), Path())
        if scanned > max_entries:
            break
    return [matches[key] for key in sorted(matches)], incomplete


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
