"""Build the normalized As-Is topology and attach repo-owned intent."""

from __future__ import annotations

from typing import Any

from moth.architecture_drift import build_architecture_drift
from moth.architecture_intent import load_architecture_intent

# 每个实体/关系的**来源**。这是 as_is 里最容易撒谎的一处:
# 合并之后声明来的和检测来的长得一模一样, 于是一张全靠人手写的图也会显示成"当前结构 OBSERVED"。
# 2026-08-17 实测: moth 自己 18 个实体里 15 个、13 条关系里 12 条只存在于 .moth/architecture.yaml;
# 把该文件移走后 as_is 只剩 3 实体 / 1 关系。所以三档必须分开记。
SOURCE_DETECTED = "DETECTED"    # 检测器从清单/代码里读出来的
SOURCE_DECLARED = "DECLARED"    # 只在声明文件里出现, 没有任何检测器独立看到
SOURCE_CONFIRMED = "CONFIRMED"  # 声明了, 而且检测器也独立看到了 —— 写下的被证实


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
        if existing is not None:
            without_source = {k: v for k, v in existing.items() if k != "source"}
            if without_source != item:
                issues.append(
                    f"architecture conflict: {collection} id has incompatible facts"
                )
                continue
            # 声明的东西检测器也独立看到了 —— 这是最强的一档: 写下的被证实了。
            merged[item["id"]] = {**item, "source": SOURCE_CONFIRMED}
            continue
        # 只在声明里出现, 没有任何检测器看到过。它可能是真的, 也可能是编的。
        merged[item["id"]] = {**item, "source": SOURCE_DECLARED}
    return [merged[item_id] for item_id in sorted(merged)]


def _provenance_counts(
    entities: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    flows: list[dict[str, Any]],
    state_machines: list[dict[str, Any]],
) -> dict[str, int]:
    """数清 as_is 里各来源各有多少。

    flows 与 state_machines **只可能**来自声明 —— 没有任何检测器产出这两样
    (2026-08-17 实测: run_detectors 的输出键里根本没有 flows/state_machines),
    所以它们无条件计入 declared, 不参与 detected 的判定。
    """
    counts = {"detected": 0, "declared": 0, "confirmed": 0}
    for item in [*entities, *relations]:
        source = item.get("source")
        if source == SOURCE_DETECTED:
            counts["detected"] += 1
        elif source == SOURCE_CONFIRMED:
            counts["confirmed"] += 1
        else:
            counts["declared"] += 1
    counts["declared"] += len(flows) + len(state_machines)
    return counts


def build_architecture_model(
    repo_path: Any,
    *,
    project: dict[str, Any] | None,
    applications: list[dict[str, Any]],
    runtimes: list[dict[str, Any]],
    modules: list[dict[str, Any]],
) -> dict[str, Any]:
    # 来源在**产出时**就标定, 不等到合并时才补 —— 没有声明文件的仓根本走不到合并那一步,
    # 靠合并补标会让一个纯检测出来的架构被算成"全是声明的"。
    entities = [
        {**item, "source": SOURCE_DETECTED}
        for item in _base_entities(project, applications, runtimes, modules)
    ]
    relations = [
        {**item, "source": SOURCE_DETECTED}
        for item in _base_relations(applications, {item["id"] for item in runtimes})
    ]
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
    # 有多少是真看到的, 有多少只是写下的 —— 这两个数必须能被界面读到,
    # 否则"当前结构"这张卡片会把一份手写 yaml 说成扫描结果。
    provenance = _provenance_counts(entities, relations, flows, state_machines)
    current = {
        # 只要有任何一个对象是检测器独立看到的, 才谈得上 OBSERVED;
        # 全部只来自声明时叫 DECLARED_ONLY —— 它不是"观察到的结构", 是"你告诉我的结构"。
        "state": (
            "NOT_OBSERVED"
            if not (entities or relations or flows or state_machines)
            else "OBSERVED"
            if provenance["detected"] or provenance["confirmed"]
            else "DECLARED_ONLY"
        ),
        "complete": current_complete,
        "provenance": provenance,
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
            "provenance": current["provenance"],
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
