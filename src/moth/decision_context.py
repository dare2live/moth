"""Task-level guidance ordering and honest executor-attestation states."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from moth.guidance_application import evaluate_guidance_applications
from moth.guidance_policy import TASK_ACTIVATIONS

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}$")


def _ordered(active: list[dict[str, Any]], all_ids: set[str]) -> list[dict[str, Any]]:
    by_id = {str(item["id"]): item for item in active}
    for item in active:
        for dep in item.get("load_after", []):
            if dep not in all_ids:
                raise ValueError(f"missing guidance dependency: {dep}")
    result: list[dict[str, Any]] = []
    remaining = dict(by_id)
    while remaining:
        ready = sorted(
            (item for item in remaining.values() if all(dep not in remaining for dep in item.get("load_after", []))),
            key=lambda item: str(item["id"]),
        )
        if not ready:
            raise ValueError("guidance load order contains a cycle")
        for item in ready:
            result.append(item)
            remaining.pop(str(item["id"]))
    return result


def _valid_time(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _receipt_state(receipt: dict[str, Any], source: dict[str, Any], run_id: str) -> str:
    required = {"receipt_id", "run_id", "source_id", "source_digest", "executor_id", "loaded_at", "contract_id", "evidence_refs"}
    if set(receipt) != required:
        return "INVALID"
    for key in ("receipt_id", "run_id", "source_id", "executor_id", "contract_id"):
        if not isinstance(receipt.get(key), str) or not _SAFE_ID.fullmatch(receipt[key]):
            return "INVALID"
    refs = receipt.get("evidence_refs")
    if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) and _SAFE_REF.fullmatch(ref) for ref in refs):
        return "INVALID"
    if not _valid_time(receipt.get("loaded_at")):
        return "INVALID"
    if source.get("state") != "DISCOVERED" or not source.get("source_digest"):
        return "INVALID"
    if receipt["run_id"] != run_id or receipt["source_id"] != source["id"] or receipt["source_digest"] != source["source_digest"]:
        return "STALE"
    # Local helper output is an executor self-attestation, not host-verifiable proof.
    return "SELF_ATTESTED"


def build_decision_context(
    guidance: dict[str, Any],
    *,
    task_kind: str,
    run_id: str,
    receipts: list[dict[str, Any]],
    application_reports: list[dict[str, Any]] | None = None,
    available_evidence_ids: set[str] | None = None,
) -> dict[str, Any]:
    if task_kind not in TASK_ACTIVATIONS:
        raise ValueError(f"unknown task kind: {task_kind}")
    if not isinstance(run_id, str) or not _SAFE_ID.fullmatch(run_id):
        raise ValueError("run_id must be a bounded portable identifier")
    sources = guidance.get("sources") or []
    ids = [str(item.get("id")) for item in sources]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate guidance source id")
    by_id = {str(item["id"]): item for item in sources}
    receipt_by_source: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        source_id = str(receipt.get("source_id", ""))
        if source_id not in by_id:
            raise ValueError("activation receipt references unknown guidance source")
        if source_id in receipt_by_source:
            raise ValueError("duplicate activation receipt")
        receipt_by_source[source_id] = receipt
    active = [item for item in sources if item.get("activation") in TASK_ACTIVATIONS[task_kind]]
    ordered = _ordered(active, set(ids))
    receipt_states: dict[str, str] = {}
    activation_bindings: dict[str, dict[str, Any]] = {}
    for source in ordered:
        source_id = str(source["id"])
        receipt = receipt_by_source.get(source_id)
        state = "NONE" if receipt is None else _receipt_state(receipt, source, run_id)
        receipt_states[source_id] = state
        if receipt is not None and state in {"SELF_ATTESTED", "PLATFORM_VERIFIED"}:
            activation_bindings[source_id] = {
                "receipt_state": state,
                "contract_id": receipt["contract_id"],
                "loaded_at": receipt["loaded_at"],
            }
    guidance_applications = evaluate_guidance_applications(
        ordered,
        run_id=run_id,
        reports=application_reports,
        available_evidence_ids=available_evidence_ids,
        activation_bindings=activation_bindings,
    )
    application_by_source = {
        item["source_id"]: item for item in guidance_applications
    }
    guidance_rows: list[dict[str, Any]] = []
    missing: list[str] = []
    self_attested_required: list[str] = []
    sanitized_receipts: list[dict[str, Any]] = []
    application_reports_provided = bool(application_reports)
    missing_application: list[str] = []
    for source in ordered:
        source_id = str(source["id"])
        applicability = "REQUIRED" if source.get("requirement") == "required_when_active" else "OPTIONAL"
        receipt = receipt_by_source.get(source_id)
        state = receipt_states[source_id]
        if applicability == "REQUIRED" and state == "SELF_ATTESTED":
            self_attested_required.append(source_id)
        elif applicability == "REQUIRED" and state != "PLATFORM_VERIFIED":
            missing.append(source_id)
        row = {
            "source_id": source_id,
            "discovery_state": source.get("state", "UNAVAILABLE"),
            "applicability": applicability,
            "receipt_state": state,
            "application_state": application_by_source[source_id][
                "application_state"
            ],
        }
        guidance_rows.append(row)
        if (
            application_reports_provided
            and applicability == "REQUIRED"
            and row["application_state"] != "APPLIED_WITH_EVIDENCE"
        ):
            missing_application.append(source_id)
        if receipt is not None:
            sanitized_receipts.append({
                "source_id": source_id,
                "receipt_state": state,
                "attestation_kind": "executor_self_attested",
            })
    readiness = (
        "BLOCKED"
        if missing or missing_application
        else "SELF_ATTESTED"
        if self_attested_required
        else "READY"
    )
    return {
        "schema_version": "moth.decision_context.v1",
        "task": {"kind": task_kind, "run_id": run_id},
        "ordered_guidance_sources": [str(item["id"]) for item in ordered],
        "guidance": guidance_rows,
        "context_readiness": readiness,
        "missing_required_sources": missing,
        "self_attested_required_sources": self_attested_required,
        "application_readiness": (
            "NOT_REPORTED"
            if not application_reports_provided
            else "BLOCKED"
            if missing_application
            else "COMPLETE"
        ),
        "missing_application_sources": missing_application,
        "not_applicable_sources": sorted(set(ids) - {str(item["id"]) for item in active}),
        "activation_receipts": sanitized_receipts,
        "guidance_applications": guidance_applications,
        "project_health_affected": False,
    }
