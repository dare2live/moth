"""Evidence-driven Apple/Xcode project detector."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from moth.detectors.common import (
    bounded_manifest_paths,
    detector_result,
    load_platform_rules,
    manifest_evidence,
    read_manifest,
)

_SWIFT_PACKAGE_NAME = re.compile(r"\bname\s*:\s*\"([A-Za-z0-9_.-]+)\"")
_SWIFT_TOOLS_VERSION = re.compile(r"swift-tools-version\s*:\s*([0-9.]+)")


def detect_apple_project(repo_path: str | Path) -> dict[str, Any]:
    rules = load_platform_rules()
    limits = rules["limits"]
    config = rules["apple"]
    paths, truncated = bounded_manifest_paths(
        repo_path,
        config["project_globs"],
        limits=limits,
    )
    package_paths, packages_truncated = bounded_manifest_paths(
        repo_path,
        config["swift_package_globs"],
        limits=limits,
    )
    if not paths and not package_paths:
        warnings = (
            ["apple project coverage partial: bounded filesystem scan was incomplete"]
            if truncated or packages_truncated
            else []
        )
        return detector_result(config["detector_id"], "NOT_DETECTED", warnings=warnings)

    applications: list[dict[str, Any]] = []
    modules: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, str]] = []
    issues: list[str] = []
    xcode_evidence_ids: list[str] = []
    swift_evidence_ids: list[str] = []
    swift_constraints: set[str] = set()

    def add_platforms(content: str, evidence_id: str) -> None:
        for platform_id, platform in config["platform_signals"].items():
            if any(signal in content for signal in platform["contains_any"]):
                module_id = f"platform:{platform_id}"
                existing = modules.get(module_id)
                if existing is None:
                    modules[module_id] = {
                        "id": module_id,
                        "kind": "platform",
                        "name": platform["name"],
                        "subtype": "apple",
                        "evidence_ids": [evidence_id],
                    }
                elif evidence_id not in existing["evidence_ids"]:
                    existing["evidence_ids"].append(evidence_id)

    for relative in paths:
        raw, failure = read_manifest(
            repo_path,
            relative,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        if raw is None:
            issues.append(f"apple manifest invalid: {relative.as_posix()} is {failure}")
            continue
        item = manifest_evidence(relative, raw)
        evidence.append(item)
        xcode_evidence_ids.append(item["id"])
        project_dir = relative.parent
        project_name = project_dir.name.removesuffix(".xcodeproj")
        applications.append(
            {
                "id": f"apple-xcode:{project_name}",
                "name": project_name,
                "kind": "application",
                "subtype": "apple_xcode_project",
                "entrypoint": project_dir.as_posix(),
                "runtime_id": "xcode",
                "evidence_ids": [item["id"]],
            }
        )
        content = raw.decode("utf-8", errors="replace").lower()
        add_platforms(content, item["id"])

    for relative in package_paths:
        raw, failure = read_manifest(
            repo_path,
            relative,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        if raw is None:
            issues.append(f"apple manifest invalid: {relative.as_posix()} is {failure}")
            continue
        item = manifest_evidence(relative, raw)
        evidence.append(item)
        swift_evidence_ids.append(item["id"])
        content = raw.decode("utf-8", errors="replace")
        add_platforms(content.lower(), item["id"])
        version = _SWIFT_TOOLS_VERSION.search(content)
        if version:
            swift_constraints.add(version.group(1))
        package_name = _SWIFT_PACKAGE_NAME.search(content)
        if package_name:
            name = package_name.group(1)
            applications.append(
                {
                    "id": f"apple-swift-package:{name}",
                    "name": name,
                    "kind": "application",
                    "subtype": "apple_swift_package",
                    "entrypoint": relative.as_posix(),
                    "runtime_id": "swift",
                    "evidence_ids": [item["id"]],
                }
            )

    state = "INVALID" if issues and not evidence else "DETECTED"
    warnings = (
        ["apple project coverage partial: bounded filesystem scan was incomplete"]
        if truncated or packages_truncated
        else []
    )
    runtimes: list[dict[str, Any]] = []
    if xcode_evidence_ids:
        runtimes.append(
            {
                "id": "xcode",
                "kind": "runtime",
                "constraint": None,
                "dependencies": [],
                "evidence_ids": xcode_evidence_ids,
            }
        )
    if swift_evidence_ids:
        if len(swift_constraints) > 1:
            warnings.append(
                "swift runtime coverage partial: manifests declare conflicting tools versions"
            )
        runtimes.append(
            {
                "id": "swift",
                "kind": "runtime",
                "constraint": (
                    next(iter(swift_constraints)) if len(swift_constraints) == 1 else None
                ),
                "dependencies": [],
                "evidence_ids": swift_evidence_ids,
            }
        )
    return detector_result(
        config["detector_id"],
        state,
        applications=applications,
        runtimes=runtimes,
        modules=modules.values(),
        evidence=evidence,
        issues=issues,
        warnings=warnings,
    )
