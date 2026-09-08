"""Build a renderer-neutral visual document from one portable inspection."""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

from moth.visual_policy import load_visual_policy


_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
_BUCKET_RANK = {"now": 0, "watch": 1, "defer": 2}

# P1/P2: architecture_model 挂在实体上的影响面字段(模块级 fan-in/fan-out) ——
# 与 import_module/import_scope 同一条透传规矩: 有就带进 attributes, 缺就不写,
# 不补 0/空列表。列在一处, 两处重建(unified entities 初次构建 + applications/
# modules 循环按同一个 id 重建覆盖)都要用同一份 key 集合, 不能漏改一处。
_IMPACT_ATTRIBUTE_KEYS = (
    "fan_in",
    "fan_out",
    "imported_by",
    "imports_direct",
    "imported_by_omitted",
    "imports_direct_omitted",
)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    return [str(item) for item in _list(value)]


def _provenance_of(
    project_model: dict[str, Any],
    entity_ids: list[str],
    relation_ids: list[str],
) -> dict[str, int]:
    """数清给定的这批 id 里, 各有多少是扫描出来的、多少只是被声明过。

    口径必须与页面上展示的那批 id 一致 —— 否则"20 个对象"配上一个按全量算的
    "共 35 项"拆分, 读的人只会以为自己看错了。

    project_model 里查不到的 id(例如 flow / state_machine —— 它们不在 entities 表里,
    而且没有任何检测器产出这两样)一律算 declared。
    """
    source_by_id: dict[str, str] = {}
    for collection in ("entities", "relations"):
        for item in _list(project_model.get(collection)):
            row = _mapping(item)
            if row.get("id"):
                source_by_id[str(row["id"])] = str(row.get("source") or "DECLARED")
    counts = {"detected": 0, "declared": 0, "confirmed": 0}
    for item_id in [*entity_ids, *relation_ids]:
        source = source_by_id.get(item_id, "DECLARED")
        if source == "DETECTED":
            counts["detected"] += 1
        elif source == "CONFIRMED":
            counts["confirmed"] += 1
        else:
            counts["declared"] += 1
    return counts


def _digest(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _stable_id(prefix: str, value: str) -> str:
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{suffix}"


def _evidence(
    evidence_id: str,
    *,
    kind: str,
    locator: str,
    summary: str,
    digest: str | None = None,
) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "kind": kind,
        "locator": locator,
        "summary": summary,
        "digest": digest,
    }


def _entity(
    entity_id: str,
    *,
    kind: str,
    name: str,
    summary: str,
    status: str,
    evidence_ids: list[str],
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": entity_id,
        "kind": kind,
        "name": name,
        "summary": summary,
        "status": status,
        "evidence_ids": sorted(set(evidence_ids)),
        "attributes": attributes or {},
    }


def _relation(
    relation_id: str,
    *,
    kind: str,
    source_id: str,
    target_id: str,
    label: str,
    evidence_ids: list[str],
    order: int | None = None,
    source: str | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "id": relation_id,
        "kind": kind,
        "source_id": source_id,
        "target_id": target_id,
        "label": label,
        "evidence_ids": sorted(set(evidence_ids)),
    }
    # 只有**有序**的关系(目前只有 flow_step)带 order。
    # 为什么不让视图自己数: 文档输出前 relations 按 id 字典序重排(见文末 dict(sorted(...))),
    # 而 id 里的序号没补零 —— 10 步的流程会排成 1, 10, 2, 3。顺序是模型知道的事实,
    # 让视图从 id 字符串里反推等于把同一件事算第二遍, 且算错。
    if order is not None:
        row["order"] = int(order)
    # source 只由调用方在**能查到**上游 source 时传入(见 _build_entities 里的
    # relation_sources 查表)—— 查不到就不设这个键, 不默认成 DECLARED。默认成 DECLARED
    # 会把"不知道"渲染成"只来自声明", 比不显示更具误导性。
    if source is not None:
        row["source"] = source
    # N2: verification 同样只在**能查到**上游 verification 时才设置 —— 半成品的
    # verification(缺 status 或 reason)比没有更误导, 见 _relation_verification()。
    if verification is not None:
        row["verification"] = verification
    return row


def _relation_verification(raw: Any, limit: int) -> dict[str, Any] | None:
    """把 project_model 关系上的 verification 透传成 visual relation 的可选字段。

    locations 是**代码坐标**, 不是 evidence 注册表条目 —— 两者不是一回事, 不能塞进
    evidence 里冒充证据。按 limit 只保留前 N 条(与本文件既有的截断风格一致: 图上
    predicates/关系引用截断时都留一个 omitted 计数), 超出的数量必须如实写成
    omitted_locations, 不能悄悄丢掉。
    """

    verification = _mapping(raw)
    status = str(verification.get("status") or "").strip()
    reason = str(verification.get("reason") or "").strip()
    if not status or not reason:
        return None
    result: dict[str, Any] = {"status": status, "reason": reason}
    locations: list[dict[str, Any]] = []
    for item in _list(verification.get("locations")):
        entry = _mapping(item)
        path = str(entry.get("path") or "").strip()
        line = entry.get("line")
        if not path or not isinstance(line, int):
            continue
        locations.append({"path": path, "line": line})
    if locations:
        kept = locations[: max(0, limit)]
        omitted = len(locations) - len(kept)
        result["locations"] = kept
        if omitted:
            result["omitted_locations"] = omitted
    return result


# finding 的**归属**: 这条说的是谁的问题。
#   project — 用户项目本身的状况(架构漂移 / 复杂度热点 / 未提交改动 / 识别覆盖不足)
#   tooling — Moth 自己的前置条件没就绪(索引没建 / baseline 缺失 / 上下文未验证)
# 为什么必须分开: 控制台服务的是"学架构、看问题"的人, 而 tooling 类说的是本工具的内务,
# 他既看不懂也不该关心。混在同一列表里, 工具内务会挤掉真正的项目问题 ——
# 用户实测反馈"看了没啥实际用途", 页面上五条里有三条是 codegraph/baseline 未就绪。
# severity/action_bucket 回答的是"多急", 这里回答的是"谁的事", 两个维度不可互相替代。
ORIGIN_PROJECT = "project"
ORIGIN_TOOLING = "tooling"


def _finding(
    finding_id: str,
    *,
    title: str,
    severity: str,
    confidence: str,
    action_bucket: str,
    origin: str,
    why: str,
    impact: list[str],
    safest_step: str,
    avoid: list[str],
    evidence_ids: list[str],
    layer_ids: list[str],
    viewpoint_ids: list[str],
    location: str = "Moth inspection",
    responsibility: str = "验证门禁与证据覆盖",
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "title": title,
        "location": location,
        "responsibility": responsibility,
        "why": why,
        "impact": impact,
        "safest_step": safest_step,
        "avoid": avoid,
        "severity": severity,
        "confidence": confidence,
        "action_bucket": action_bucket,
        "origin": origin,
        "evidence_ids": sorted(set(evidence_ids)),
        "layer_ids": sorted(set(layer_ids)),
        "viewpoint_ids": sorted(set(viewpoint_ids)),
    }


def _add_inspection_evidence(
    store: dict[str, dict[str, Any]],
    evidence_id: str,
    summary: str,
) -> str:
    store[evidence_id] = _evidence(
        evidence_id,
        kind="inspection_observation",
        locator="moth.inspect",
        summary=summary,
        digest=_digest(summary),
    )
    return evidence_id


def _copy_project_evidence(
    project_model: dict[str, Any],
    store: dict[str, dict[str, Any]],
) -> None:
    for raw in _list(project_model.get("evidence")):
        item = _mapping(raw)
        evidence_id = str(item.get("id") or "").strip()
        if not evidence_id:
            continue
        store[evidence_id] = _evidence(
            evidence_id,
            kind=str(item.get("kind") or "evidence"),
            locator=str(item.get("locator") or evidence_id),
            summary=f"{item.get('kind') or 'evidence'}: {item.get('locator') or evidence_id}",
            digest=str(item.get("sha256")) if item.get("sha256") else None,
        )


def _copy_change_evidence(
    inspection: dict[str, Any],
    store: dict[str, dict[str, Any]],
) -> None:
    change_safety = _mapping(inspection.get("change_safety"))
    for evidence_id, raw in _mapping(change_safety.get("evidence")).items():
        item = _mapping(raw)
        identifier = str(item.get("id") or evidence_id).strip()
        if not identifier:
            continue
        locator = str(item.get("locator") or "moth.inspect")
        summary = str(item.get("summary") or "change safety observation")
        store[identifier] = _evidence(
            identifier,
            kind=str(item.get("observation_kind") or "change_observation"),
            locator=locator,
            summary=summary,
            digest=_digest(item),
        )


def _build_entities(
    *,
    inspection: dict[str, Any],
    snapshot: dict[str, Any],
    project_model: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
    verification_locations_limit: int,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[str]],
]:
    entities: dict[str, dict[str, Any]] = {}
    relations: dict[str, dict[str, Any]] = {}
    # 同 id 关系的 source, 只收合法枚举值 —— 查不到 / 值不合法就不进表, 调用方
    # 拿 .get(...) 会得到 None, _relation() 因此不写这个键, 而不是被喂进一个假的
    # DECLARED。口径与 _provenance_of 一致但用途不同: 那边是计数, 这里是透传。
    relation_sources: dict[str, str] = {}
    for raw in _list(project_model.get("relations")):
        item = _mapping(raw)
        source_relation_id = str(item.get("id") or "").strip()
        source_value = item.get("source")
        if source_relation_id and source_value in {"DETECTED", "CONFIRMED", "DECLARED"}:
            relation_sources[source_relation_id] = str(source_value)
    groups: dict[str, list[str]] = {
        "project": [],
        "applications": [],
        "runtimes": [],
        "modules": [],
        "technologies": [],
        "flows": [],
        "documents": [],
        "code": [],
        "tools": [],
    }
    unified_entities = _list(project_model.get("entities"))
    for raw in unified_entities:
        item = _mapping(raw)
        entity_id = str(item.get("id") or "").strip()
        if not entity_id:
            continue
        kind = str(item.get("kind") or "entity")
        # N3: import_module/import_scope 是 import 图验证时(architecture_model.
        # _classify_entity_import_scope)挂在实体上的坐标信息 —— 有就带进 attributes,
        # openEntity 已经泛化渲染它, 不必新写一条 UI。缺失就不写这个键, 不编空字符串。
        # P1: fan_in/fan_out/imported_by/imports_direct(+*_omitted 计数)同一条规矩,
        # 用 `key in item` 而不是 `item.get(key)` 判断存在 —— fan_in=0 是一个真实的
        # 计数(某模块没有任何直接导入者), 不能被当成"没有这个字段"漏掉。
        attributes: dict[str, Any] = {}
        if item.get("locator"):
            attributes["locator"] = item.get("locator")
        if item.get("import_module"):
            attributes["import_module"] = item.get("import_module")
        if item.get("import_scope"):
            attributes["import_scope"] = item.get("import_scope")
        for key in _IMPACT_ATTRIBUTE_KEYS:
            if key in item:
                attributes[key] = item[key]
        entities[entity_id] = _entity(
            entity_id,
            kind=kind,
            name=str(item.get("name") or entity_id),
            summary=str(item.get("responsibility") or "职责尚未声明。"),
            status="OBSERVED",
            evidence_ids=_strings(item.get("evidence_ids")),
            attributes=attributes,
        )
        if kind == "project":
            groups["project"].append(entity_id)
        elif kind == "runtime":
            groups["runtimes"].append(entity_id)
        elif kind == "application":
            groups["applications"].append(entity_id)
        elif kind == "technology":
            groups["technologies"].append(entity_id)
        else:
            groups["modules"].append(entity_id)
    # N3: applications/modules 下面还会按**同一个 id**重建实体(它们来自 project_model
    # 的另一份列表, 不是 unified_entities), 那两处重建会整个覆盖掉上面刚设好的
    # attributes —— 查 moth 自己的真实数据实测: python-console:moth 在 unified
    # entities 里带 import_module=moth.cli, 但 applications 循环用只有 entrypoint
    # 的 attributes 把它整个换掉, import_module 就丢了。这张表按 id 记一份
    # import_module/import_scope(+P1 的影响面字段), 供后面两处重建时合并回去,
    # 不重新计算一次。
    import_scope_by_id: dict[str, dict[str, Any]] = {}
    for raw in unified_entities:
        item = _mapping(raw)
        entity_id = str(item.get("id") or "").strip()
        if not entity_id:
            continue
        scoped: dict[str, Any] = {}
        if item.get("import_module"):
            scoped["import_module"] = item.get("import_module")
        if item.get("import_scope"):
            scoped["import_scope"] = item.get("import_scope")
        for key in _IMPACT_ATTRIBUTE_KEYS:
            if key in item:
                scoped[key] = item[key]
        if scoped:
            import_scope_by_id[entity_id] = scoped

    def _with_import_scope(entity_id: str, attributes: dict[str, Any]) -> dict[str, Any]:
        extra = import_scope_by_id.get(entity_id)
        return {**attributes, **extra} if extra else attributes

    project = _mapping(project_model.get("project"))
    project_id = str(project.get("id") or "project:unknown")
    if project:
        entities[project_id] = _entity(
            project_id,
            kind="project",
            name=str(project.get("name") or "未识别项目"),
            summary=str(project.get("description") or "暂无可验证的项目说明。"),
            status=str(project_model.get("verdict") or "UNKNOWN"),
            evidence_ids=_strings(project.get("evidence_ids")),
            attributes={"version": project.get("version")},
        )
        groups["project"].append(project_id)

    for raw in _list(project_model.get("evidence")):
        item = _mapping(raw)
        if item.get("kind") != "project_document":
            continue
        evidence_id = str(item.get("id") or "").strip()
        locator = str(item.get("locator") or "").strip()
        if not evidence_id or evidence_id not in evidence or not locator:
            continue
        document_id = f"document:{evidence_id}"
        entities[document_id] = _entity(
            document_id,
            kind="project_document",
            name=locator.rsplit("/", 1)[-1],
            summary=f"项目文档：{locator}",
            status="OBSERVED",
            evidence_ids=[evidence_id],
            attributes={"locator": locator},
        )
        groups["documents"].append(document_id)

    runtime_ids: set[str] = set()
    for raw in _list(project_model.get("runtimes")):
        runtime = _mapping(raw)
        runtime_id = str(runtime.get("id") or "").strip()
        if not runtime_id:
            continue
        runtime_ids.add(runtime_id)
        dependencies = _strings(runtime.get("dependencies"))
        entities[runtime_id] = _entity(
            runtime_id,
            kind=str(runtime.get("kind") or "runtime"),
            name=runtime_id,
            summary=(
                f"约束 {runtime.get('constraint') or '未声明'}，"
                f"已声明依赖 {len(dependencies)} 项。"
            ),
            status="OBSERVED",
            evidence_ids=_strings(runtime.get("evidence_ids")),
            attributes={
                "constraint": runtime.get("constraint"),
                "dependency_count": len(dependencies),
            },
        )
        groups["runtimes"].append(runtime_id)

    for raw in _list(project_model.get("applications")):
        application = _mapping(raw)
        application_id = str(application.get("id") or "").strip()
        if not application_id:
            continue
        evidence_ids = _strings(application.get("evidence_ids"))
        entities[application_id] = _entity(
            application_id,
            kind=str(application.get("subtype") or application.get("kind") or "application"),
            name=str(application.get("name") or application_id),
            summary=f"入口 {application.get('entrypoint') or '未识别'}。",
            status="OBSERVED",
            evidence_ids=evidence_ids,
            attributes=_with_import_scope(
                application_id, {"entrypoint": application.get("entrypoint")}
            ),
        )
        groups["applications"].append(application_id)
        runtime_id = str(application.get("runtime_id") or "")
        if runtime_id in runtime_ids:
            relation_id = f"uses-runtime:{application_id}:{runtime_id}"
            relations[relation_id] = _relation(
                relation_id,
                kind="uses_runtime",
                source_id=application_id,
                target_id=runtime_id,
                label="使用运行时",
                evidence_ids=evidence_ids,
                source=relation_sources.get(relation_id),
            )

    for raw in _list(project_model.get("modules")):
        module = _mapping(raw)
        module_id = str(module.get("id") or "").strip()
        if not module_id:
            continue
        entities[module_id] = _entity(
            module_id,
            kind=str(module.get("kind") or "module"),
            name=str(module.get("name") or module_id),
            summary=str(module.get("responsibility") or "模块职责尚未声明。"),
            status="OBSERVED",
            evidence_ids=_strings(module.get("evidence_ids")),
            attributes=_with_import_scope(module_id, {}),
        )
        if module.get("kind") == "technology":
            groups["technologies"].append(module_id)
        else:
            groups["modules"].append(module_id)

    for raw in _list(project_model.get("relations")):
        item = _mapping(raw)
        relation_id = str(item.get("id") or "").strip()
        source_id = str(item.get("source_id") or "").strip()
        target_id = str(item.get("target_id") or "").strip()
        if not relation_id or source_id not in entities or target_id not in entities:
            continue
        relations[relation_id] = _relation(
            relation_id,
            kind=str(item.get("kind") or "relates_to"),
            source_id=source_id,
            target_id=target_id,
            label=str(item.get("label") or item.get("kind") or "关联"),
            evidence_ids=_strings(item.get("evidence_ids")),
            source=relation_sources.get(relation_id),
            verification=_relation_verification(
                item.get("verification"), verification_locations_limit
            ),
        )

    def add_flow(raw_flow: Any, *, desired: bool) -> None:
        flow = _mapping(raw_flow)
        flow_id = str(flow.get("id") or "").strip()
        if not flow_id:
            return
        evidence_ids = _strings(flow.get("evidence_ids"))
        entities[flow_id] = _entity(
            flow_id,
            kind="business_flow",
            name=str(flow.get("name") or flow_id),
            summary=f"包含 {len(_list(flow.get('steps')))} 个显式步骤。",
            status=(
                f"EXPECTED_{flow.get('expectation') or 'REQUIRED'}"
                if desired
                else "OBSERVED"
            ),
            evidence_ids=evidence_ids,
        )
        if not desired:
            groups["flows"].append(flow_id)
        for index, raw_step in enumerate(_list(flow.get("steps"))):
            step = _mapping(raw_step)
            target_id = str(step.get("entity_id") or "")
            if target_id not in entities:
                continue
            relation_id = f"flow-step:{flow_id}:{index + 1}:{target_id}"
            relations[relation_id] = _relation(
                relation_id,
                kind="flow_step",
                source_id=flow_id,
                target_id=target_id,
                label=str(step.get("action") or f"步骤 {index + 1}"),
                evidence_ids=evidence_ids,
                order=index + 1,
            )

    def add_state_machine(raw_machine: Any, *, desired: bool) -> None:
        machine = _mapping(raw_machine)
        machine_id = str(machine.get("id") or "").strip()
        owner_id = str(machine.get("entity_id") or "")
        if not machine_id:
            return
        evidence_ids = _strings(machine.get("evidence_ids"))
        entities[machine_id] = _entity(
            machine_id,
            kind="state_machine",
            # 声明里给了名字就用名字 —— 与 flow 一致。此前无条件用 id, 于是标题栏上写着
            # `state-machine:inspection`, 对着它看的人学不到任何东西。
            name=str(machine.get("name") or machine_id),
            summary=(
                f"初始状态 {machine.get('initial_state') or 'UNKNOWN'}，"
                f"{len(_list(machine.get('transitions')))} 个显式转换。"
            ),
            status=(
                f"EXPECTED_{machine.get('expectation') or 'REQUIRED'}"
                if desired
                else "OBSERVED"
            ),
            evidence_ids=evidence_ids,
            attributes={
                "state_count": len(_list(machine.get("states"))),
                "transition_count": len(_list(machine.get("transitions"))),
            },
        )
        if not desired:
            groups["flows"].append(machine_id)
        if owner_id in entities:
            relation_id = f"governs:{machine_id}:{owner_id}"
            relations[relation_id] = _relation(
                relation_id,
                kind="governs_state",
                source_id=machine_id,
                target_id=owner_id,
                label="约束状态",
                evidence_ids=evidence_ids,
            )

    for raw in _list(project_model.get("flows")):
        add_flow(raw, desired=False)
    for raw in _list(project_model.get("state_machines")):
        add_state_machine(raw, desired=False)

    architecture_model = _mapping(project_model.get("architecture"))
    desired_state = _mapping(architecture_model.get("desired"))
    for raw in _list(desired_state.get("entities")):
        item = _mapping(raw)
        entity_id = str(item.get("id") or "").strip()
        if not entity_id:
            continue
        if entity_id not in entities:
            entities[entity_id] = _entity(
                entity_id,
                kind=str(item.get("kind") or "entity"),
                name=str(item.get("name") or entity_id),
                summary=str(item.get("responsibility") or "目标职责尚未声明。"),
                status=f"EXPECTED_{item.get('expectation') or 'REQUIRED'}",
                evidence_ids=_strings(item.get("evidence_ids")),
                attributes=(
                    {"locator": item.get("locator")}
                    if item.get("locator")
                    else {}
                ),
            )
    for raw in _list(desired_state.get("relations")):
        item = _mapping(raw)
        relation_id = str(item.get("id") or "").strip()
        source_id = str(item.get("source_id") or "")
        target_id = str(item.get("target_id") or "")
        if (
            relation_id
            and relation_id not in relations
            and source_id in entities
            and target_id in entities
        ):
            relations[relation_id] = _relation(
                relation_id,
                kind=str(item.get("kind") or "relates_to"),
                source_id=source_id,
                target_id=target_id,
                label=str(item.get("label") or "目标关系"),
                evidence_ids=_strings(item.get("evidence_ids")),
            )
    for raw in _list(desired_state.get("flows")):
        add_flow(raw, desired=True)
    for raw in _list(desired_state.get("state_machines")):
        add_state_machine(raw, desired=True)

    for identifier, title, payload in (
        ("code:codegraph", "代码索引", _mapping(snapshot.get("codegraph"))),
        ("code:complexity", "复杂度", _mapping(snapshot.get("complexity"))),
        ("code:coupling", "耦合", _mapping(snapshot.get("coupling"))),
        ("code:import-cycles", "循环依赖", _mapping(snapshot.get("import_cycles"))),
    ):
        if not payload:
            continue
        evidence_id = _add_inspection_evidence(
            evidence,
            f"inspection:{identifier}",
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
        )
        entities[identifier] = _entity(
            identifier,
            kind=identifier.removeprefix("code:"),
            name=title,
            summary=f"状态 {payload.get('state') or payload.get('verdict') or 'UNKNOWN'}。",
            status=str(payload.get("verdict") or payload.get("state") or "UNKNOWN"),
            evidence_ids=[evidence_id],
            attributes={
                key: value
                for key, value in payload.items()
                if key
                in {
                    "state",
                    "verdict",
                    "index_up_to_date",
                    "fail_count",
                    "warn_count",
                    "new_count",
                }
            },
        )
        groups["code"].append(identifier)

    tools = _mapping(_mapping(snapshot.get("tool_evidence")).get("tools"))
    for tool_id, raw in sorted(tools.items()):
        tool = _mapping(raw)
        entity_id = f"tool:{tool_id}"
        evidence_id = _add_inspection_evidence(
            evidence,
            f"inspection:{entity_id}",
            json.dumps(tool, ensure_ascii=False, sort_keys=True),
        )
        entities[entity_id] = _entity(
            entity_id,
            kind="external_tool",
            name=str(tool_id),
            summary=f"状态 {tool.get('state') or 'UNKNOWN'}，兼容 {tool.get('compatible', 'UNKNOWN')}。",
            status=str(tool.get("state") or "UNKNOWN"),
            evidence_ids=[evidence_id],
            attributes={
                "compatible": tool.get("compatible"),
                "compatibility_basis": tool.get("compatibility_basis"),
            },
        )
        groups["tools"].append(entity_id)

    change_safety = _mapping(inspection.get("change_safety"))
    if change_safety:
        change_id = "change:safety"
        change_evidence_ids = [
            evidence_id
            for evidence_id in _strings(change_safety.get("evidence_ids"))
            if evidence_id in evidence
        ]
        entities[change_id] = _entity(
            change_id,
            kind="change_safety",
            name="变更安全",
            summary=(
                f"阶段 {change_safety.get('phase') or 'UNKNOWN'}，"
                f"结论 {change_safety.get('verdict') or 'NO_GO'}。"
            ),
            status=str(change_safety.get("verdict") or "NO_GO"),
            evidence_ids=change_evidence_ids,
        )
        groups["code"].append(change_id)
        for index, raw in enumerate(_list(change_safety.get("associations"))):
            association = _mapping(raw)
            locator = str(association.get("path") or "")
            for target_id in _strings(association.get("entity_ids")):
                if target_id not in entities:
                    continue
                relation_id = f"change-affects:{index + 1}:{target_id}"
                relations[relation_id] = _relation(
                    relation_id,
                    kind="change_affects",
                    source_id=change_id,
                    target_id=target_id,
                    label=f"影响 {locator}" if locator else "影响",
                    evidence_ids=change_evidence_ids,
                )

    return entities, relations, groups


# `add_message` 是个混合入口: 各处检查的 warning/issue 都从这里进来, 所以归属**必须按
# 消息内容判**, 不能按产出点一刀切。2026-08-17 实测暑假古诗, 同一个产出点吐出的 5 条里
# 4 条是工具内务(codegraph 未初始化 x2 / complexity baseline 缺失 / safe view 禁用了
# 仓库自配可执行文件), 只有 1 条是项目问题(complexity hotspots: 4 findings)。
# 先前按产出点标成 project 是错的 —— 实测当场抓到。
#
# 判据只认**Moth 自身前置条件**这一类: 索引没建、基线没有、本工具的安全策略限制了自己。
# 其余一律归 project —— 宁可把工具内务误判成项目问题(用户看到多余的), 也不要反过来
# 把项目问题藏进折叠区(用户看不到该看的)。
_TOOLING_MESSAGE_MARKERS = (
    "codegraph",
    "complexity baseline",
    "baseline unavailable",
    "safe view disabled",
    "guidance",
    # "bounded filesystem scan was incomplete" = **Moth 自己的扫描预算**(max_depth/
    # max_entries)触顶, 不是项目的毛病。读者看到"bounded filesystem scan"既看不懂也
    # 无从下手。刻意只收这一条: 同批 coverage 消息里
    # "requires-python is unavailable without pyproject.toml"(清单缺字段)与
    # "requirements-ci.txt shares entrypoint"(项目结构)说的都是项目, 必须留在主列表。
    "bounded filesystem scan",
)


# 工具内务的修复命令。这些条目的正确答案就是"跑一条命令", 而通用文案
# ("打开对应证据, 用最小只读检查确认真实状态")对它们等于没说 —— 读者看不懂
# 也无从下手。给不出命令的必须诚实说明为什么, 不能编一条看着像的。
_TOOLING_REMEDIES = (
    ("codegraph", "codegraph sync <项目路径>", "索引没建或已过期, 重新同步即可。"),
    ("complexity baseline", "moth complexity <项目路径> --write-baseline",
     "首次需要写一份复杂度基线, 之后才能比较增量。"),
    ("baseline unavailable", "moth complexity <项目路径> --write-baseline",
     "首次需要写一份复杂度基线, 之后才能比较增量。"),
    ("safe view disabled", None,
     "这是 Moth 的安全策略: 只读视图不执行仓库自配的可执行文件。"
     "不是故障, 也不该为看报告而关掉它。"),
    ("guidance", None,
     "协作上下文需要由可信执行器激活并留下回执, 无法用一条命令补。"),
)


def _tooling_remedy(message: str) -> tuple[str | None, str]:
    """返回 (可复制的命令 | None, 一句人话说明)。"""

    low = str(message or "").lower()
    for marker, command, note in _TOOLING_REMEDIES:
        if marker in low:
            return command, note
    return None, "这是 Moth 自身的前置状态, 与你的项目无关。"


def _message_origin(message: str) -> str:
    low = str(message or "").lower()
    return ORIGIN_TOOLING if any(m in low for m in _TOOLING_MESSAGE_MARKERS) else ORIGIN_PROJECT


def _build_findings(
    *,
    inspection: dict[str, Any],
    snapshot: dict[str, Any],
    project_model: dict[str, Any],
    evidence: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    findings: dict[str, dict[str, Any]] = {}
    seen_messages: set[str] = set()

    def add_message(message: str, *, issue: bool) -> None:
        if message in seen_messages:
            return
        prefix = "issue" if issue else "warning"
        finding_id = _stable_id(prefix, message)
        evidence_id = _add_inspection_evidence(
            evidence,
            f"inspection:{finding_id}",
            message,
        )
        origin = _message_origin(message)
        if origin == ORIGIN_TOOLING:
            command, note = _tooling_remedy(message)
            # 保留 <项目路径> 占位而不是穿透仓路径进来: project_model/snapshot 都不带它,
            # 为一个占位符改函数签名不值得(奥卡姆), 而读者从项目选择器就知道自己选的是哪个目录。
            step = f"在项目目录下运行: {command}" if command else note
        else:
            step = "打开对应证据，用最小只读检查确认真实状态。"
        findings[finding_id] = _finding(
            finding_id,
            origin=origin,
            title="检查发现问题" if issue else "检查覆盖仍不完整",
            severity="high" if issue else "medium",
            confidence="high",
            action_bucket="now" if issue else "watch",
            why=message,
            impact=[
                "当前结论可能不可靠。"
                if issue
                else "未覆盖区域不能被当作已经确认安全。"
            ],
            safest_step=step,
            avoid=["不要删除门禁、放宽断言或把未知状态改写成通过。"],
            evidence_ids=[evidence_id],
            layer_ids=["overview", "evidence"],
            viewpoint_ids=["product", "system", "risk"],
        )
        seen_messages.add(message)

    for message in _strings(snapshot.get("issues")):
        add_message(message, issue=True)
    for message in _strings(snapshot.get("warnings")):
        add_message(message, issue=False)

    readiness = str(inspection.get("context_readiness") or "UNKNOWN")
    if readiness != "READY":
        evidence_id = _add_inspection_evidence(
            evidence,
            "inspection:context-readiness",
            f"context_readiness={readiness}",
        )
        findings["guidance-context"] = _finding(
            "guidance-context",
            origin=ORIGIN_TOOLING,  # guidance 上下文是 Moth 自身的加载前置
            title="协作上下文尚未验证",
            severity="high" if readiness == "BLOCKED" else "medium",
            confidence="high",
            action_bucket="now",
            why="Mio 与架构判断尚未得到平台级验证。",
            impact=["未经验证的协作声明可能造成假绿。"],
            safest_step="通过可信执行器完成 Guidance 激活并保留平台回执。",
            avoid=["不要把自证或缺失状态标记为 READY。"],
            evidence_ids=[evidence_id],
            layer_ids=["overview", "evidence"],
            viewpoint_ids=["product", "risk"],
        )

    dirty_count = int(snapshot.get("dirty_worktree_count") or 0)
    if dirty_count:
        evidence_id = _add_inspection_evidence(
            evidence,
            "inspection:dirty-worktree",
            f"dirty_worktree_count={dirty_count}",
        )
        findings["dirty-worktree"] = _finding(
            "dirty-worktree",
            origin=ORIGIN_PROJECT,  # 工作区状态属项目
            title="工作区存在未提交改动",
            severity="medium",
            confidence="high",
            action_bucket="now",
            why="未提交改动会让基线、影响范围和回滚点失真。",
            impact=["后续检查可能混入尚未确认的变化。"],
            safest_step="先审查并保存当前改动，再建立可复现检查点。",
            avoid=["不要在当前工作区执行不可逆变更。"],
            evidence_ids=[evidence_id],
            layer_ids=["overview", "code"],
            viewpoint_ids=["system", "risk"],
        )

    codegraph = _mapping(snapshot.get("codegraph"))
    if codegraph.get("index_up_to_date") is False:
        evidence_id = _add_inspection_evidence(
            evidence,
            "inspection:codegraph-freshness",
            f"codegraph.state={codegraph.get('state') or 'UNKNOWN'}",
        )
        findings["codegraph-freshness"] = _finding(
            "codegraph-freshness",
            origin=ORIGIN_TOOLING,  # codegraph 索引是 Moth 的前置条件
            title="代码索引不是最新状态",
            severity="high",
            confidence="high",
            action_bucket="now",
            why="陈旧索引不能支撑可靠的依赖与影响判断。",
            impact=["受影响模块和测试可能被漏报。"],
            safest_step="在项目目录下运行: codegraph sync <项目路径>",
            avoid=["不要用陈旧索引批准架构或删除变更。"],
            evidence_ids=[evidence_id],
            layer_ids=["code", "evidence"],
            viewpoint_ids=["system", "risk"],
        )

    high_count = int(
        _mapping(_mapping(snapshot.get("complexity")).get("summary")).get("high_count")
        or 0
    )
    if high_count:
        evidence_id = _add_inspection_evidence(
            evidence,
            "inspection:complexity-high",
            f"complexity.high_count={high_count}",
        )
        findings["complexity-high"] = _finding(
            "complexity-high",
            origin=ORIGIN_PROJECT,  # 复杂度热点说的是项目代码
            title="存在高风险复杂度线索",
            severity="medium",
            confidence="medium",
            action_bucket="watch",
            why="复杂度扫描发现需要真实调用路径或基准复核的热点。",
            impact=["热点可能放大性能、维护或变更风险。"],
            safest_step="从最高置信度热点开始做最小复现和调用路径核验。",
            avoid=["不要把启发式扫描直接写成已确认根因。"],
            evidence_ids=[evidence_id],
            layer_ids=["code", "evidence"],
            viewpoint_ids=["system", "risk"],
        )

    coverage = _mapping(project_model.get("coverage"))
    for message in _strings(coverage.get("warnings")):
        if message in seen_messages:
            continue
        finding_id = _stable_id("coverage", message)
        evidence_id = _add_inspection_evidence(
            evidence,
            f"inspection:{finding_id}",
            message,
        )
        findings[finding_id] = _finding(
            finding_id,
            origin=ORIGIN_PROJECT,  # 项目缺清单, 说的是项目
            title="项目识别覆盖不完整",
            severity="medium",
            confidence="high",
            action_bucket="watch",
            why=message,
            impact=["平台或运行时事实可能尚未进入项目模型。"],
            safest_step="补充对应 detector 所需的仓内真相源。",
            avoid=["不要把未探测到当作不存在。"],
            evidence_ids=[evidence_id],
            layer_ids=["overview", "evidence"],
            viewpoint_ids=["product", "system", "risk"],
        )
        seen_messages.add(message)
    change_safety = _mapping(inspection.get("change_safety"))
    change_verdict = str(change_safety.get("verdict") or "")
    if change_verdict in {"CAUTION", "NO_GO"}:
        evidence_ids = [
            evidence_id
            for evidence_id in _strings(change_safety.get("evidence_ids"))
            if evidence_id in evidence
        ]
        if not evidence_ids:
            evidence_ids = [
                _add_inspection_evidence(
                    evidence,
                    "inspection:change-safety",
                    f"change_safety={change_verdict}",
                )
            ]
        findings["change-safety"] = _finding(
            "change-safety",
            origin=ORIGIN_PROJECT,  # 变更安全裁决说的是项目改动的风险
            title=(
                "变更安全门禁未通过"
                if change_verdict == "NO_GO"
                else "变更仍需谨慎推进"
            ),
            severity="high" if change_verdict == "NO_GO" else "medium",
            confidence="high",
            action_bucket="now",
            why=", ".join(_strings(change_safety.get("reasons")))
            or "变更证据尚不足。",
            impact=["当前变更不能被当作已完成或可安全发布。"],
            safest_step="补齐缺失的结构影响、测试执行或仓库 gate 证据。",
            avoid=["不要把 affectedTests 计划清单冒充测试执行结果。"],
            evidence_ids=evidence_ids,
            layer_ids=["overview", "architecture", "code", "evidence"],
            viewpoint_ids=["system", "risk"],
        )
    architecture = _mapping(project_model.get("architecture"))
    drift = _mapping(architecture.get("drift"))
    for raw in _list(drift.get("findings")):
        item = _mapping(raw)
        status = str(item.get("status") or "UNVERIFIABLE")
        if status == "CONFORMANT":
            continue
        source_id = str(item.get("id") or "").strip()
        if not source_id:
            continue
        finding_id = f"architecture-drift:{source_id}"
        evidence_ids = sorted(
            set(_strings(item.get("declaration_evidence_ids")))
            | set(_strings(item.get("observation_evidence_ids")))
        )
        if not evidence_ids:
            evidence_id = _add_inspection_evidence(
                evidence,
                f"inspection:{finding_id}",
                str(item.get("reason") or "architecture drift is unverifiable"),
            )
            evidence_ids = [evidence_id]
        findings[finding_id] = _finding(
            finding_id,
            origin=ORIGIN_PROJECT,  # 架构漂移说的是项目结构与其声明不符
            title=(
                "架构约束与现状冲突"
                if status == "VIOLATION"
                else "架构漂移暂不可验证"
            ),
            severity="high" if status == "VIOLATION" else "medium",
            confidence="high" if status == "VIOLATION" else "medium",
            action_bucket="now" if status == "VIOLATION" else "watch",
            why=str(item.get("reason") or status),
            impact=[
                "显式架构约束未被当前拓扑满足。"
                if status == "VIOLATION"
                else "As-Is 覆盖不足，不能声称符合或违反目标架构。"
            ],
            safest_step="核对声明与观测证据，再修复约束或补齐探测覆盖。",
            avoid=["不要把不可验证状态洗成符合，也不要让视觉层反写架构声明。"],
            evidence_ids=evidence_ids,
            layer_ids=["architecture", "evidence"],
            viewpoint_ids=["system", "risk"],
        )
    return findings


def _build_actions(
    findings: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    actions: dict[str, dict[str, Any]] = {}
    for finding_id, finding in findings.items():
        avoid = _strings(finding.get("avoid"))
        if not avoid:
            continue
        action_id = f"avoid:{finding_id}"
        actions[action_id] = {
            "id": action_id,
            "kind": "avoid",
            "title": avoid[0],
            "basis_finding_id": finding_id,
            "evidence_ids": _strings(finding.get("evidence_ids")),
        }
    return actions


def _sorted_finding_ids(findings: dict[str, dict[str, Any]]) -> list[str]:
    return sorted(
        findings,
        key=lambda finding_id: (
            _BUCKET_RANK.get(str(findings[finding_id].get("action_bucket")), 9),
            _SEVERITY_RANK.get(str(findings[finding_id].get("severity")), 9),
            finding_id,
        ),
    )


def _build_layers(
    *,
    policy: dict[str, Any],
    groups: dict[str, list[str]],
    relations: dict[str, dict[str, Any]],
    findings: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    limit_entities = int(policy["limits"]["entities_per_layer"])
    limit_relations = int(policy["limits"]["relations_per_layer"])
    limit_findings = int(policy["limits"]["findings_per_layer"])
    limit_evidence = int(policy["limits"]["evidence_per_layer"])
    entity_map = {
        "overview": groups["project"],
        "architecture": groups["applications"] + groups["modules"],
        "stack": groups["runtimes"] + groups["technologies"],
        "flows": groups["flows"],
        "code": groups["code"],
        "evidence": groups["tools"] + groups["documents"],
    }
    layers = []
    for definition in policy["layers"]:
        layer_id = str(definition["id"])
        all_entities = sorted(set(entity_map.get(layer_id, [])))
        all_findings = sorted(
            finding_id
            for finding_id, finding in findings.items()
            if layer_id in _strings(finding.get("layer_ids"))
        )
        visible_findings = all_findings[:limit_findings]
        relation_ids = sorted(
            relation_id
            for relation_id, relation in relations.items()
            if relation["source_id"] in set(all_entities)
            or relation["target_id"] in set(all_entities)
        )
        finding_evidence_ids = sorted(
            {
                evidence_id
                for finding_id in visible_findings
                for evidence_id in _strings(findings[finding_id].get("evidence_ids"))
            }
        )
        if layer_id == "evidence":
            evidence_ids = finding_evidence_ids + sorted(
                set(evidence) - set(finding_evidence_ids)
            )
        else:
            evidence_ids = finding_evidence_ids
        layers.append(
            {
                "id": layer_id,
                "label": str(definition["label"]),
                "summary": str(definition["summary"]),
                "availability": "AVAILABLE" if all_entities or all_findings or evidence_ids else "PARTIAL",
                "entity_ids": all_entities[:limit_entities],
                "relation_ids": relation_ids[:limit_relations],
                "finding_ids": visible_findings,
                "evidence_ids": evidence_ids[:limit_evidence],
                "omitted": {
                    "entities": max(0, len(all_entities) - limit_entities),
                    "relations": max(0, len(relation_ids) - limit_relations),
                    "findings": max(0, len(all_findings) - limit_findings),
                    "evidence": max(0, len(evidence_ids) - limit_evidence),
                },
            }
        )
    return layers


def build_visual_model(inspection: dict[str, Any]) -> dict[str, Any]:
    policy = load_visual_policy()
    snapshot = _mapping(inspection.get("snapshot"))
    project_model = _mapping(snapshot.get("project_model"))
    evidence: dict[str, dict[str, Any]] = {}
    _copy_project_evidence(project_model, evidence)
    _copy_change_evidence(inspection, evidence)
    status = str(inspection.get("status") or "UNKNOWN")
    project_health = str(inspection.get("project_health") or "UNKNOWN")
    context_readiness = str(inspection.get("context_readiness") or "UNKNOWN")
    status_evidence_id = _add_inspection_evidence(
        evidence,
        "inspection:status",
        (
            f"status={status};project_health={project_health};"
            f"context_readiness={context_readiness}"
        ),
    )
    entities, relations, groups = _build_entities(
        inspection=inspection,
        snapshot=snapshot,
        project_model=project_model,
        evidence=evidence,
        verification_locations_limit=int(
            policy["limits"]["verification_locations_per_relation"]
        ),
    )
    findings = _build_findings(
        inspection=inspection,
        snapshot=snapshot,
        project_model=project_model,
        evidence=evidence,
    )
    actions = _build_actions(findings)
    ordered_findings = _sorted_finding_ids(findings)
    priorities = ordered_findings[: int(policy["limits"]["priorities"])]
    avoid_actions = [
        f"avoid:{finding_id}"
        for finding_id in ordered_findings
        if f"avoid:{finding_id}" in actions
    ][: int(policy["limits"]["avoid"])]
    project = _mapping(project_model.get("project"))
    project_id = str(project.get("id") or "project:unknown")
    identity_evidence = _strings(project.get("evidence_ids"))
    architecture_model = _mapping(project_model.get("architecture"))
    current_architecture = _mapping(architecture_model.get("current"))
    # S1: 架构图只画组件与组件间的结构关系。business_flow / state_machine 是流程记录,
    # 不是组件 —— 混进来会让"这个系统有几个组件"这个问题答不出来
    # (2026-09-07 实测: moth 自己的架构图 20 个节点里 4 个不是组件, 25 条边里 13 条不是
    # 结构关系)。project/runtime/technology 的既有排除保持不变。
    architecture_excluded_entity_kinds = {
        "project",
        "runtime",
        "technology",
        "business_flow",
        "state_machine",
    }
    architecture_excluded_relation_kinds = {"flow_step", "governs_state"}
    if architecture_model:
        all_architecture_entity_ids = sorted(
            {
                entity_id
                for entity_id in (
                    _strings(current_architecture.get("entity_ids"))
                    + _strings(current_architecture.get("flow_ids"))
                    + _strings(current_architecture.get("state_machine_ids"))
                )
                if entity_id in entities
                and entities[entity_id].get("kind")
                not in architecture_excluded_entity_kinds
            }
        )
    else:
        all_architecture_entity_ids = sorted(
            set(groups["applications"] + groups["modules"])
        )
    architecture_entity_limit = int(policy["limits"]["entities_per_layer"])
    architecture_relation_limit = int(policy["limits"]["relations_per_layer"])
    architecture_entity_ids = all_architecture_entity_ids[:architecture_entity_limit]
    # 关系必须按**这张卡片实际会展示的实体集**(截断后的 architecture_entity_ids)过滤端点,
    # 不是按截断前的全量集 —— 否则两个各自独立截断的列表凑不齐, 留下端点在图上找不到自己
    # 另一头的悬空边。这也是 S5 那条跨集合校验今天就是红的原因: uses-runtime 关系的 target
    # 是被排除的 runtime 实体, 关系本身此前却仍留在 relation_ids 里。
    _architecture_entity_id_set = set(architecture_entity_ids)
    if architecture_model:
        current_relation_ids = set(
            _strings(current_architecture.get("relation_ids"))
        )
        all_architecture_relation_ids = sorted(
            relation_id
            for relation_id, relation in relations.items()
            if relation_id in current_relation_ids
            and relation.get("kind") not in architecture_excluded_relation_kinds
            and relation["source_id"] in _architecture_entity_id_set
            and relation["target_id"] in _architecture_entity_id_set
        )
    else:
        all_architecture_relation_ids = sorted(
            relation_id
            for relation_id, relation in relations.items()
            if relation.get("kind") not in architecture_excluded_relation_kinds
            and relation["source_id"] in _architecture_entity_id_set
            and relation["target_id"] in _architecture_entity_id_set
        )
    architecture_relation_ids = all_architecture_relation_ids[:architecture_relation_limit]
    if architecture_model:
        desired = _mapping(architecture_model.get("desired"))
        to_be_entity_ids = sorted(
            {
                str(item.get("id"))
                for collection in ("entities", "flows", "state_machines")
                for item in (
                    _mapping(raw) for raw in _list(desired.get(collection))
                )
                if str(item.get("id") or "") in entities
            }
        )
        to_be_relation_ids = sorted(
            {
                str(item.get("id"))
                for item in (
                    _mapping(raw)
                    for raw in _list(desired.get("relations"))
                )
                if str(item.get("id") or "") in relations
            }
        )
        to_be_evidence_ids = [
            evidence_id
            for evidence_id in _strings(desired.get("evidence_ids"))
            if evidence_id in evidence
        ]
        to_be_is_declared = bool(
            desired.get("state") == "DECLARED"
            and to_be_evidence_ids
            and (to_be_entity_ids or to_be_relation_ids)
        )
        architecture_drift = _list(
            _mapping(architecture_model.get("drift")).get("findings")
        )
    else:
        desired = _mapping(snapshot.get("desired_architecture"))
        to_be_entity_ids = [
            str(item)
            for item in _list(desired.get("entity_ids"))
            if str(item) in entities
        ]
        to_be_relation_ids = [
            str(item)
            for item in _list(desired.get("relation_ids"))
            if str(item) in relations
        ]
        to_be_evidence_ids = [
            str(item)
            for item in _list(desired.get("evidence_ids"))
            if str(item) in evidence
        ]
        to_be_is_declared = bool(
            to_be_evidence_ids and (to_be_entity_ids or to_be_relation_ids)
        )
        architecture_drift = []
    labels = _mapping(policy.get("status_labels"))
    layers = _build_layers(
        policy=policy,
        groups=groups,
        relations=relations,
        findings=findings,
        evidence=evidence,
    )
    layer_by_id = {str(layer["id"]): layer for layer in layers}
    viewpoints = []
    for item in policy["viewpoints"]:
        viewpoint_id = str(item["id"])
        layer_ids = _strings(item["layer_ids"])
        viewpoint_layers = [
            layer_by_id[layer_id] for layer_id in layer_ids if layer_id in layer_by_id
        ]
        viewpoints.append(
            {
                "id": viewpoint_id,
                "label": str(item["label"]),
                "layer_ids": layer_ids,
                "entity_ids": sorted(
                    {
                        entity_id
                        for layer in viewpoint_layers
                        for entity_id in _strings(layer.get("entity_ids"))
                    }
                ),
                "relation_ids": sorted(
                    {
                        relation_id
                        for layer in viewpoint_layers
                        for relation_id in _strings(layer.get("relation_ids"))
                    }
                ),
                "finding_ids": sorted(
                    finding_id
                    for finding_id, finding in findings.items()
                    if viewpoint_id in _strings(finding.get("viewpoint_ids"))
                ),
            }
        )
    drift_counts = {"CONFORMANT": 0, "VIOLATION": 0, "UNVERIFIABLE": 0}
    for item in architecture_drift:
        status_name = str(_mapping(item).get("status") or "UNVERIFIABLE")
        if status_name in drift_counts:
            drift_counts[status_name] += 1
    if drift_counts["VIOLATION"]:
        architecture_state = "VIOLATION"
    elif drift_counts["UNVERIFIABLE"]:
        architecture_state = "UNVERIFIABLE"
    elif to_be_is_declared and architecture_drift:
        architecture_state = "CONFORMANT"
    elif not to_be_is_declared:
        architecture_state = "NOT_DECLARED"
    else:
        architecture_state = "PARTIAL"
    architecture_as_is = {
        # 采用 project_model 已经算好的结论, 不在这里第二次判定 ——
        # 此前这里无条件写 OBSERVED, 于是一份 100% 手写的架构声明也会显示成"观察到的"。
        # 拿不到上游结论时才退回按有没有实体来分, 且那种情况下不敢声称 OBSERVED。
        "state": str(
            current_architecture.get("state")
            or ("OBSERVED" if all_architecture_entity_ids else "PARTIAL")
        ),
        # 按**这张卡片实际展示的那批 id** 数, 不直接搬 project_model 的全量统计:
        # 大项目会按 entities_per_layer 截断引用列表, 两个口径混在一行里
        # ("20 个对象" 配 "共 35 项")会让人算不明白, 而算不明白的数字等于没给。
        "provenance": _provenance_of(
            project_model,
            architecture_entity_ids,
            architecture_relation_ids,
        ),
        "entity_ids": architecture_entity_ids,
        "relation_ids": architecture_relation_ids,
        "evidence_ids": sorted(
            {
                evidence_id
                for entity_id in architecture_entity_ids
                for evidence_id in _strings(entities[entity_id].get("evidence_ids"))
            }
        ),
        "omitted": {
            # 语义性排除(business_flow/state_machine 实体、flow_step/governs_state 关系、
            # 端点不全在 entity_ids 里的悬空关系)已经在 all_architecture_* 计算时被拿掉,
            # 不会流进这里 —— omitted 的既有语义是"因预算截断而省略", 把语义性排除混进来
            # 会让这个数字撒谎。
            "entities": len(all_architecture_entity_ids)
            - len(architecture_entity_ids),
            "relations": len(all_architecture_relation_ids)
            - len(architecture_relation_ids),
        },
    }
    # S2: 上游有 complete 且是布尔值才透传; 没声明就不输出这个键, 也不默认成
    # True/False —— "未声明"不等于"不完整"。
    current_complete = current_architecture.get("complete")
    if isinstance(current_complete, bool):
        architecture_as_is["complete"] = current_complete
    return {
        "schema_version": "moth.visual-document.v1",
        "source": {
            "inspection_digest": _digest(inspection),
            "generated_at": snapshot.get("generated_at"),
        },
        "identity": {
            "id": project_id,
            "name": project.get("name") or "未识别项目",
            "description": project.get("description"),
            "version": project.get("version"),
            "tags": [],
            "evidence_ids": identity_evidence,
        },
        "status": {
            "value": status,
            "project_health": project_health,
            "context_readiness": context_readiness,
            "label": labels.get(status, labels.get("UNKNOWN", "状态未知")),
            "summary": (
                f"项目健康 {project_health}，"
                f"协作上下文 {context_readiness}。"
            ),
            "evidence_ids": sorted(
                {status_evidence_id}
                | {
                    evidence_id
                    for finding in findings.values()
                    for evidence_id in _strings(finding.get("evidence_ids"))
                }
            ),
        },
        "home": {
            "priority_finding_ids": priorities,
            "avoid_action_ids": avoid_actions,
        },
        "navigation": {
            "layers": [
                {"id": str(item["id"]), "label": str(item["label"])}
                for item in policy["layers"]
            ],
            "viewpoints": viewpoints,
        },
        "entities": dict(sorted(entities.items())),
        "relations": dict(sorted(relations.items())),
        "findings": dict(sorted(findings.items())),
        "actions": dict(sorted(actions.items())),
        "evidence": dict(sorted(evidence.items())),
        "layers": layers,
        "diagram_policy": policy.get("diagram"),
        "terms": policy.get("terms"),
        "architecture": {
            "as_is": architecture_as_is,
            "to_be": {
                "state": "DECLARED" if to_be_is_declared else "NOT_DECLARED",
                "entity_ids": to_be_entity_ids if to_be_is_declared else [],
                "relation_ids": to_be_relation_ids if to_be_is_declared else [],
                "evidence_ids": to_be_evidence_ids if to_be_is_declared else [],
                "omitted": {"entities": 0, "relations": 0},
            },
            "drift": architecture_drift,
            "summary": {
                "state": architecture_state,
                "counts": drift_counts,
            },
        },
    }


def validate_visual_model(model: dict[str, Any]) -> list[str]:
    """Validate referential integrity that JSON Schema cannot express."""

    errors: list[str] = []
    entities = _mapping(model.get("entities"))
    relations = _mapping(model.get("relations"))
    findings = _mapping(model.get("findings"))
    actions = _mapping(model.get("actions"))
    evidence = _mapping(model.get("evidence"))
    layers = _list(model.get("layers"))
    layer_ids = {str(layer.get("id")) for layer in layers if isinstance(layer, dict)}
    viewpoints = _list(_mapping(model.get("navigation")).get("viewpoints"))
    viewpoint_ids = {
        str(viewpoint.get("id"))
        for viewpoint in viewpoints
        if isinstance(viewpoint, dict)
    }

    for mapping_name, values in (
        ("entity", entities),
        ("relation", relations),
        ("finding", findings),
        ("action", actions),
        ("evidence", evidence),
    ):
        for identifier, payload in values.items():
            if not isinstance(payload, dict) or payload.get("id") != identifier:
                errors.append(f"{mapping_name} {identifier} id does not match map key")

    def check_evidence(owner: str, identifiers: Any) -> None:
        for evidence_id in _strings(identifiers):
            if evidence_id not in evidence:
                errors.append(f"{owner} evidence reference missing: {evidence_id}")

    for entity_id, entity in entities.items():
        check_evidence(f"entity {entity_id}", entity.get("evidence_ids"))
    for relation_id, relation in relations.items():
        if relation.get("source_id") not in entities:
            errors.append(f"relation {relation_id} source reference missing")
        if relation.get("target_id") not in entities:
            errors.append(f"relation {relation_id} target reference missing")
        check_evidence(f"relation {relation_id}", relation.get("evidence_ids"))
    for finding_id, finding in findings.items():
        check_evidence(f"finding {finding_id}", finding.get("evidence_ids"))
        for layer_id in _strings(finding.get("layer_ids")):
            if layer_id not in layer_ids:
                errors.append(f"finding {finding_id} layer reference missing: {layer_id}")
        for viewpoint_id in _strings(finding.get("viewpoint_ids")):
            if viewpoint_id not in viewpoint_ids:
                errors.append(
                    f"finding {finding_id} viewpoint reference missing: {viewpoint_id}"
                )
    for action_id, action in actions.items():
        if action.get("basis_finding_id") not in findings:
            errors.append(f"action {action_id} basis finding reference missing")
        check_evidence(f"action {action_id}", action.get("evidence_ids"))

    status = _mapping(model.get("status"))
    if not _strings(status.get("evidence_ids")):
        errors.append("status requires at least one evidence reference")
    check_evidence("status", status.get("evidence_ids"))

    home = _mapping(model.get("home"))
    for finding_id in _strings(home.get("priority_finding_ids")):
        if finding_id not in findings:
            errors.append(f"home priority finding reference missing: {finding_id}")
    for action_id in _strings(home.get("avoid_action_ids")):
        if action_id not in actions:
            errors.append(f"home avoid action reference missing: {action_id}")

    for layer in layers:
        if not isinstance(layer, dict):
            continue
        layer_id = str(layer.get("id"))
        for field, known in (
            ("entity_ids", entities),
            ("relation_ids", relations),
            ("finding_ids", findings),
            ("evidence_ids", evidence),
        ):
            for identifier in _strings(layer.get(field)):
                if identifier not in known:
                    errors.append(f"layer {layer_id} {field} reference missing: {identifier}")

    for viewpoint in viewpoints:
        if not isinstance(viewpoint, dict):
            continue
        viewpoint_id = str(viewpoint.get("id"))
        for layer_id in _strings(viewpoint.get("layer_ids")):
            if layer_id not in layer_ids:
                errors.append(
                    f"viewpoint {viewpoint_id} layer reference missing: {layer_id}"
                )
        for field, known in (
            ("entity_ids", entities),
            ("relation_ids", relations),
            ("finding_ids", findings),
        ):
            for identifier in _strings(viewpoint.get(field)):
                if identifier not in known:
                    errors.append(
                        f"viewpoint {viewpoint_id} {field} reference missing: {identifier}"
                    )

    architecture = _mapping(model.get("architecture"))
    for state_name in ("as_is", "to_be"):
        state = _mapping(architecture.get(state_name))
        for field, known in (
            ("entity_ids", entities),
            ("relation_ids", relations),
            ("evidence_ids", evidence),
        ):
            for identifier in _strings(state.get(field)):
                if identifier not in known:
                    errors.append(
                        f"architecture {state_name} {field} reference missing: {identifier}"
                    )
    to_be = _mapping(architecture.get("to_be"))
    if to_be.get("state") == "DECLARED" and (
        not _strings(to_be.get("evidence_ids"))
        or not (
            _strings(to_be.get("entity_ids"))
            or _strings(to_be.get("relation_ids"))
        )
    ):
        errors.append(
            "declared To-Be requires evidence and at least one entity or relation"
        )

    # S5: architecture.as_is 是画架构图用的那批 id —— 图上不能有一条边只有一头站得住。
    # (a) 两端都必须是留在 as_is.entity_ids 里的组件, 不能悬空引用一个被排除的实体;
    # (b) 必须带 source, 查不到来源时前端没法决定这条边画实线还是虚线, 不能悄悄漏掉。
    # 两条都必须点名是哪条 relation, 否则读错误信息的人不知道该去修哪一条。
    as_is = _mapping(architecture.get("as_is"))
    as_is_entity_ids = set(_strings(as_is.get("entity_ids")))
    for relation_id in _strings(as_is.get("relation_ids")):
        relation = _mapping(relations.get(relation_id))
        if (
            relation.get("source_id") not in as_is_entity_ids
            or relation.get("target_id") not in as_is_entity_ids
        ):
            errors.append(
                f"architecture as_is relation {relation_id} endpoint missing from entity_ids"
            )
        if "source" not in relation:
            errors.append(
                f"architecture as_is relation {relation_id} is missing source"
            )
    return errors


def validate_visual_document_schema(model: dict[str, Any]) -> list[str]:
    """Validate the public visual contract from its packaged canonical schema."""

    schema = json.loads(
        files("moth.schemas")
        .joinpath("moth.visual-document.schema.json")
        .read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(model),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    return [
        (
            f"{'.'.join(str(item) for item in error.absolute_path) or '<root>'}: "
            f"{error.message}"
        )
        for error in errors
    ]
