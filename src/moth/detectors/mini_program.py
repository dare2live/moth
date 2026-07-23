"""Evidence-driven detector for paired mini-program manifests."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from moth.detectors.common import (
    bounded_manifest_paths,
    detector_result,
    load_platform_rules,
    manifest_evidence,
    read_manifest,
)


def _load_json(
    repo_path: str | Path,
    relative: Path,
    max_bytes: int,
) -> tuple[dict[str, Any] | None, dict[str, str] | None, str | None]:
    raw, failure = read_manifest(repo_path, relative, max_bytes=max_bytes)
    if raw is None:
        return None, None, failure
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        return None, None, "malformed"
    if not isinstance(value, dict):
        return None, None, "not an object"
    return value, manifest_evidence(relative, raw), None


def _safe_page(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def detect_mini_program(repo_path: str | Path) -> dict[str, Any]:
    rules = load_platform_rules()
    limits = rules["limits"]
    config = rules["mini_program"]
    project_globs = [
        pattern
        for platform in config["platforms"].values()
        for pattern in (
            platform["project_manifest"],
            f"*/{platform['project_manifest']}",
        )
    ]
    project_paths, truncated = bounded_manifest_paths(
        repo_path,
        project_globs,
        limits=limits,
    )
    if not project_paths:
        return detector_result(
            config["detector_id"],
            "NOT_DETECTED",
            warnings=(
                ["mini-program coverage partial: bounded filesystem scan was incomplete"]
                if truncated
                else []
            ),
        )

    applications: list[dict[str, Any]] = []
    runtimes: list[dict[str, Any]] = []
    modules: list[dict[str, Any]] = []
    evidence_by_id: dict[str, dict[str, str]] = {}
    issues: list[str] = []
    warnings: list[str] = []
    for project_relative in project_paths:
        platform_entry = next(
            (
                (platform_id, platform)
                for platform_id, platform in config["platforms"].items()
                if project_relative.name == platform["project_manifest"]
            ),
            None,
        )
        if platform_entry is None:
            continue
        platform_id, platform = platform_entry
        app_relative = project_relative.parent / platform["app_manifest"]
        if not (Path(repo_path) / app_relative).is_file():
            warnings.append(
                f"mini-program coverage partial: {project_relative.as_posix()} has no paired app manifest"
            )
            continue
        project_data, project_evidence, project_failure = _load_json(
            repo_path,
            project_relative,
            int(limits["max_manifest_bytes"]),
        )
        app_data, app_evidence, app_failure = _load_json(
            repo_path,
            app_relative,
            int(limits["max_manifest_bytes"]),
        )
        if project_data is None or project_evidence is None:
            issues.append(
                f"mini-program manifest invalid: {project_relative.as_posix()} is {project_failure}"
            )
            continue
        if app_data is None or app_evidence is None:
            issues.append(
                f"mini-program manifest invalid: {app_relative.as_posix()} is {app_failure}"
            )
            continue
        discriminator = platform.get("discriminator")
        if discriminator and project_data.get(discriminator["field"]) != discriminator["equals"]:
            continue
        for item in (app_evidence, project_evidence):
            evidence_by_id[item["id"]] = item
        evidence_ids = sorted((app_evidence["id"], project_evidence["id"]))
        platform_module_id = f"platform:{platform['runtime_id']}"
        modules.append(
            {
                "id": platform_module_id,
                "kind": "platform",
                "name": platform["name"],
                "subtype": "mini_program",
                "evidence_ids": evidence_ids,
            }
        )
        pages = app_data.get("pages", [])
        if not isinstance(pages, list):
            issues.append(
                f"mini-program manifest invalid: {app_relative.as_posix()} pages must be a list"
            )
            pages = []
        for page in sorted(filter(None, (_safe_page(value) for value in pages))):
            modules.append(
                {
                    "id": f"page:{platform_id}:{page}",
                    "kind": "page",
                    "name": page,
                    "subtype": platform_id,
                    "evidence_ids": [app_evidence["id"]],
                }
            )
        name = project_data.get(platform["name_field"])
        if isinstance(name, str) and name.strip():
            applications.append(
                {
                    "id": f"mini-program:{platform_id}:{name.strip()}",
                    "name": name.strip(),
                    "kind": "application",
                    "subtype": "mini_program_application",
                    "entrypoint": app_relative.as_posix(),
                    "runtime_id": platform["runtime_id"],
                    "evidence_ids": evidence_ids,
                }
            )
        else:
            warnings.append(
                f"mini-program application coverage partial: {project_relative.as_posix()} has no project name"
            )
        runtimes.append(
            {
                "id": platform["runtime_id"],
                "kind": "runtime",
                "constraint": None,
                "dependencies": [],
                "evidence_ids": evidence_ids,
            }
        )
    if truncated:
        warnings.append("mini-program coverage partial: bounded filesystem scan was incomplete")
    state = (
        "DETECTED"
        if evidence_by_id
        else ("INVALID" if issues else "NOT_DETECTED")
    )
    return detector_result(
        config["detector_id"],
        state,
        applications=applications,
        runtimes=runtimes,
        modules=modules,
        evidence=evidence_by_id.values(),
        issues=issues,
        warnings=warnings,
    )
