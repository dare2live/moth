"""Build the normalized As-Is topology and attach repo-owned intent."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from moth.architecture_drift import build_architecture_drift
from moth.architecture_intent import load_architecture_intent, load_architecture_policy
from moth.checks.import_graph import (
    build_import_graph,
    infer_import_roots,
    load_import_graph_policy,
)

# 每个实体/关系的**来源**。这是 as_is 里最容易撒谎的一处:
# 合并之后声明来的和检测来的长得一模一样, 于是一张全靠人手写的图也会显示成"当前结构 OBSERVED"。
# 2026-08-17 实测: moth 自己 18 个实体里 15 个、13 条关系里 12 条只存在于 .moth/architecture.yaml;
# 把该文件移走后 as_is 只剩 3 实体 / 1 关系。所以三档必须分开记。
SOURCE_DETECTED = "DETECTED"    # 检测器从清单/代码里读出来的
SOURCE_DECLARED = "DECLARED"    # 只在声明文件里出现, 没有任何检测器独立看到
SOURCE_CONFIRMED = "CONFIRMED"  # 声明了, 而且检测器也独立看到了 —— 写下的被证实

# Phase 2: 声明的关系(s->t)对着共享 import 图的三档判定结果。
VERIFICATION_CONFIRMED = "CONFIRMED_BY_IMPORT"
VERIFICATION_NOT_OBSERVED = "NOT_OBSERVED"
VERIFICATION_NOT_VERIFIABLE = "NOT_VERIFIABLE"

_ENTRYPOINT_RE = re.compile(
    r"^[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*:[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*$"
)


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


def _module_for_relative_path(path_no_suffix: str, roots: list[str]) -> str | None:
    """把一个不带 `.py` 后缀的仓库相对路径, 按 import_graph 的 roots 转成模块名。

    与 checks/import_graph._module_name_for_root 同一条规则(去掉最长匹配的 root
    前缀, "/" 转 ".", 末尾 __init__ 丢弃), 但操作的是字符串而不是真实存在的 Path ——
    这样测试可以给一份纯手写的 import_graph 而不必真的建一棵源码树。
    """

    best_prefix_len = -1
    best_rel: str | None = None
    for raw_root in roots:
        root_norm = str(raw_root).strip("/")
        prefix = "" if root_norm in ("", ".") else root_norm + "/"
        if prefix:
            if path_no_suffix == root_norm:
                rel = ""
            elif path_no_suffix.startswith(prefix):
                rel = path_no_suffix[len(prefix):]
            else:
                continue
        else:
            rel = path_no_suffix
        if len(prefix) > best_prefix_len:
            best_prefix_len = len(prefix)
            best_rel = rel
    if not best_rel:
        return None
    parts = best_rel.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return None
    return ".".join(parts)


def _module_for_entrypoint(value: str) -> str | None:
    """`module.path:function` (pyproject `project.scripts` 的既有写法) -> module 部分。"""

    if not _ENTRYPOINT_RE.match(value):
        return None
    module, _, _func = value.partition(":")
    return module


def _classify_entity_import_scope(
    entity: dict[str, Any],
    roots: list[str],
    known_modules: set[str],
    *,
    graph_ready: bool,
) -> tuple[str | None, str | None, str | None]:
    """单个实体的 locator/entrypoint -> import 图模块名映射 (M1)。

    返回 (import_module, import_scope, issue)。`import_scope="outside"` 是纯语法判断
    (locator 后缀不是 .py 也不是 module:func 形状), 不依赖 import 图是否配置好, 因为
    "这是不是 Python 代码" 这件事跟 roots 有没有配对无关。但 .py/entrypoint 分支要
    去查 known_modules 才能判断是否真映射得上, 没有可用的图时(graph_ready=False)
    宁可什么都不说, 也不要在缺图的情况下瞎猜/瞎报 issue。
    """

    locator = entity.get("locator")
    if not locator or not isinstance(locator, str):
        return None, None, None
    if locator.endswith(".py"):
        if not graph_ready:
            return None, None, None
        module = _module_for_relative_path(locator[: -len(".py")], roots)
        if module is None or module not in known_modules:
            return None, None, (
                f"architecture entity {entity['id']}: locator does not map to any module "
                f"the import graph knows about (roots={roots!r}): {locator}"
            )
        return module, None, None
    entrypoint_module = _module_for_entrypoint(locator)
    if entrypoint_module is not None:
        if not graph_ready:
            return None, None, None
        if entrypoint_module not in known_modules:
            return None, None, (
                f"architecture entity {entity['id']}: entrypoint does not map to any module "
                f"the import graph knows about (roots={roots!r}): {locator}"
            )
        return entrypoint_module, None, None
    # 非 .py, 非 module:func 的 locator (.html / .command / .yaml / ...) —— 这个实体
    # 不在 import 图的管辖范围内, 这是事实判断, 不是"没配好图"的借口。
    return None, "outside", None


def _build_elevated_edges(
    edges: list[dict[str, Any]],
    module_to_entity: dict[str, str],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """M2: 把模块图的直接边提升成组件(声明实体)边, 只提升直接边, 不做传递闭包。"""

    elevated: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for edge in edges:
        source_entity = module_to_entity.get(edge.get("source"))
        target_entity = module_to_entity.get(edge.get("target"))
        if not source_entity or not target_entity or source_entity == target_entity:
            continue
        bucket = elevated.setdefault((source_entity, target_entity), [])
        for location in edge.get("locations") or []:
            loc = {"path": location["path"], "line": location["line"]}
            if loc not in bucket:
                bucket.append(loc)
    for bucket in elevated.values():
        bucket.sort(key=lambda item: (item["path"], item["line"]))
    return elevated


def _relation_kind_policy() -> tuple[set[str], set[str]]:
    """M4: refutable/confirmable relation kinds 从 architecture_policy.yaml 读, 不 hardcode。"""

    vocabulary = load_architecture_policy()["vocabulary"]
    refutable = set(vocabulary.get("refutable_relation_kinds") or [])
    confirmable = set(vocabulary.get("confirmable_relation_kinds") or [])
    return refutable, confirmable


def _dynamic_import_marker(repo: Path, locator: Any) -> str | None:
    """NOT_OBSERVED 时, 若源模块含 importlib/__import__/subprocess 等动态导入标记,
    要在 reason 里说明 —— 静态 AST 图天然看不到这些, 不说明就是把"看不见"说成"没有"。
    """

    if not locator or not isinstance(locator, str) or not locator.endswith(".py"):
        return None
    try:
        markers = load_import_graph_policy()["dynamic_import_markers"]
    except (OSError, ValueError):
        return None
    target = repo / locator
    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for marker in markers:
        if marker in text:
            return str(marker)
    return None


def _self_derive_import_graph(repo_path: Any) -> dict[str, Any]:
    """production 调用路径的兜底: 调用方(project_model.build_project_model)已经算过
    一份 import_graph 但没有把它传下来 —— 这里独立地再推一次 roots/图, 只用
    repo_path 能拿到的信息(pyproject.toml), 不依赖 profile 里的 import_cycles 配置
    (那份配置到不了这一层)。测试可以绕过这条路径, 直接把 import_graph 传进来。
    """

    inferred = infer_import_roots(repo_path, import_cycles_config=None)
    roots = list(inferred["roots"]) if inferred["state"] == "OK" else []
    return build_import_graph(repo_path, roots=roots, excludes=[])


def _verify_relations_against_import_graph(
    *,
    repo: Path,
    relations: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    declared_relation_ids: set[str],
    import_graph: dict[str, Any],
    issues: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """M3 三档合并 + M2 提升到组件层的落地。

    返回 (更新后的 relations, 新产出的 DETECTED "imports" 关系)。只给**声明的**关系
    (id 在 declared_relation_ids 里)挂 verification —— 纯检测出来的关系(uses_runtime
    之类)不存在"声明是否被证实"这回事。
    """

    if import_graph.get("state") != "OK":
        # M5: 没有图不等于关系不存在, 一律 NOT_VERIFIABLE, 绝不能产出 NOT_OBSERVED,
        # 也不能借这个理由让 declaration_state 变 INVALID(所以这里不追加 issues)。
        updated = []
        for relation in relations:
            relation = dict(relation)
            if relation["id"] in declared_relation_ids:
                relation["verification"] = {
                    "status": VERIFICATION_NOT_VERIFIABLE,
                    "reason": "import_graph_not_configured",
                }
            updated.append(relation)
        return updated, []

    roots = list(import_graph.get("roots") or [])
    known_modules = set(import_graph.get("modules") or [])
    refutable_kinds, confirmable_kinds = _relation_kind_policy()

    entity_info: dict[str, dict[str, str | None]] = {}
    tagged_entities: list[dict[str, Any]] = []
    for entity in entities:
        module, scope, issue = _classify_entity_import_scope(
            entity, roots, known_modules, graph_ready=True
        )
        if issue:
            issues.append(issue)
        entity_info[entity["id"]] = {"module": module, "scope": scope}
        tagged = dict(entity)
        if module:
            tagged["import_module"] = module
        if scope:
            tagged["import_scope"] = scope
        tagged_entities.append(tagged)
    entities[:] = tagged_entities
    entities_by_id = {item["id"]: item for item in entities}

    module_to_entity = {
        info["module"]: entity_id
        for entity_id, info in entity_info.items()
        if info["module"]
    }
    elevated = _build_elevated_edges(import_graph.get("edges") or [], module_to_entity)
    existing_pairs = {(item["source_id"], item["target_id"]) for item in relations}

    updated: list[dict[str, Any]] = []
    for relation in relations:
        relation = dict(relation)
        if relation["id"] in declared_relation_ids:
            pair = (relation["source_id"], relation["target_id"])
            locations = elevated.get(pair)
            if locations is not None and relation["kind"] in confirmable_kinds:
                relation["source"] = SOURCE_CONFIRMED
                relation["verification"] = {
                    "status": VERIFICATION_CONFIRMED,
                    "reason": "confirmed_by_import_edge",
                    "locations": [dict(item) for item in locations],
                }
            else:
                s_info = entity_info.get(relation["source_id"], {"module": None, "scope": None})
                t_info = entity_info.get(relation["target_id"], {"module": None, "scope": None})
                if not s_info["module"] or not t_info["module"]:
                    reason = (
                        "cross_language"
                        if s_info["scope"] == "outside" or t_info["scope"] == "outside"
                        else "non_python_locator"
                    )
                    relation["verification"] = {
                        "status": VERIFICATION_NOT_VERIFIABLE,
                        "reason": reason,
                    }
                elif relation["kind"] not in refutable_kinds:
                    relation["verification"] = {
                        "status": VERIFICATION_NOT_VERIFIABLE,
                        "reason": "kind_outside_import_scope",
                    }
                else:
                    marker = _dynamic_import_marker(
                        repo, entities_by_id.get(relation["source_id"], {}).get("locator")
                    )
                    reason = "not_observed_in_static_imports"
                    if marker:
                        reason += f"; dynamic import marker present in source module: {marker}"
                    relation["verification"] = {
                        "status": VERIFICATION_NOT_OBSERVED,
                        "reason": reason,
                    }
        updated.append(relation)

    new_relations: list[dict[str, Any]] = []
    for (source_id, target_id), locations in elevated.items():
        if (source_id, target_id) in existing_pairs:
            continue
        target_module = entity_info.get(target_id, {}).get("module") or target_id
        new_relations.append(
            {
                "id": f"imports:{source_id}:{target_id}",
                "kind": "imports",
                "source_id": source_id,
                "target_id": target_id,
                "label": f"imports {target_module}",
                "evidence_ids": [],
                "source": SOURCE_DETECTED,
                "verification": {
                    "status": VERIFICATION_CONFIRMED,
                    "reason": "confirmed_by_import_edge",
                    "locations": [dict(item) for item in locations],
                },
            }
        )
    new_relations.sort(key=lambda item: item["id"])

    return updated, new_relations


def build_architecture_model(
    repo_path: Any,
    *,
    project: dict[str, Any] | None,
    applications: list[dict[str, Any]],
    runtimes: list[dict[str, Any]],
    modules: list[dict[str, Any]],
    import_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo = Path(repo_path).resolve()
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
    # Phase 2: 把共享 import 图提升到声明的组件层, 给每条**声明的**关系一个三档判定
    # (CONFIRMED_BY_IMPORT / NOT_OBSERVED / NOT_VERIFIABLE), 并把提升边里声明没提过的
    # 新关系一并产出。import_graph 未显式传入时(生产路径就是这样 —— project_model.py
    # 调这个函数时不带 import_graph, 见模块顶部导入处的说明)在这里独立地自己推一份。
    declared_relation_ids = (
        {item["id"] for item in intent["current"]["relations"]}
        if intent["state"] == "DECLARED"
        else set()
    )
    effective_import_graph = (
        import_graph if import_graph is not None else _self_derive_import_graph(repo_path)
    )
    relations, new_import_relations = _verify_relations_against_import_graph(
        repo=repo,
        relations=relations,
        entities=entities,
        declared_relation_ids=declared_relation_ids,
        import_graph=effective_import_graph,
        issues=issues,
    )
    relations = sorted(relations + new_import_relations, key=lambda item: item["id"])
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
