"""Canonical project model composed from bounded detectors."""

from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from moth.architecture_model import build_architecture_model
from moth.detectors.common import load_platform_rules
from moth.detectors.registry import run_detectors


_MAX_PROFILE_EVIDENCE_BYTES = 1_048_576


def _repository_identity(repo_path: str | Path) -> tuple[dict[str, Any], dict[str, str]]:
    repo = Path(repo_path).resolve()
    name = repo.name or "repository"
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_") or "repository"
    observed = f"repository-directory-name:{name}"
    evidence_id = "repository:root"
    return (
        {
            "id": f"repository:{slug}",
            "name": name,
            "version": None,
            "description": None,
            "evidence_ids": [evidence_id],
        },
        {
            "id": evidence_id,
            "kind": "repository_boundary",
            "locator": ".",
            "sha256": "sha256:" + hashlib.sha256(observed.encode("utf-8")).hexdigest(),
        },
    )


def _merge_project(
    fragments: list[dict[str, Any]],
    issues: list[str],
) -> dict[str, Any] | None:
    candidates = [
        dict(fragment["project"])
        for fragment in fragments
        if fragment["project"] is not None
    ]
    if not candidates:
        return None
    selected = candidates[0]
    selected["evidence_ids"] = sorted(set(selected["evidence_ids"]))
    for candidate in candidates[1:]:
        candidate_evidence = sorted(set(candidate["evidence_ids"]))
        comparable_selected = {
            key: value for key, value in selected.items() if key != "evidence_ids"
        }
        comparable_candidate = {
            key: value for key, value in candidate.items() if key != "evidence_ids"
        }
        if comparable_selected != comparable_candidate:
            issues.append("project model conflict: project identity has incompatible facts")
            continue
        selected["evidence_ids"] = sorted(
            set(selected["evidence_ids"]) | set(candidate_evidence)
        )
    return selected


def _merge_evidence(
    fragments: list[dict[str, Any]],
    issues: list[str],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        for item in fragment["evidence"]:
            existing = merged.get(item["id"])
            if existing is None:
                merged[item["id"]] = item
            elif existing != item:
                issues.append("project model conflict: evidence id has incompatible facts")
    return [merged[item_id] for item_id in sorted(merged)]


def _merge_items(
    fragments: list[dict[str, Any]],
    field: str,
    issues: list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for fragment in fragments:
        for raw_item in fragment[field]:
            item = dict(raw_item)
            item["evidence_ids"] = sorted(set(item.get("evidence_ids", [])))
            existing = merged.get(item["id"])
            if existing is None:
                merged[item["id"]] = item
                continue
            if field == "runtimes":
                if existing["kind"] != item["kind"]:
                    issues.append("project model conflict: runtime id has incompatible kind")
                    continue
                existing["dependencies"] = sorted(
                    set(existing["dependencies"]) | set(item["dependencies"])
                )
                existing["evidence_ids"] = sorted(
                    set(existing["evidence_ids"]) | set(item["evidence_ids"])
                )
                if existing["constraint"] != item["constraint"]:
                    existing["constraint"] = None
                    warnings.append(
                        "project model coverage partial: runtime constraints conflict"
                    )
                continue
            comparable_existing = {
                key: value for key, value in existing.items() if key != "evidence_ids"
            }
            comparable_item = {
                key: value for key, value in item.items() if key != "evidence_ids"
            }
            if comparable_existing != comparable_item:
                issues.append(
                    f"project model conflict: {field[:-1]} id has incompatible facts"
                )
                continue
            existing["evidence_ids"] = sorted(
                set(existing["evidence_ids"]) | set(item["evidence_ids"])
            )
    return [merged[item_id] for item_id in sorted(merged)]


def _profile_evidence(
    repo_path: str | Path,
    evidence_paths: dict[str, Path] | None,
) -> tuple[list[dict[str, str]], list[str]]:
    repo = Path(repo_path).resolve()
    evidence: list[dict[str, str]] = []
    warnings: list[str] = []
    for label, configured_path in sorted((evidence_paths or {}).items()):
        path = Path(configured_path)
        try:
            resolved = path.resolve(strict=True)
            relative = resolved.relative_to(repo)
        except (OSError, ValueError):
            warnings.append(f"profile evidence unavailable: {label}")
            continue
        if path.is_symlink() or not resolved.is_file():
            continue
        try:
            with resolved.open("rb") as handle:
                raw = handle.read(_MAX_PROFILE_EVIDENCE_BYTES + 1)
        except OSError:
            warnings.append(f"profile evidence unreadable: {label}")
            continue
        if len(raw) > _MAX_PROFILE_EVIDENCE_BYTES:
            warnings.append(f"profile evidence exceeds size limit: {label}")
            continue
        slug = re.sub(r"[^a-z0-9_-]+", "-", str(label).lower()).strip("-_")
        evidence.append(
            {
                "id": f"profile:{slug or hashlib.sha256(str(label).encode()).hexdigest()[:12]}",
                "kind": (
                    "project_document"
                    if resolved.suffix.lower() in {".md", ".rst", ".txt"}
                    else "project_evidence"
                ),
                "locator": relative.as_posix(),
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        )
    return evidence, warnings


def build_project_model(
    repo_path: str | Path,
    *,
    evidence_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    detected = run_detectors(repo_path)
    issues = [issue for fragment in detected for issue in fragment["issues"]]
    warnings = [warning for fragment in detected for warning in fragment["warnings"]]
    if all(
        fragment["detector"]["state"] == "NOT_DETECTED" for fragment in detected
    ):
        warnings.append("project coverage unavailable: no supported manifest detected")
    applications = _merge_items(detected, "applications", issues, warnings)
    runtimes = _merge_items(detected, "runtimes", issues, warnings)
    modules = _merge_items(detected, "modules", issues, warnings)
    evidence = _merge_evidence(detected, issues)
    declared_evidence, evidence_warnings = _profile_evidence(repo_path, evidence_paths)
    evidence.extend(declared_evidence)
    warnings.extend(evidence_warnings)
    platform_modules = [item for item in modules if item.get("kind") == "platform"]
    config = load_platform_rules()["composition"]["mixed"]
    collapsed_subtypes = set(config.get("collapse_subtypes") or [])
    composition_keys = {
        (
            f"subtype:{item.get('subtype')}"
            if item.get("subtype") in collapsed_subtypes
            else f"id:{item['id']}"
        )
        for item in platform_modules
    }
    if len(composition_keys) > 1:
        mixed = {
            "id": config["id"],
            "kind": "composition",
            "name": config["name"],
            "subtype": config["subtype"],
            "evidence_ids": sorted(
                {
                    evidence_id
                    for item in platform_modules
                    for evidence_id in item["evidence_ids"]
                }
            ),
        }
        modules.append(mixed)
        modules.sort(key=lambda item: item["id"])
    project = _merge_project(detected, issues)
    if project is None:
        project, repository_evidence = _repository_identity(repo_path)
        evidence.append(repository_evidence)
    architecture = build_architecture_model(
        repo_path,
        project=project,
        applications=applications,
        runtimes=runtimes,
        modules=modules,
    )
    for item in architecture["evidence"]:
        existing = next(
            (known for known in evidence if known["id"] == item["id"]),
            None,
        )
        if existing is None:
            evidence.append(item)
        elif existing != item:
            issues.append(
                "project model conflict: architecture evidence id has incompatible facts"
            )
    evidence.sort(key=lambda item: item["id"])
    issues.extend(architecture["issues"])
    warnings.extend(architecture["warnings"])
    issues = list(dict.fromkeys(issues))
    warnings = list(dict.fromkeys(warnings))
    if issues:
        verdict = "FAIL"
    elif warnings:
        verdict = "WARN"
    else:
        verdict = "PASS"
    result = {
        "schema_version": "moth.project-model.v2",
        "verdict": verdict,
        "project": project,
        "applications": applications,
        "runtimes": runtimes,
        "modules": modules,
        "entities": architecture["entities"],
        "relations": architecture["relations"],
        "flows": architecture["flows"],
        "state_machines": architecture["state_machines"],
        "architecture": architecture["architecture"],
        "evidence": evidence,
        "coverage": {
            "detectors": [fragment["detector"] for fragment in detected],
            "issues": issues,
            "warnings": warnings,
        },
    }
    schema_errors = validate_project_model_schema(result)
    if schema_errors:
        result["verdict"] = "FAIL"
        result["coverage"]["issues"] = list(
            dict.fromkeys(
                [
                    *result["coverage"]["issues"],
                    *(f"project model schema: {error}" for error in schema_errors),
                ]
            )
        )
    return result


def validate_project_model_schema(payload: dict[str, Any]) -> list[str]:
    schema = json.loads(
        files("moth.schemas")
        .joinpath("moth.project-model.schema.json")
        .read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    return [
        (
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}"
        )
        for error in errors
    ]
