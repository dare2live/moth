"""Bounded, evidence-first change-safety assessment.

This module observes existing Moth impact and gate engines, then applies a
small packaged policy.  It never executes affected tests itself: CodeGraph's
``affectedTests`` are planning evidence until a repository-owned gate proves
execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator

import yaml
from jsonschema import Draft202012Validator

from moth.gates import run_gate
from moth.report import build_affected_report


SCHEMA_VERSION = "moth.change-safety.v1"
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_GATE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@lru_cache(maxsize=1)
def load_change_safety_policy() -> dict[str, Any]:
    payload = yaml.safe_load(
        files("moth")
        .joinpath("change_safety_policy.yaml")
        .read_text(encoding="utf-8")
    )
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "moth_change_safety_policy"
    ):
        raise ValueError("change safety policy must be a moth_change_safety_policy mapping")
    bounds = payload.get("bounds")
    phases = payload.get("phases")
    rules = payload.get("rules")
    vocabulary = payload.get("vocabulary")
    repository = payload.get("repository")
    if not all(
        isinstance(item, dict)
        for item in (bounds, phases, rules, vocabulary, repository)
    ):
        raise ValueError("change safety policy sections must be mappings")
    config_path = _safe_locator(
        repository.get("config_path"),
        max_length=512,
    )
    max_config_bytes = repository.get("max_config_bytes")
    if config_path is None or not isinstance(max_config_bytes, int):
        raise ValueError("change safety repository policy is invalid")
    for key in (
        "max_changed_files",
        "max_path_length",
        "max_affected_tests",
        "max_entities",
        "max_heuristics",
        "max_gates",
    ):
        value = bounds.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 10_000:
            raise ValueError(f"change safety bound {key} must be between 1 and 10000")
    if set(phases) != {"pre_change", "during_change", "post_change"}:
        raise ValueError("change safety policy must define exactly three phases")
    verdicts = set(_strings(vocabulary.get("verdicts")))
    for phase, spec in phases.items():
        if not isinstance(spec, dict) or spec.get("default_verdict") not in verdicts:
            raise ValueError(f"change safety phase {phase} has an invalid default verdict")
        for requirement in (
            "require_scope",
            "require_fresh_codegraph",
            "require_affected_analysis",
            "require_passing_gate",
        ):
            if not isinstance(spec.get(requirement), bool):
                raise ValueError(f"change safety phase {phase} {requirement} must be boolean")
    if rules.get("heuristic_maximum_impact") != "CAUTION":
        raise ValueError("heuristic evidence maximum impact must remain CAUTION")
    risk_order = _strings(rules.get("risk_order"))
    if not risk_order or len(risk_order) != len(set(risk_order)):
        raise ValueError("change safety risk order must be present and unique")
    return payload


def load_repo_change_safety(
    repo_path: str | Path,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load repository-owned mandatory gates from one conventional config."""

    resolved_policy = policy or load_change_safety_policy()
    repository = resolved_policy["repository"]
    repo = Path(repo_path).resolve()
    relative = Path(repository["config_path"])
    config = repo / relative
    empty = {
        "schema_version": "moth.change-safety-profile.v1",
        "state": "NOT_CONFIGURED",
        "phases": {
            phase: {"mandatory_gates": []}
            for phase in ("pre_change", "during_change", "post_change")
        },
    }
    if not config.exists():
        return empty
    if config.is_symlink():
        raise ValueError("change safety profile cannot be a symlink")
    try:
        resolved = config.resolve(strict=True)
        resolved.relative_to(repo)
        with resolved.open("rb") as handle:
            raw = handle.read(int(repository["max_config_bytes"]) + 1)
    except (OSError, ValueError):
        raise ValueError("change safety profile is unavailable") from None
    if len(raw) > int(repository["max_config_bytes"]):
        raise ValueError("change safety profile exceeds configured bound")
    try:
        payload = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeError, yaml.YAMLError):
        raise ValueError("change safety profile is malformed") from None
    schema = json.loads(
        files("moth.schemas")
        .joinpath("moth.change-safety-profile.schema.json")
        .read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise ValueError(
            "change safety profile schema: "
            + (
                ".".join(str(part) for part in errors[0].absolute_path)
                or "<root>"
            )
            + f": {errors[0].message}"
        )
    assert isinstance(payload, dict)
    return {**payload, "state": "CONFIGURED"}


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _canonical_digest(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _safe_locator(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > max_length:
        return None
    if "\x00" in value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return None
    normalized = path.as_posix()
    if normalized in {"", "."} or normalized.startswith("./"):
        return None
    return normalized


def _normalize_changed_files(values: Any, policy: dict[str, Any]) -> list[str]:
    if not isinstance(values, list):
        raise ValueError("changed files must be a list")
    bounds = policy["bounds"]
    if len(values) > int(bounds["max_changed_files"]):
        raise ValueError("changed file scope exceeds configured bound")
    normalized: list[str] = []
    for value in values:
        locator = _safe_locator(value, max_length=int(bounds["max_path_length"]))
        if locator is None:
            raise ValueError("changed files must use safe repository-relative paths")
        normalized.append(locator)
    return sorted(set(normalized))


def _iter_mappings_bounded(value: Any, *, limit: int) -> Iterator[dict[str, Any]]:
    pending: list[Any] = [value]
    visited = 0
    while pending and visited < limit:
        current = pending.pop()
        visited += 1
        if isinstance(current, dict):
            yield current
            pending.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            pending.extend(reversed(current))


def _exact_entity_associations(
    snapshot: dict[str, Any],
    changed_files: list[str],
    policy: dict[str, Any],
) -> dict[str, list[str]]:
    by_path = {path: [] for path in changed_files}
    bounds = policy["bounds"]
    project_model = _mapping(snapshot.get("project_model"))
    for item in _iter_mappings_bounded(
        project_model,
        limit=int(bounds["max_entities"]) * 8,
    ):
        entity_id = item.get("id")
        locator = _safe_locator(
            item.get("locator"),
            max_length=int(bounds["max_path_length"]),
        )
        if (
            isinstance(entity_id, str)
            and entity_id
            and locator in by_path
            and entity_id not in by_path[locator]
        ):
            by_path[locator].append(entity_id)
    return {path: sorted(ids) for path, ids in by_path.items()}


def _add_observation(
    store: dict[str, dict[str, Any]],
    *,
    observation_kind: str,
    state: str,
    summary: str,
    locator: str | None = None,
    entity_ids: Iterable[str] = (),
    causal_claim: bool,
) -> str:
    seed = {
        "observation_kind": observation_kind,
        "state": state,
        "summary": summary,
        "locator": locator,
        "entity_ids": sorted(set(entity_ids)),
        "causal_claim": causal_claim,
    }
    evidence_id = f"change:{_canonical_digest(seed)[:20]}"
    store[evidence_id] = {"id": evidence_id, **seed}
    return evidence_id


def _affected_tests(
    affected_report: dict[str, Any],
    policy: dict[str, Any],
) -> list[str]:
    raw = _mapping(affected_report.get("codegraph_affected")).get("affectedTests")
    if not isinstance(raw, list):
        return []
    bounds = policy["bounds"]
    result: list[str] = []
    for item in raw[: int(bounds["max_affected_tests"])]:
        candidate: Any = item
        if isinstance(item, dict):
            candidate = item.get("locator") or item.get("path") or item.get("file")
        locator = _safe_locator(
            candidate,
            max_length=int(bounds["max_path_length"]),
        )
        if locator is not None:
            result.append(locator)
    return sorted(set(result))


def _coverage_complete(affected_report: dict[str, Any], policy: dict[str, Any]) -> bool:
    affected = _mapping(affected_report.get("codegraph_affected"))
    fields = _strings(policy["rules"].get("coverage_complete_fields"))
    return any(
        affected_report.get(field) is True or affected.get(field) is True
        for field in fields
    )


def _heuristic_rows(
    *,
    snapshot: dict[str, Any],
    affected_report: dict[str, Any],
    changed_files: list[str],
    policy: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Return exact ``(locator, risk_level, evidence_kind)`` rows only."""

    scoped = set(changed_files)
    bounds = policy["bounds"]
    rows: list[tuple[str, str, str]] = []

    complexity = _mapping(affected_report.get("complexity"))
    complexity_findings = complexity.get("findings")
    if isinstance(complexity_findings, list):
        for finding in complexity_findings:
            if len(rows) >= int(bounds["max_heuristics"]):
                break
            item = _mapping(finding)
            locator = _safe_locator(
                item.get("path"),
                max_length=int(bounds["max_path_length"]),
            )
            severity = str(item.get("severity") or "").lower()
            if locator in scoped and severity:
                rows.append((locator, severity, "complexity"))

    omen = _mapping(
        _mapping(_mapping(snapshot.get("tool_evidence")).get("tools")).get("omen")
    )
    if omen.get("scope") != "evidence_only":
        return rows
    raw_evidence = omen.get("evidence")
    if not isinstance(raw_evidence, list):
        return rows
    for evidence in raw_evidence:
        if len(rows) >= int(bounds["max_heuristics"]):
            break
        item = _mapping(evidence)
        kind = str(item.get("kind") or "")
        findings = item.get("findings")
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if len(rows) >= int(bounds["max_heuristics"]):
                break
            record = _mapping(finding)
            severity = str(
                record.get("severity") or record.get("risk_level") or ""
            ).lower()
            candidates: list[Any]
            if kind == "hotspot":
                candidates = [record.get("file")]
            elif kind == "changes" and isinstance(record.get("files_modified"), list):
                candidates = list(record["files_modified"])
            else:
                # Aggregate/diff heuristics have no exact path association.
                candidates = []
            for candidate in candidates:
                locator = _safe_locator(
                    candidate,
                    max_length=int(bounds["max_path_length"]),
                )
                if locator in scoped and severity:
                    rows.append((locator, severity, kind))
    return rows[: int(bounds["max_heuristics"])]


def _gate_summary(gate_results: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    sanitized: list[dict[str, Any]] = []
    for index, raw in enumerate(gate_results):
        gate = _mapping(raw)
        sanitized.append(
            {
                "name": str(gate.get("name") or f"gate-{index + 1}"),
                "state": "PASSED" if gate.get("go") is True else "FAILED",
                "pass": int(gate.get("pass") or 0),
                "fail": int(gate.get("fail") or 0),
                "error": int(gate.get("error") or 0),
            }
        )
    if not sanitized:
        return "NOT_RUN", sanitized
    if all(item["state"] == "PASSED" for item in sanitized):
        return "PASSED", sanitized
    return "FAILED", sanitized


def assess_change_safety(
    *,
    phase: str,
    snapshot: dict[str, Any],
    affected_report: dict[str, Any],
    gate_results: list[dict[str, Any]],
    baseline_digest: str | None = None,
) -> dict[str, Any]:
    """Assess observations without executing tools or tests."""

    policy = load_change_safety_policy()
    phases = policy["phases"]
    if phase not in phases:
        raise ValueError(f"unsupported change phase: {phase}")
    if not isinstance(snapshot, dict) or not isinstance(affected_report, dict):
        raise ValueError("snapshot and affected report must be mappings")
    if not isinstance(gate_results, list):
        raise ValueError("gate results must be a list")
    changed_files = _normalize_changed_files(
        affected_report.get("input_files", []),
        policy,
    )
    digest = baseline_digest or _canonical_digest(snapshot)
    if not isinstance(digest, str) or _HEX_DIGEST_RE.fullmatch(digest) is None:
        raise ValueError("baseline digest must be a lowercase sha256 hex digest")

    evidence: dict[str, dict[str, Any]] = {}
    entities = _exact_entity_associations(snapshot, changed_files, policy)
    associations = {
        path: {
            "path": path,
            "entity_ids": entities[path],
            "risk_levels": [],
            "evidence_kinds": ["changed_file"],
        }
        for path in changed_files
    }
    for path in changed_files:
        _add_observation(
            evidence,
            observation_kind="FACT",
            state="PRESENT",
            summary="file is in the explicit change scope",
            locator=path,
            entity_ids=entities[path],
            causal_claim=True,
        )

    codegraph = _mapping(snapshot.get("codegraph"))
    codegraph_fresh = (
        codegraph.get("verdict") == "PASS"
        and codegraph.get("state") == "UP_TO_DATE"
        and codegraph.get("index_up_to_date") is True
    )
    _add_observation(
        evidence,
        observation_kind="RUNTIME_RESULT",
        state="PASS" if codegraph_fresh else ("FAIL" if codegraph else "UNKNOWN"),
        summary="CodeGraph index freshness",
        causal_claim=True,
    )

    affected = _mapping(affected_report.get("codegraph_affected"))
    affected_passed = (
        affected_report.get("status") in {"PASS", "WARN"}
        and affected.get("verdict") == "PASS"
    )
    _add_observation(
        evidence,
        observation_kind="RUNTIME_RESULT",
        state="PASS" if affected_passed else "FAIL",
        summary="CodeGraph affected analysis",
        causal_claim=True,
    )

    planned_tests = _affected_tests(affected_report, policy)
    test_evidence_ids: list[str] = []
    for locator in planned_tests:
        test_evidence_ids.append(
            _add_observation(
                evidence,
                observation_kind="RUNTIME_RESULT",
                state="PRESENT",
                summary="CodeGraph identified an affected test; execution is only planned",
                locator=locator,
                causal_claim=False,
            )
        )
    test_state = (
        policy["rules"]["affected_test_states"]["planned"]
        if planned_tests
        else policy["rules"]["affected_test_states"]["absent"]
    )

    gate_state, public_gates = _gate_summary(gate_results)
    gate_evidence_ids: list[str] = []
    for gate in public_gates:
        gate_evidence_ids.append(
            _add_observation(
                evidence,
                observation_kind="RUNTIME_RESULT",
                state="PASS" if gate["state"] == "PASSED" else "FAIL",
                summary=f"repository-owned gate {gate['name']} {gate['state'].lower()}",
                locator=f"gate:{gate['name']}",
                causal_claim=True,
            )
        )
    if not public_gates:
        gate_evidence_ids.append(
            _add_observation(
                evidence,
                observation_kind="RUNTIME_RESULT",
                state="NOT_CHECKED",
                summary="no repository-owned gate was executed",
                causal_claim=True,
            )
        )

    risk_order = _strings(policy["rules"].get("risk_order"))
    risk_rank = {level: index for index, level in enumerate(risk_order)}
    heuristic_evidence_ids: list[str] = []
    for locator, level, evidence_kind in _heuristic_rows(
        snapshot=snapshot,
        affected_report=affected_report,
        changed_files=changed_files,
        policy=policy,
    ):
        if level not in risk_rank:
            continue
        association = associations[locator]
        if level not in association["risk_levels"]:
            association["risk_levels"].append(level)
        if evidence_kind not in association["evidence_kinds"]:
            association["evidence_kinds"].append(evidence_kind)
        heuristic_evidence_ids.append(
            _add_observation(
                evidence,
                observation_kind="HEURISTIC",
                state="PRESENT",
                summary=f"{evidence_kind} reported {level} heuristic evidence",
                locator=locator,
                entity_ids=entities[locator],
                causal_claim=False,
            )
        )
    for association in associations.values():
        association["risk_levels"].sort(key=lambda item: risk_rank.get(item, -1))
        association["evidence_kinds"].sort()
    observed_levels = [
        level
        for association in associations.values()
        for level in association["risk_levels"]
    ]
    highest_level = (
        max(observed_levels, key=lambda item: risk_rank.get(item, -1))
        if observed_levels
        else None
    )

    phase_policy = phases[phase]
    missing_requirements: list[str] = []
    no_go_reasons: list[str] = []
    caution_reasons: list[str] = []
    if phase_policy["require_scope"] and not changed_files:
        missing_requirements.append("change_scope")
        no_go_reasons.append("missing_change_scope")
    if phase_policy["require_fresh_codegraph"] and not codegraph_fresh:
        missing_requirements.append("fresh_codegraph")
        no_go_reasons.append("stale_or_unknown_codegraph")
    if phase_policy["require_affected_analysis"] and not affected_passed:
        missing_requirements.append("affected_analysis")
        no_go_reasons.append("affected_analysis_failed")
    if phase_policy["require_passing_gate"] and gate_state != "PASSED":
        missing_requirements.append("passing_gate_evidence")
        no_go_reasons.append("passing_gate_evidence_missing")
    if (
        policy["rules"].get("provided_gate_failure_is_no_go") is True
        and gate_state == "FAILED"
    ):
        no_go_reasons.append("repository_gate_failed")
    if not planned_tests and not _coverage_complete(affected_report, policy):
        missing_requirements.append("affected_test_coverage")
        caution_reasons.append("affected_test_coverage_unknown")
    if highest_level in set(
        _strings(policy["rules"].get("heuristic_caution_levels"))
    ):
        caution_reasons.append("heuristic_risk_observed")

    if no_go_reasons:
        verdict = "NO_GO"
    elif phase_policy["default_verdict"] == "CAUTION" or caution_reasons:
        verdict = "CAUTION"
    else:
        verdict = "GO"
    reasons = sorted(set(no_go_reasons + caution_reasons))

    result = {
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "baseline_digest": digest,
        "verdict": verdict,
        "reasons": reasons,
        "missing_requirements": sorted(set(missing_requirements)),
        "scope": {
            "state": "PRESENT" if changed_files else "UNKNOWN",
            "changed_files": changed_files,
        },
        "test_evidence": {
            "state": test_state,
            "affected_tests": planned_tests,
            "evidence_ids": sorted(test_evidence_ids),
        },
        "gate_evidence": {
            "state": gate_state,
            "gates": public_gates,
            "evidence_ids": sorted(gate_evidence_ids),
        },
        "risk": {
            "highest_level": highest_level,
            "causal_root": None,
            "evidence_ids": sorted(heuristic_evidence_ids),
        },
        "associations": [associations[path] for path in sorted(associations)],
        "evidence": dict(sorted(evidence.items())),
    }
    result["evidence_ids"] = sorted(result["evidence"])
    schema_errors = validate_change_safety_schema(result)
    if schema_errors:
        raise ValueError(
            "change safety result violates public schema: " + "; ".join(schema_errors)
        )
    return result


def _gate_result_from_error(name: str, exc: Exception) -> dict[str, Any]:
    return {
        "name": name,
        "go": False,
        "pass": 0,
        "fail": 0,
        "error": 1,
        "issues": [f"gate execution failed: {type(exc).__name__}"],
    }


def build_change_safety(
    profile: Any,
    *,
    snapshot: dict[str, Any],
    changed_files: list[str],
    phase: str,
    gate_names: list[str] | None = None,
    depth: int = 5,
    test_filter: str | None = None,
    baseline_digest: str | None = None,
    execute_gates: bool = True,
) -> dict[str, Any]:
    """Collect existing impact/gate evidence and assess it in one bounded call."""

    policy = load_change_safety_policy()
    normalized_files = _normalize_changed_files(changed_files, policy)
    repo_config = load_repo_change_safety(profile.repo_path, policy=policy)
    mandatory = _strings(
        _mapping(_mapping(repo_config.get("phases")).get(phase)).get(
            "mandatory_gates"
        )
    )
    names = sorted(set([*(gate_names or []), *mandatory]))
    if not isinstance(names, list) or len(names) > int(policy["bounds"]["max_gates"]):
        raise ValueError("gate names must be a bounded list")
    normalized_names: list[str] = []
    for name in names:
        if not isinstance(name, str) or _GATE_NAME_RE.fullmatch(name) is None:
            raise ValueError("gate names must be safe identifiers")
        normalized_names.append(name)
    affected_report = build_affected_report(
        profile,
        normalized_files,
        depth=depth,
        test_filter=test_filter,
    )
    gate_results: list[dict[str, Any]] = []
    for name in normalized_names if execute_gates else []:
        try:
            result = run_gate(profile.repo_path, name)
        except Exception as exc:  # Gate evidence must fail closed, not crash inspection.
            result = _gate_result_from_error(name, exc)
        else:
            result = {**result, "name": result.get("name") or name}
        gate_results.append(result)
    return assess_change_safety(
        phase=phase,
        snapshot=snapshot,
        affected_report=affected_report,
        gate_results=gate_results,
        baseline_digest=baseline_digest,
    )


def validate_change_safety_schema(payload: dict[str, Any]) -> list[str]:
    schema = json.loads(
        files("moth.schemas")
        .joinpath("moth.change-safety.schema.json")
        .read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    return [
        (
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: "
            f"{error.message}"
        )
        for error in errors
    ]
