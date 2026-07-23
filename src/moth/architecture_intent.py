"""Load repository-owned architecture intent without interpreting prose."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


_DECLARATION_EVIDENCE_ID = "architecture-declaration"
_COLLECTIONS = ("entities", "relations", "flows", "state_machines")


def load_architecture_policy() -> dict[str, Any]:
    path = Path(__file__).with_name("architecture_policy.yaml")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("architecture policy must be a mapping")
    required = {"schema_version", "declaration_path", "limits", "vocabulary"}
    if set(data) != required:
        raise ValueError("architecture policy keys are invalid")
    if data["schema_version"] != "moth.architecture-policy.v1":
        raise ValueError("unsupported architecture policy")
    declaration = Path(str(data["declaration_path"]))
    if declaration.is_absolute() or ".." in declaration.parts:
        raise ValueError("architecture declaration path must be repository-relative")
    for key, value in data["limits"].items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"architecture policy limit {key} must be positive")
    return data


def _empty_intent(state: str, *, issues: list[str] | None = None) -> dict[str, Any]:
    empty_state = {
        "complete": False,
        "entities": [],
        "relations": [],
        "flows": [],
        "state_machines": [],
    }
    return {
        "schema_version": "moth.architecture-intent.v1",
        "state": state,
        "current": dict(empty_state),
        "desired": dict(empty_state),
        "evidence": [],
        "issues": list(issues or []),
        "warnings": [],
    }


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _safe_repo_file(
    repo: Path,
    raw_path: Any,
    *,
    max_bytes: int,
) -> tuple[str | None, bytes | None, str | None]:
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        return None, None, "evidence path is invalid"
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        return None, None, "evidence path escapes repository"
    candidate = repo / relative
    if candidate.is_symlink():
        return None, None, "architecture evidence cannot be a symlink"
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo)
    except (OSError, ValueError):
        return None, None, "architecture evidence is unavailable"
    if not resolved.is_file():
        return None, None, "architecture evidence is not a file"
    try:
        with resolved.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError:
        return None, None, "architecture evidence is unreadable"
    if len(raw) > max_bytes:
        return None, None, "architecture evidence exceeds configured limit"
    return relative.as_posix(), raw, None


def _schema_errors(payload: Any) -> list[str]:
    schema_path = Path(__file__).with_name("schemas") / (
        "moth.architecture-intent.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    return [
        "architecture declaration schema: "
        + (".".join(str(item) for item in error.absolute_path) or "<root>")
        + f": {error.message}"
        for error in errors
    ]


def _bounded(payload: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    limits = policy["limits"]
    issues: list[str] = []
    if len(payload["evidence"]) > limits["evidence_files"]:
        issues.append("architecture evidence count exceeds configured limit")
    for state_name in ("current", "desired"):
        state = payload[state_name]
        for collection, limit_key in (
            ("entities", "entities_per_state"),
            ("relations", "relations_per_state"),
            ("flows", "flows_per_state"),
            ("state_machines", "state_machines_per_state"),
        ):
            if len(state[collection]) > limits[limit_key]:
                issues.append(
                    f"architecture {state_name}.{collection} exceeds configured limit"
                )
        for flow in state["flows"]:
            if len(flow["steps"]) > limits["steps_per_flow"]:
                issues.append("architecture flow steps exceed configured limit")
        for machine in state["state_machines"]:
            if len(machine["states"]) > limits["states_per_machine"]:
                issues.append("architecture states exceed configured limit")
            if len(machine["transitions"]) > limits["transitions_per_machine"]:
                issues.append("architecture transitions exceed configured limit")
    return issues


def _unique_ids(payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for state_name in ("current", "desired"):
        state = payload[state_name]
        for collection in _COLLECTIONS:
            ids = [item["id"] for item in state[collection]]
            if len(ids) != len(set(ids)):
                issues.append(
                    f"architecture {state_name}.{collection} ids must be unique"
                )
        for flow in state["flows"]:
            step_ids = [step["id"] for step in flow["steps"]]
            if len(step_ids) != len(set(step_ids)):
                issues.append(f"architecture flow {flow['id']} step ids must be unique")
        for machine in state["state_machines"]:
            transition_ids = [item["id"] for item in machine["transitions"]]
            if len(transition_ids) != len(set(transition_ids)):
                issues.append(
                    f"architecture state machine {machine['id']} transition ids must be unique"
                )
    return issues


def _validate_vocabulary(
    payload: dict[str, Any], policy: dict[str, Any]
) -> list[str]:
    vocabulary = policy["vocabulary"]
    entity_kinds = set(vocabulary["entity_kinds"])
    relation_kinds = set(vocabulary["relation_kinds"])
    expectations = set(vocabulary["expectations"])
    issues: list[str] = []
    for state_name in ("current", "desired"):
        state = payload[state_name]
        for item in state["entities"]:
            if state_name == "current" and "expectation" in item:
                issues.append("current architecture facts cannot declare expectations")
            if item["kind"] not in entity_kinds:
                issues.append(f"architecture entity kind is not configured: {item['kind']}")
        for item in state["relations"]:
            if state_name == "current" and "expectation" in item:
                issues.append("current architecture facts cannot declare expectations")
            if item["kind"] not in relation_kinds:
                issues.append(
                    f"architecture relation kind is not configured: {item['kind']}"
                )
        if state_name == "desired":
            for collection in _COLLECTIONS:
                for item in state[collection]:
                    if item["expectation"] not in expectations:
                        issues.append("architecture expectation is not configured")
        else:
            for collection in ("flows", "state_machines"):
                if any("expectation" in item for item in state[collection]):
                    issues.append(
                        "current architecture facts cannot declare expectations"
                    )
    return issues


def _claim_evidence(
    payload: dict[str, Any],
    known_evidence: set[str],
) -> list[str]:
    issues: list[str] = []
    for state_name in ("current", "desired"):
        for collection in _COLLECTIONS:
            for item in payload[state_name][collection]:
                unknown = sorted(set(item["evidence_ids"]) - known_evidence)
                if unknown:
                    issues.append(
                        f"architecture {item['id']} references unknown evidence"
                    )
                item["evidence_ids"] = sorted(
                    set(item["evidence_ids"]) | {_DECLARATION_EVIDENCE_ID}
                )
    return issues


def _validate_references(
    payload: dict[str, Any],
    base_entity_ids: set[str],
) -> list[str]:
    issues: list[str] = []
    current = payload["current"]
    desired = payload["desired"]
    current_ids = base_entity_ids | {item["id"] for item in current["entities"]}
    desired_ids = current_ids | {item["id"] for item in desired["entities"]}

    def validate_state(state: dict[str, Any], entity_ids: set[str]) -> None:
        for relation in state["relations"]:
            for endpoint in ("source_id", "target_id"):
                if relation[endpoint] not in entity_ids:
                    issues.append(
                        f"architecture {relation['id']} references unknown entity "
                        f"{relation[endpoint]}"
                    )
        for flow in state["flows"]:
            for step in flow["steps"]:
                if step["entity_id"] not in entity_ids:
                    issues.append(
                        f"architecture {flow['id']} references unknown entity "
                        f"{step['entity_id']}"
                    )
        for machine in state["state_machines"]:
            if machine["entity_id"] not in entity_ids:
                issues.append(
                    f"architecture {machine['id']} references unknown entity "
                    f"{machine['entity_id']}"
                )
            states = set(machine["states"])
            if machine["initial_state"] not in states:
                issues.append(
                    f"architecture {machine['id']} initial state is not declared"
                )
            for transition in machine["transitions"]:
                if (
                    transition["from_state"] not in states
                    or transition["to_state"] not in states
                ):
                    issues.append(
                        f"architecture {machine['id']} transition references unknown state"
                    )

    validate_state(current, current_ids)
    validate_state(desired, desired_ids)
    return issues


def load_architecture_intent(
    repo_path: str | Path,
    *,
    base_entity_ids: set[str],
) -> dict[str, Any]:
    """Load one conventional, repository-owned declaration or return an honest state."""

    repo = Path(repo_path).resolve()
    policy = load_architecture_policy()
    relative = Path(policy["declaration_path"])
    declaration_path = repo / relative
    if not declaration_path.exists():
        return _empty_intent("NOT_DECLARED")
    if declaration_path.is_symlink():
        return _empty_intent(
            "INVALID", issues=["architecture declaration cannot be a symlink"]
        )
    try:
        resolved = declaration_path.resolve(strict=True)
        resolved.relative_to(repo)
        with resolved.open("rb") as handle:
            raw = handle.read(policy["limits"]["declaration_bytes"] + 1)
    except (OSError, ValueError):
        return _empty_intent(
            "INVALID", issues=["architecture declaration is unavailable"]
        )
    if len(raw) > policy["limits"]["declaration_bytes"]:
        return _empty_intent(
            "INVALID",
            issues=["architecture declaration exceeds configured limit"],
        )
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError):
        return _empty_intent(
            "INVALID", issues=["architecture declaration is malformed"]
        )
    schema_issues = _schema_errors(payload)
    if schema_issues:
        result = _empty_intent("INVALID", issues=schema_issues)
        result["evidence"] = [
            {
                "id": _DECLARATION_EVIDENCE_ID,
                "kind": "architecture_declaration",
                "locator": relative.as_posix(),
                "sha256": _digest(raw),
            }
        ]
        return result
    assert isinstance(payload, dict)
    issues = [
        *_bounded(payload, policy),
        *_unique_ids(payload),
        *_validate_vocabulary(payload, policy),
    ]
    evidence = [
        {
            "id": _DECLARATION_EVIDENCE_ID,
            "kind": "architecture_declaration",
            "locator": relative.as_posix(),
            "sha256": _digest(raw),
        }
    ]
    seen_evidence = {_DECLARATION_EVIDENCE_ID}
    for source in payload["evidence"][: policy["limits"]["evidence_files"]]:
        if source["id"] in seen_evidence:
            issues.append("architecture evidence ids must be unique")
            continue
        locator, source_raw, error = _safe_repo_file(
            repo,
            source["path"],
            max_bytes=policy["limits"]["evidence_bytes_each"],
        )
        if error:
            issues.append(f"architecture evidence {source['id']}: {error}")
            continue
        assert locator is not None and source_raw is not None
        seen_evidence.add(source["id"])
        evidence.append(
            {
                "id": source["id"],
                "kind": source["kind"],
                "locator": locator,
                "sha256": _digest(source_raw),
            }
        )
    issues.extend(_claim_evidence(payload, seen_evidence))
    issues.extend(_validate_references(payload, base_entity_ids))
    if issues:
        result = _empty_intent("INVALID", issues=list(dict.fromkeys(issues)))
        result["evidence"] = evidence
        return result
    return {
        "schema_version": "moth.architecture-intent.v1",
        "state": "DECLARED",
        "current": payload["current"],
        "desired": payload["desired"],
        "evidence": evidence,
        "issues": [],
        "warnings": [],
    }
