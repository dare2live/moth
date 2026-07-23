"""Evidence-driven Node/Web manifest detector."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from moth.detectors.common import (
    bounded_manifest_paths,
    detector_result,
    load_platform_rules,
    manifest_evidence,
    read_manifest,
)


def _mapping(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def detect_web_project(repo_path: str | Path) -> dict[str, Any]:
    rules = load_platform_rules()
    limits = rules["limits"]
    config = rules["web"]
    paths, truncated = bounded_manifest_paths(
        repo_path,
        config["package_globs"],
        limits=limits,
    )
    if not paths:
        return detector_result(
            config["detector_id"],
            "NOT_DETECTED",
            warnings=(
                ["web project coverage partial: bounded filesystem scan was incomplete"]
                if truncated
                else []
            ),
        )

    applications: list[dict[str, Any]] = []
    modules: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, str]] = []
    issues: list[str] = []
    warnings: list[str] = []
    dependencies: set[str] = set()
    constraints: set[str] = set()
    runtime_evidence: list[str] = []
    for relative in paths:
        raw, failure = read_manifest(
            repo_path,
            relative,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        if raw is None:
            issues.append(f"web manifest invalid: {relative.as_posix()} is {failure}")
            continue
        try:
            package = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            issues.append(f"web manifest invalid: {relative.as_posix()} is malformed")
            continue
        if not isinstance(package, dict):
            issues.append(f"web manifest invalid: {relative.as_posix()} must be an object")
            continue
        dependency_sections: list[dict[str, Any]] = []
        invalid_section = False
        for section_name in ("dependencies", "devDependencies"):
            section = package.get(section_name, {})
            section_mapping = _mapping(section)
            if section_mapping is None or not all(
                isinstance(name, str) and isinstance(version, str)
                for name, version in section_mapping.items()
            ):
                issues.append(
                    f"web manifest invalid: {relative.as_posix()} {section_name} must map strings to strings"
                )
                invalid_section = True
                break
            dependency_sections.append(section_mapping)
        if invalid_section:
            continue
        item = manifest_evidence(relative, raw)
        evidence.append(item)
        runtime_evidence.append(item["id"])
        package_dependencies = {
            name: version
            for section in dependency_sections
            for name, version in section.items()
        }
        dependencies.update(
            f"{name}@{version}" for name, version in package_dependencies.items()
        )
        engines = _mapping(package.get("engines", {}))
        if engines is None:
            issues.append(
                f"web manifest invalid: {relative.as_posix()} engines must be an object"
            )
            continue
        node_constraint = engines.get("node")
        if node_constraint is not None and not isinstance(node_constraint, str):
            issues.append(
                f"web manifest invalid: {relative.as_posix()} engines.node must be a string"
            )
            continue
        if node_constraint:
            constraints.add(node_constraint)

        matched = [
            framework
            for dependency, framework in config["framework_dependencies"].items()
            if dependency in package_dependencies
        ]
        if not matched:
            continue
        capabilities = {framework["capability"] for framework in matched}
        for capability in sorted(capabilities):
            capability_config = config["capabilities"][capability]
            module_id = f"platform:{capability}"
            module = modules.setdefault(
                module_id,
                {
                    "id": module_id,
                    "kind": "platform",
                    "name": capability_config["name"],
                    "subtype": capability_config["subtype"],
                    "evidence_ids": [],
                },
            )
            module["evidence_ids"].append(item["id"])
        for framework in matched:
            module_id = f"framework:{framework['id']}"
            module = modules.setdefault(
                module_id,
                {
                    "id": module_id,
                    "kind": "framework",
                    "name": framework["name"],
                    "subtype": "web",
                    "evidence_ids": [],
                },
            )
            module["evidence_ids"].append(item["id"])
        name = package.get("name")
        if not isinstance(name, str) or not name.strip():
            warnings.append(
                f"web application coverage partial: {relative.as_posix()} has no package name"
            )
            continue
        applications.append(
            {
                "id": f"web:{name.strip()}",
                "name": name.strip(),
                "kind": "application",
                "subtype": "web_application",
                "entrypoint": relative.as_posix(),
                "runtime_id": "nodejs",
                "evidence_ids": [item["id"]],
            }
        )

    if len(constraints) > 1:
        warnings.append("node runtime coverage partial: manifests declare conflicting constraints")
    if truncated:
        warnings.append("web project coverage partial: bounded filesystem scan was incomplete")
    state = "INVALID" if issues and not evidence else "DETECTED"
    return detector_result(
        config["detector_id"],
        state,
        applications=applications,
        runtimes=(
            [
                {
                    "id": "nodejs",
                    "kind": "runtime",
                    "constraint": next(iter(constraints)) if len(constraints) == 1 else None,
                    "dependencies": sorted(dependencies),
                    "evidence_ids": runtime_evidence,
                }
            ]
            if runtime_evidence
            else []
        ),
        modules=modules.values(),
        evidence=evidence,
        issues=issues,
        warnings=warnings,
    )
