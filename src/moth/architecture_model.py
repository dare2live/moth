"""Build the normalized As-Is topology and attach repo-owned intent."""

from __future__ import annotations

from typing import Any

from moth.architecture_drift import build_architecture_drift
from moth.architecture_intent import load_architecture_intent


def _base_entities(
    project: dict[str, Any] | None,
    applications: list[dict[str, Any]],
    runtimes: list[dict[str, Any]],
    modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    if project:
        entities.append(
            {
                "id": project["id"],
                "kind": "project",
                "name": project["name"],
                "responsibility": project.get("description") or "Project boundary.",
                "evidence_ids": project["evidence_ids"],
            }
        )
    for item in applications:
        entities.append(
            {
                "id": item["id"],
                "kind": "application",
                "name": item["name"],
                "responsibility": f"Application entrypoint {item['entrypoint']}.",
                "locator": item["entrypoint"],
                "evidence_ids": item["evidence_ids"],
            }
        )
    for item in runtimes:
        entities.append(
            {
                "id": item["id"],
                "kind": "runtime",
                "name": item["id"],
                "responsibility": "Runtime and declared dependency boundary.",
                "evidence_ids": item["evidence_ids"],
            }
        )
    for item in modules:
        entities.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "name": item["name"],
                "responsibility": item.get("responsibility")
                or f"Declared {item['kind']} module.",
                **({"locator": item["locator"]} if item.get("locator") else {}),
                "evidence_ids": item["evidence_ids"],
            }
        )
    return sorted(entities, key=lambda item: item["id"])


def _base_relations(
    applications: list[dict[str, Any]],
    runtime_ids: set[str],
) -> list[dict[str, Any]]:
    relations = []
    for item in applications:
        runtime_id = item.get("runtime_id")
        if runtime_id not in runtime_ids:
            continue
        relations.append(
            {
                "id": f"uses-runtime:{item['id']}:{runtime_id}",
                "kind": "uses_runtime",
                "source_id": item["id"],
                "target_id": runtime_id,
                "label": "uses runtime",
                "evidence_ids": item["evidence_ids"],
            }
        )
    return sorted(relations, key=lambda item: item["id"])


def _merge_by_id(
    observed: list[dict[str, Any]],
    declared: list[dict[str, Any]],
    *,
    collection: str,
    issues: list[str],
) -> list[dict[str, Any]]:
    merged = {item["id"]: item for item in observed}
    for item in declared:
        existing = merged.get(item["id"])
        if existing is not None and existing != item:
            issues.append(
                f"architecture conflict: {collection} id has incompatible facts"
            )
            continue
        merged[item["id"]] = item
    return [merged[item_id] for item_id in sorted(merged)]


def build_architecture_model(
    repo_path: Any,
    *,
    project: dict[str, Any] | None,
    applications: list[dict[str, Any]],
    runtimes: list[dict[str, Any]],
    modules: list[dict[str, Any]],
) -> dict[str, Any]:
    entities = _base_entities(project, applications, runtimes, modules)
    relations = _base_relations(
        applications, {item["id"] for item in runtimes}
    )
    intent = load_architecture_intent(
        repo_path,
        base_entity_ids={item["id"] for item in entities},
    )
    issues = list(intent["issues"])
    warnings = list(intent["warnings"])
    current_complete = False
    flows: list[dict[str, Any]] = []
    state_machines: list[dict[str, Any]] = []
    if intent["state"] == "DECLARED":
        current_complete = bool(intent["current"]["complete"])
        entities = _merge_by_id(
            entities,
            intent["current"]["entities"],
            collection="entity",
            issues=issues,
        )
        relations = _merge_by_id(
            relations,
            intent["current"]["relations"],
            collection="relation",
            issues=issues,
        )
        flows = sorted(
            intent["current"]["flows"], key=lambda item: item["id"]
        )
        state_machines = sorted(
            intent["current"]["state_machines"], key=lambda item: item["id"]
        )
    current = {
        "state": "OBSERVED" if entities or relations else "NOT_OBSERVED",
        "complete": current_complete,
        "entities": entities,
        "relations": relations,
        "flows": flows,
        "state_machines": state_machines,
    }
    desired_payload = intent["desired"]
    has_desired = any(desired_payload[name] for name in (
        "entities",
        "relations",
        "flows",
        "state_machines",
    ))
    desired = {
        "state": (
            "DECLARED"
            if intent["state"] == "DECLARED" and has_desired
            else "INVALID"
            if intent["state"] == "INVALID"
            else "NOT_DECLARED"
        ),
        "complete": bool(desired_payload["complete"]),
        "entities": sorted(
            desired_payload["entities"], key=lambda item: item["id"]
        ),
        "relations": sorted(
            desired_payload["relations"], key=lambda item: item["id"]
        ),
        "flows": sorted(
            desired_payload["flows"], key=lambda item: item["id"]
        ),
        "state_machines": sorted(
            desired_payload["state_machines"], key=lambda item: item["id"]
        ),
        "evidence_ids": sorted(
            {
                evidence_id
                for name in ("entities", "relations", "flows", "state_machines")
                for item in desired_payload[name]
                for evidence_id in item["evidence_ids"]
            }
        ),
    }
    drift = (
        build_architecture_drift(current=current, desired=desired)
        if desired["state"] == "DECLARED"
        else build_architecture_drift(
            current=current,
            desired={
                "entities": [],
                "relations": [],
                "flows": [],
                "state_machines": [],
            },
        )
    )
    architecture = {
        "schema_version": "moth.architecture-model.v1",
        "declaration_state": "INVALID" if issues else intent["state"],
        "current": {
            "state": current["state"],
            "complete": current["complete"],
            "entity_ids": [item["id"] for item in entities],
            "relation_ids": [item["id"] for item in relations],
            "flow_ids": [item["id"] for item in flows],
            "state_machine_ids": [item["id"] for item in state_machines],
            "evidence_ids": sorted(
                {
                    evidence_id
                    for name in ("entities", "relations", "flows", "state_machines")
                    for item in current[name]
                    for evidence_id in item["evidence_ids"]
                }
            ),
        },
        "desired": desired,
        "drift": drift,
        "issues": list(dict.fromkeys(issues)),
        "warnings": list(dict.fromkeys(warnings)),
    }
    return {
        "entities": entities,
        "relations": relations,
        "flows": flows,
        "state_machines": state_machines,
        "architecture": architecture,
        "evidence": intent["evidence"],
        "issues": architecture["issues"],
        "warnings": architecture["warnings"],
    }
