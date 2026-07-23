from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from moth.change_safety import (
    assess_change_safety,
    build_change_safety,
    validate_change_safety_schema,
)


def _snapshot(*, fresh: bool = True, risk_level: str | None = None) -> dict:
    evidence = []
    if risk_level is not None:
        evidence = [
            {
                "kind": "hotspot",
                "state": "COMPLETE",
                "findings": [
                    {
                        "file": "src/moth/inspection.py",
                        "severity": risk_level,
                        "score": 0.9,
                    }
                ],
            }
        ]
    return {
        "codegraph": {
            "verdict": "PASS" if fresh else "WARN",
            "state": "UP_TO_DATE" if fresh else "STALE",
            "index_up_to_date": fresh,
        },
        "project_model": {
            "architecture": {
                "current": {
                    "entities": [
                        {
                            "id": "service:inspection",
                            "kind": "service",
                            "name": "Inspection",
                            "responsibility": "Inspect",
                            "locator": "src/moth/inspection.py",
                            "evidence_ids": [],
                        }
                    ]
                }
            }
        },
        "tool_evidence": {
            "tools": {
                "omen": {
                    "state": "COMPLETE",
                    "scope": "evidence_only",
                    "evidence": evidence,
                }
            }
        },
    }


def _affected(*, tests: list[str] | None = None, status: str = "PASS") -> dict:
    return {
        "status": status,
        "input_files": ["src/moth/inspection.py"],
        "codegraph_affected": {
            "verdict": status,
            "affectedTests": (
                ["tests/test_inspection.py"] if tests is None else tests
            ),
            "totalDependentsTraversed": 7,
            "issues": [],
        },
        "complexity": {
            "verdict": "PASS",
            "summary": {"finding_count": 0},
            "findings": [],
        },
        "issues": [],
        "warnings": [],
    }


def test_pre_change_can_go_only_on_fresh_impact_evidence() -> None:
    result = assess_change_safety(
        phase="pre_change",
        snapshot=_snapshot(),
        affected_report=_affected(),
        gate_results=[],
    )

    assert result["verdict"] == "GO"
    assert result["test_evidence"]["state"] == "PLANNED"
    assert result["test_evidence"]["affected_tests"] == [
        "tests/test_inspection.py"
    ]
    assert result["gate_evidence"]["state"] == "NOT_RUN"
    assert result["associations"] == [
        {
            "path": "src/moth/inspection.py",
            "entity_ids": ["service:inspection"],
            "risk_levels": [],
            "evidence_kinds": ["changed_file"],
        }
    ]


def test_stale_codegraph_blocks_but_critical_heuristic_only_cautions() -> None:
    stale = assess_change_safety(
        phase="pre_change",
        snapshot=_snapshot(fresh=False),
        affected_report=_affected(),
        gate_results=[],
    )
    critical = assess_change_safety(
        phase="pre_change",
        snapshot=_snapshot(risk_level="critical"),
        affected_report=_affected(),
        gate_results=[],
    )

    assert stale["verdict"] == "NO_GO"
    assert "fresh_codegraph" in stale["missing_requirements"]
    assert critical["verdict"] == "CAUTION"
    assert critical["risk"]["highest_level"] == "critical"
    assert critical["associations"][0]["entity_ids"] == ["service:inspection"]
    assert "hotspot" in critical["associations"][0]["evidence_kinds"]
    heuristic = next(
        item
        for item in critical["evidence"].values()
        if item["observation_kind"] == "HEURISTIC"
    )
    assert heuristic["causal_claim"] is False


def test_post_change_never_treats_affected_tests_as_executed() -> None:
    no_gates = assess_change_safety(
        phase="post_change",
        snapshot=_snapshot(),
        affected_report=_affected(),
        gate_results=[],
    )
    passed = assess_change_safety(
        phase="post_change",
        snapshot=_snapshot(),
        affected_report=_affected(),
        gate_results=[{"name": "release", "go": True, "fail": 0, "error": 0}],
    )
    failed = assess_change_safety(
        phase="post_change",
        snapshot=_snapshot(),
        affected_report=_affected(),
        gate_results=[{"name": "release", "go": False, "fail": 1, "error": 0}],
    )

    assert no_gates["verdict"] == "NO_GO"
    assert no_gates["test_evidence"]["state"] == "PLANNED"
    assert "passing_gate_evidence" in no_gates["missing_requirements"]
    assert passed["verdict"] == "GO"
    assert passed["gate_evidence"]["state"] == "PASSED"
    assert failed["verdict"] == "NO_GO"
    assert failed["gate_evidence"]["state"] == "FAILED"


def test_during_change_is_caution_not_release_green() -> None:
    result = assess_change_safety(
        phase="during_change",
        snapshot=_snapshot(),
        affected_report=_affected(),
        gate_results=[],
    )

    assert result["verdict"] == "CAUTION"


def test_pre_change_without_scope_or_affected_test_coverage_is_not_green() -> None:
    no_scope = assess_change_safety(
        phase="pre_change",
        snapshot=_snapshot(),
        affected_report={**_affected(), "input_files": []},
        gate_results=[],
    )
    unknown_coverage = assess_change_safety(
        phase="pre_change",
        snapshot=_snapshot(),
        affected_report=_affected(tests=[]),
        gate_results=[],
    )

    assert no_scope["verdict"] == "NO_GO"
    assert "change_scope" in no_scope["missing_requirements"]
    assert unknown_coverage["verdict"] == "CAUTION"
    assert unknown_coverage["test_evidence"]["state"] == "NOT_CHECKED"
    assert "affected_test_coverage" in unknown_coverage["missing_requirements"]


def test_only_exact_safe_repo_relative_locators_are_associated() -> None:
    snapshot = _snapshot(risk_level="high")
    snapshot["project_model"]["architecture"]["current"]["entities"].extend(
        [
            {
                "id": "service:fuzzy",
                "locator": "src/moth/inspection.py.old",
            },
            {
                "id": "service:outside",
                "locator": "../src/moth/inspection.py",
            },
        ]
    )
    snapshot["tool_evidence"]["tools"]["omen"]["evidence"][0]["findings"].extend(
        [
            {"file": "src/moth/inspection.py.old", "severity": "critical"},
            {"file": "/Users/private/inspection.py", "severity": "critical"},
        ]
    )

    result = assess_change_safety(
        phase="pre_change",
        snapshot=snapshot,
        affected_report=_affected(),
        gate_results=[],
    )

    assert result["associations"] == [
        {
            "path": "src/moth/inspection.py",
            "entity_ids": ["service:inspection"],
            "risk_levels": ["high"],
            "evidence_kinds": ["changed_file", "hotspot"],
        }
    ]
    serialized = str(result)
    assert "/Users/private" not in serialized
    assert "service:fuzzy" not in serialized


def test_contract_has_ids_baseline_digest_and_valid_schema() -> None:
    result = assess_change_safety(
        phase="pre_change",
        snapshot=_snapshot(),
        affected_report=_affected(),
        gate_results=[],
    )

    assert result["schema_version"] == "moth.change-safety.v1"
    assert len(result["baseline_digest"]) == 64
    assert result["evidence_ids"] == sorted(result["evidence"])
    assert validate_change_safety_schema(result) == []
    for observation in result["evidence"].values():
        assert observation["state"] in {
            "PRESENT",
            "PASS",
            "FAIL",
            "UNKNOWN",
            "NOT_CHECKED",
            "UNAVAILABLE",
            "ERROR",
        }


def test_changed_path_validation_is_bounded_and_fail_closed() -> None:
    with pytest.raises(ValueError, match="repository-relative"):
        assess_change_safety(
            phase="pre_change",
            snapshot=_snapshot(),
            affected_report={
                **_affected(),
                "input_files": ["../outside.py"],
            },
            gate_results=[],
        )


def test_build_change_safety_reuses_existing_affected_and_repo_gate_modules(
    monkeypatch, tmp_path: Path
) -> None:
    profile = SimpleNamespace(repo_path=tmp_path, codegraph_root=tmp_path)
    calls: dict[str, object] = {}

    def fake_affected(profile_arg, files, *, depth, test_filter):
        calls["affected"] = (profile_arg, files, depth, test_filter)
        return _affected()

    def fake_gate(repo, name):
        calls.setdefault("gates", []).append((repo, name))
        return {"go": True, "fail": 0, "error": 0}

    monkeypatch.setattr("moth.change_safety.build_affected_report", fake_affected)
    monkeypatch.setattr("moth.change_safety.run_gate", fake_gate)

    result = build_change_safety(
        profile,
        snapshot=_snapshot(),
        changed_files=["src/moth/inspection.py"],
        phase="post_change",
        gate_names=["release"],
        depth=3,
        test_filter="tests/**",
    )

    assert result["verdict"] == "GO"
    assert calls["affected"] == (
        profile,
        ["src/moth/inspection.py"],
        3,
        "tests/**",
    )
    assert calls["gates"] == [(tmp_path, "release")]


def test_repo_owned_mandatory_gates_are_additive_and_plan_only_never_runs_them(
    monkeypatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / ".moth"
    config_dir.mkdir()
    (config_dir / "change-safety.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "moth.change-safety-profile.v1",
                "phases": {
                    "pre_change": {"mandatory_gates": []},
                    "during_change": {"mandatory_gates": []},
                    "post_change": {"mandatory_gates": ["mandatory"]},
                },
            }
        ),
        encoding="utf-8",
    )
    profile = SimpleNamespace(repo_path=tmp_path, codegraph_root=tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(
        "moth.change_safety.build_affected_report",
        lambda *_args, **_kwargs: _affected(),
    )

    def fake_gate(_repo, name):
        calls.append(name)
        return {"go": True, "pass": 1, "fail": 0, "error": 0}

    monkeypatch.setattr("moth.change_safety.run_gate", fake_gate)

    executed = build_change_safety(
        profile,
        snapshot=_snapshot(),
        changed_files=["src/moth/inspection.py"],
        phase="post_change",
        gate_names=["extra"],
    )
    planned = build_change_safety(
        profile,
        snapshot=_snapshot(),
        changed_files=["src/moth/inspection.py"],
        phase="post_change",
        gate_names=["extra"],
        execute_gates=False,
    )

    assert calls == ["extra", "mandatory"]
    assert executed["verdict"] == "GO"
    assert [item["name"] for item in executed["gate_evidence"]["gates"]] == [
        "extra",
        "mandatory",
    ]
    assert planned["verdict"] == "NO_GO"
    assert planned["gate_evidence"]["state"] == "NOT_RUN"
