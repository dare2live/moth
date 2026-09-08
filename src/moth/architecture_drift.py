"""Compare explicit architecture constraints against observed topology."""

from __future__ import annotations

from typing import Any


_COLLECTIONS = ("entities", "relations", "flows", "state_machines")
_SUBJECT_KINDS = {
    "entities": "entity",
    "relations": "relation",
    "flows": "flow",
    "state_machines": "state_machine",
}


def _constraint_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"expectation", "evidence_ids"}
    }


def _matches_constraint(actual: Any, constraint: Any) -> bool:
    """Match only fields explicitly declared by a partial desired constraint."""

    if isinstance(constraint, dict):
        return isinstance(actual, dict) and all(
            key in actual and _matches_constraint(actual[key], value)
            for key, value in constraint.items()
        )
    if isinstance(constraint, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(constraint)
            and all(
                _matches_constraint(actual_item, constraint_item)
                for actual_item, constraint_item in zip(actual, constraint)
            )
        )
    return actual == constraint


def build_architecture_drift(
    *,
    current: dict[str, Any],
    desired: dict[str, Any],
) -> dict[str, Any]:
    constraints = sum((list(desired[name]) for name in _COLLECTIONS), [])
    if not constraints:
        return {
            "state": "NOT_COMPUTED",
            "findings": [],
            "violation_ids": [],
            "unverifiable_ids": [],
            "conformant_ids": [],
        }

    current_complete = bool(current.get("complete"))
    findings: list[dict[str, Any]] = []
    for collection in _COLLECTIONS:
        observed = {item["id"]: item for item in current[collection]}
        subject_kind = _SUBJECT_KINDS[collection]
        for constraint in desired[collection]:
            subject_id = constraint["id"]
            finding_id = f"{subject_kind}:{subject_id}"
            actual = observed.get(subject_id)
            expectation = constraint["expectation"]
            observation_basis: str | None = None
            if expectation == "REQUIRED":
                if actual is None:
                    status = "VIOLATION" if current_complete else "UNVERIFIABLE"
                    reason = (
                        "required subject was not observed"
                        if current_complete
                        else "current architecture coverage is incomplete"
                    )
                elif not _matches_constraint(actual, _constraint_fields(constraint)):
                    status = "VIOLATION"
                    reason = "observed subject conflicts with required attributes"
                elif subject_kind in ("flow", "state_machine"):
                    # Phase 2 M6: 没有任何检测器独立看到过 flow/state_machine —— 声明里
                    # current 和 desired 对上号只说明同一份 yaml 跟自己一致, 不是证据。
                    status = "UNVERIFIABLE"
                    reason = (
                        "no detector observes flows or state machines independently "
                        "of the declaration"
                    )
                elif subject_kind == "relation":
                    # Phase 2 M6: 关系此前恒等于自己跟自己比 (current 的声明关系就是
                    # desired 抄的同一份 yaml), 现在按 import 图三档判定的 source 来定:
                    # 只有 DECLARED(没被 import 图证实) 才降级成 UNVERIFIABLE。
                    if actual.get("source") == "DECLARED":
                        status = "UNVERIFIABLE"
                        verification = actual.get("verification") or {}
                        v_status = verification.get("status", "UNKNOWN")
                        v_reason = verification.get("reason")
                        reason = (
                            f"declared relation is not independently verified by the "
                            f"import graph (verification={v_status}"
                            + (f", reason={v_reason}" if v_reason else "")
                            + ")"
                        )
                    else:
                        status = "CONFORMANT"
                        reason = "required subject was observed"
                        observation_basis = "import_graph"
                else:
                    # entity: locator 已经在声明加载时校验过真的存在于仓库里, 这是
                    # 真观测 —— 但只观测到"文件存在", 职责文本(responsibility)从来
                    # 没有被任何检测器核实过, observation_basis 说清楚这一点。
                    status = "CONFORMANT"
                    reason = "required subject was observed"
                    if actual.get("locator"):
                        observation_basis = "locator_exists"
            elif actual is not None:
                status = "VIOLATION"
                reason = "forbidden subject was observed"
            elif current_complete:
                status = "CONFORMANT"
                reason = "forbidden subject was not observed in complete coverage"
            else:
                status = "UNVERIFIABLE"
                reason = "current architecture coverage is incomplete"
            finding = {
                "id": finding_id,
                "subject_id": subject_id,
                "subject_kind": subject_kind,
                "expectation": expectation,
                "status": status,
                "reason": reason,
                "declaration_evidence_ids": constraint["evidence_ids"],
                "observation_evidence_ids": (
                    actual.get("evidence_ids", []) if actual else []
                ),
            }
            if observation_basis:
                finding["observation_basis"] = observation_basis
            findings.append(finding)

    findings.sort(key=lambda item: item["id"])
    by_status = {
        status: [item["id"] for item in findings if item["status"] == status]
        for status in ("VIOLATION", "UNVERIFIABLE", "CONFORMANT")
    }
    if by_status["VIOLATION"]:
        state = "DRIFT_DETECTED"
    elif by_status["UNVERIFIABLE"]:
        state = "UNVERIFIABLE"
    else:
        state = "CONFORMANT"
    return {
        "state": state,
        "findings": findings,
        "violation_ids": by_status["VIOLATION"],
        "unverifiable_ids": by_status["UNVERIFIABLE"],
        "conformant_ids": by_status["CONFORMANT"],
    }
