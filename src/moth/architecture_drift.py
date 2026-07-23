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
                else:
                    status = "CONFORMANT"
                    reason = "required subject was observed"
            elif actual is not None:
                status = "VIOLATION"
                reason = "forbidden subject was observed"
            elif current_complete:
                status = "CONFORMANT"
                reason = "forbidden subject was not observed in complete coverage"
            else:
                status = "UNVERIFIABLE"
                reason = "current architecture coverage is incomplete"
            findings.append(
                {
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
            )

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
