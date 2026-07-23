"""Validate structured evidence that discovered guidance influenced decisions."""

from __future__ import annotations

import json
from datetime import datetime
from importlib.resources import files
from typing import Any

import yaml
from jsonschema import Draft202012Validator


def _load_policy() -> dict[str, Any]:
    payload = yaml.safe_load(
        files("moth")
        .joinpath("guidance_application_policy.yaml")
        .read_text(encoding="utf-8")
    )
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "moth_guidance_application_policy"
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("contract"), dict)
        or not isinstance(payload.get("limits"), dict)
        or not isinstance(payload.get("states"), dict)
        or not isinstance(payload.get("conflict_resolutions"), list)
    ):
        raise ValueError("invalid packaged guidance application policy")
    return payload


def _load_schema() -> dict[str, Any]:
    payload = json.loads(
        files("moth")
        .joinpath("schemas/moth.guidance-application.schema.json")
        .read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise ValueError("invalid packaged guidance application schema")
    Draft202012Validator.check_schema(payload)
    return payload


_POLICY = _load_policy()
_SCHEMA = _load_schema()


def _validate_policy_schema_contract(
    policy: dict[str, Any], schema: dict[str, Any]
) -> None:
    states = policy["states"]
    if (
        not isinstance(states.get("report"), dict)
        or not isinstance(states.get("application"), dict)
        or set(states["report"]) != {"none", "valid", "invalid", "stale"}
        or set(states["application"]) != {"not_claimed", "applied"}
        or policy["contract"].get("activation_states")
        != ["SELF_ATTESTED", "PLATFORM_VERIFIED"]
    ):
        raise ValueError("invalid packaged guidance application states")
    properties = schema.get("properties", {})
    definitions = schema.get("$defs", {})
    expected = (
        policy["contract"]["schema_version"]
        == properties.get("schema_version", {}).get("const")
        and policy["conflict_resolutions"]
        == properties.get("conflicts", {})
        .get("items", {})
        .get("properties", {})
        .get("resolution", {})
        .get("enum")
        and policy["limits"]["decisions"]
        == properties.get("decisions_influenced", {}).get("maxItems")
        and policy["limits"]["conflicts"]
        == properties.get("conflicts", {}).get("maxItems")
        and policy["limits"]["evidence_refs"]
        == definitions.get("non_empty_ref_list", {}).get("maxItems")
        and policy["limits"]["summary_chars"]
        == properties.get("decision_summary", {}).get("maxLength")
        and policy["limits"]["summary_chars"]
        == properties.get("decisions_influenced", {})
        .get("items", {})
        .get("properties", {})
        .get("summary", {})
        .get("maxLength")
    )
    if not expected:
        raise ValueError("guidance application policy/schema drift")


_validate_policy_schema_contract(_POLICY, _SCHEMA)
_VALIDATOR = Draft202012Validator(_SCHEMA)


def _empty_summary(source_id: str, report_state: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "report_state": report_state,
        "application_state": _POLICY["states"]["application"]["not_claimed"],
        "contract_id": None,
        "loaded_at": None,
        "decision_summary": None,
        "evidence_refs": [],
        "decisions_influenced": [],
        "conflicts": [],
    }


def _valid_summary(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": report["source_id"],
        "report_state": _POLICY["states"]["report"]["valid"],
        "application_state": _POLICY["states"]["application"]["applied"],
        "contract_id": report["contract_id"],
        "loaded_at": report["loaded_at"],
        "decision_summary": report["decision_summary"],
        "evidence_refs": sorted(report["evidence_refs"]),
        "decisions_influenced": sorted(
            (
                {
                    "decision_id": decision["decision_id"],
                    "summary": decision["summary"],
                    "evidence_refs": sorted(decision["evidence_refs"]),
                }
                for decision in report["decisions_influenced"]
            ),
            key=lambda item: item["decision_id"],
        ),
        "conflicts": sorted(
            (
                {
                    "conflict_id": conflict["conflict_id"],
                    "with_source_ids": sorted(conflict["with_source_ids"]),
                    "resolution": conflict["resolution"],
                    "evidence_refs": sorted(conflict["evidence_refs"]),
                }
                for conflict in report["conflicts"]
            ),
            key=lambda item: item["conflict_id"],
        ),
    }


def _valid_time(value: str) -> bool:
    if not value.endswith("Z"):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _semantically_valid(
    report: dict[str, Any],
    *,
    available_evidence_ids: set[str],
    activation_binding: dict[str, Any],
) -> bool:
    decision_ids = [
        item["decision_id"] for item in report["decisions_influenced"]
    ]
    conflict_ids = [item["conflict_id"] for item in report["conflicts"]]
    referenced_evidence = set(report["evidence_refs"])
    for decision in report["decisions_influenced"]:
        referenced_evidence.update(decision["evidence_refs"])
    for conflict in report["conflicts"]:
        referenced_evidence.update(conflict["evidence_refs"])
    return (
        len(decision_ids) == len(set(decision_ids))
        and len(conflict_ids) == len(set(conflict_ids))
        and bool(referenced_evidence)
        and referenced_evidence <= available_evidence_ids
        and _valid_time(report["loaded_at"])
        and activation_binding.get("receipt_state")
        in _POLICY["contract"]["activation_states"]
        and report["contract_id"] == activation_binding.get("contract_id")
        and report["loaded_at"] == activation_binding.get("loaded_at")
        and all(
            report["source_id"] not in conflict["with_source_ids"]
            for conflict in report["conflicts"]
        )
    )


def evaluate_guidance_applications(
    sources: list[dict[str, Any]],
    *,
    run_id: str,
    reports: list[dict[str, Any]] | None = None,
    available_evidence_ids: set[str] | None = None,
    activation_bindings: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return bounded application claims without interpreting guidance prose."""

    configured_reports = [] if reports is None else reports
    evidence_ids = set() if available_evidence_ids is None else set(available_evidence_ids)
    bindings = {} if activation_bindings is None else activation_bindings
    if not isinstance(configured_reports, list):
        raise ValueError("guidance application reports must be a list")
    max_reports = int(_POLICY["limits"]["reports"])
    if len(configured_reports) > max_reports:
        raise ValueError("too many guidance application reports")

    by_id = {str(source.get("id", "")): source for source in sources}
    if len(by_id) != len(sources) or "" in by_id:
        raise ValueError("guidance application sources must have unique ids")

    report_by_source: dict[str, dict[str, Any]] = {}
    for report in configured_reports:
        if not isinstance(report, dict):
            raise ValueError("guidance application report must be an object")
        source_id = report.get("source_id")
        if not isinstance(source_id, str) or source_id not in by_id:
            raise ValueError(
                "guidance application report references unknown guidance source"
            )
        if source_id in report_by_source:
            raise ValueError("duplicate guidance application report")
        report_by_source[source_id] = report

    summaries: list[dict[str, Any]] = []
    report_states = _POLICY["states"]["report"]
    for source in sources:
        source_id = str(source["id"])
        report = report_by_source.get(source_id)
        if report is None:
            summaries.append(_empty_summary(source_id, report_states["none"]))
            continue
        if not _VALIDATOR.is_valid(report):
            summaries.append(_empty_summary(source_id, report_states["invalid"]))
            continue
        if source.get("state") != "DISCOVERED" or not source.get("source_digest"):
            summaries.append(_empty_summary(source_id, report_states["invalid"]))
            continue
        if (
            report["run_id"] != run_id
            or report["source_id"] != source_id
            or report["source_digest"] != source.get("source_digest")
        ):
            summaries.append(_empty_summary(source_id, report_states["stale"]))
            continue
        binding = bindings.get(source_id)
        if not isinstance(binding, dict):
            summaries.append(_empty_summary(source_id, report_states["invalid"]))
            continue
        if (
            report["contract_id"] != binding.get("contract_id")
            or report["loaded_at"] != binding.get("loaded_at")
        ):
            summaries.append(_empty_summary(source_id, report_states["stale"]))
            continue
        if not _semantically_valid(
            report,
            available_evidence_ids=evidence_ids,
            activation_binding=binding,
        ):
            summaries.append(_empty_summary(source_id, report_states["invalid"]))
            continue
        summaries.append(_valid_summary(report))
    return summaries
