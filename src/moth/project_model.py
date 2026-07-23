"""Canonical project model composed from bounded detectors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moth.detectors.common import load_platform_rules
from moth.detectors.registry import run_detectors


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


def build_project_model(repo_path: str | Path) -> dict[str, Any]:
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
    issues = list(dict.fromkeys(issues))
    warnings = list(dict.fromkeys(warnings))
    if issues:
        verdict = "FAIL"
    elif warnings:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return {
        "schema_version": "moth.project-model.v1",
        "verdict": verdict,
        "project": project,
        "applications": applications,
        "runtimes": runtimes,
        "modules": modules,
        "evidence": evidence,
        "coverage": {
            "detectors": [fragment["detector"] for fragment in detected],
            "issues": issues,
            "warnings": warnings,
        },
    }
