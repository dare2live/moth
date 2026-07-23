"""Detect explicit Git submodule composition without publishing remote URLs."""

from __future__ import annotations

import configparser
from pathlib import Path, PurePosixPath
from typing import Any

from moth.detectors.common import (
    detector_result,
    load_platform_rules,
    manifest_evidence,
    read_manifest,
)


def _safe_relative_locator(value: str) -> str | None:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def detect_multi_repository(repo_path: str | Path) -> dict[str, Any]:
    rules = load_platform_rules()
    limits = rules["limits"]
    config = rules["composition"]["multi_repository"]
    relative = Path(config["manifest"])
    if not (Path(repo_path) / relative).is_file():
        return detector_result(config["detector_id"], "NOT_DETECTED")
    raw, failure = read_manifest(
        repo_path,
        relative,
        max_bytes=int(limits["max_manifest_bytes"]),
    )
    if raw is None:
        return detector_result(
            config["detector_id"],
            "INVALID",
            issues=[f"multi-repository manifest invalid: .gitmodules is {failure}"],
        )
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw.decode("utf-8"))
    except (UnicodeError, configparser.Error):
        return detector_result(
            config["detector_id"],
            "INVALID",
            issues=["multi-repository manifest invalid: .gitmodules is malformed"],
        )
    evidence = manifest_evidence(relative, raw)
    repositories: list[dict[str, Any]] = []
    issues: list[str] = []
    for section in sorted(parser.sections()):
        if not section.startswith('submodule "') or not section.endswith('"'):
            continue
        name = section[len('submodule "') : -1]
        locator = _safe_relative_locator(parser.get(section, "path", fallback=""))
        if not name or locator is None:
            issues.append(
                "multi-repository manifest invalid: submodule requires a safe relative path"
            )
            continue
        repositories.append(
            {
                "id": f"repository:{name}",
                "kind": "repository",
                "name": name,
                "subtype": "git_submodule",
                "locator": locator,
                "evidence_ids": [evidence["id"]],
            }
        )
    if not repositories and not issues:
        issues.append("multi-repository manifest invalid: no submodules declared")
    modules = (
        [
            {
                "id": config["id"],
                "kind": "composition",
                "name": config["name"],
                "subtype": config["subtype"],
                "evidence_ids": [evidence["id"]],
            },
            *repositories,
        ]
        if repositories
        else []
    )
    return detector_result(
        config["detector_id"],
        "DETECTED" if repositories else "INVALID",
        modules=modules,
        evidence=[evidence],
        issues=issues,
    )
