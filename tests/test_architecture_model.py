from pathlib import Path

import yaml

from moth.architecture_drift import build_architecture_drift
from moth.project_model import build_project_model


def _write_python_manifest(repo: Path) -> None:
    (repo / "pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                "name = 'sample'",
                "version = '1.0.0'",
                "requires-python = '>=3.12'",
                "[project.scripts]",
                "sample = 'sample.cli:main'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_architecture(repo: Path, payload: dict) -> None:
    target = repo / ".moth"
    target.mkdir()
    (target / "architecture.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )


def test_required_constraint_ignores_optional_fields_it_does_not_declare() -> None:
    current = {
        "complete": True,
        "entities": [
            {
                "id": "service:inspection",
                "kind": "service",
                "name": "Inspection",
                "responsibility": "Inspect repositories.",
                "locator": "src/moth/inspection.py",
                "evidence_ids": ["observed"],
            }
        ],
        "relations": [],
        "flows": [],
        "state_machines": [],
    }
    desired = {
        "complete": False,
        "entities": [
            {
                "id": "service:inspection",
                "kind": "service",
                "name": "Inspection",
                "responsibility": "Inspect repositories.",
                "expectation": "REQUIRED",
                "evidence_ids": ["declared"],
            }
        ],
        "relations": [],
        "flows": [],
        "state_machines": [],
    }

    drift = build_architecture_drift(current=current, desired=desired)

    assert drift["state"] == "CONFORMANT"
    assert drift["violation_ids"] == []


def test_project_model_keeps_undeclared_intent_honest(tmp_path: Path) -> None:
    _write_python_manifest(tmp_path)

    model = build_project_model(tmp_path)

    assert model["schema_version"] == "moth.project-model.v2"
    assert model["architecture"]["declaration_state"] == "NOT_DECLARED"
    assert model["architecture"]["current"]["state"] == "OBSERVED"
    assert model["flows"] == []
    assert model["state_machines"] == []
    assert model["architecture"]["desired"] == {
        "state": "NOT_DECLARED",
        "complete": False,
        "entities": [],
        "relations": [],
        "flows": [],
        "state_machines": [],
        "evidence_ids": [],
    }
    assert model["architecture"]["drift"] == {
        "state": "NOT_COMPUTED",
        "findings": [],
        "violation_ids": [],
        "unverifiable_ids": [],
        "conformant_ids": [],
    }


def test_declaration_adds_real_flows_states_and_evidence_backed_drift(
    tmp_path: Path,
) -> None:
    _write_python_manifest(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [
                {
                    "id": "architecture-doc",
                    "kind": "architecture_document",
                    "path": "docs/architecture.md",
                }
            ],
            "current": {
                "complete": True,
                "entities": [
                    {
                        "id": "service:inspection",
                        "kind": "service",
                        "name": "Inspection service",
                        "responsibility": "Build a portable inspection.",
                        "locator": "src/moth/inspection.py",
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
                "relations": [
                    {
                        "id": "relation:cli-inspection",
                        "kind": "calls",
                        "source_id": "python-console:sample",
                        "target_id": "service:inspection",
                        "label": "invokes",
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
                "flows": [
                    {
                        "id": "flow:inspect",
                        "name": "Inspect project",
                        "steps": [
                            {
                                "id": "step:request",
                                "entity_id": "python-console:sample",
                                "action": "receive request",
                                "from_state": "idle",
                                "to_state": "requested",
                            },
                            {
                                "id": "step:report",
                                "entity_id": "service:inspection",
                                "action": "build report",
                                "from_state": "requested",
                                "to_state": "reported",
                            },
                        ],
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
                "state_machines": [
                    {
                        "id": "state-machine:inspection",
                        "entity_id": "service:inspection",
                        "initial_state": "idle",
                        "states": ["idle", "requested", "reported"],
                        "transitions": [
                            {
                                "id": "transition:request",
                                "from_state": "idle",
                                "to_state": "requested",
                                "trigger": "inspect",
                            }
                        ],
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
            },
            "desired": {
                "complete": False,
                "entities": [
                    {
                        "id": "service:risk",
                        "kind": "service",
                        "name": "Risk service",
                        "responsibility": "Unify change evidence.",
                        "locator": "src/moth/change_safety.py",
                        "expectation": "REQUIRED",
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
                "relations": [
                    {
                        "id": "relation:inspection-risk",
                        "kind": "calls",
                        "source_id": "service:inspection",
                        "target_id": "service:risk",
                        "label": "assesses",
                        "expectation": "REQUIRED",
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
                "flows": [],
                "state_machines": [],
            },
        },
    )

    model = build_project_model(tmp_path)
    architecture = model["architecture"]

    assert model["verdict"] == "PASS"
    assert architecture["declaration_state"] == "DECLARED"
    assert architecture["current"]["state"] == "OBSERVED"
    assert [item["id"] for item in model["flows"]] == ["flow:inspect"]
    assert [item["id"] for item in model["state_machines"]] == [
        "state-machine:inspection"
    ]
    assert architecture["desired"]["state"] == "DECLARED"
    assert architecture["drift"]["state"] == "DRIFT_DETECTED"
    assert architecture["drift"]["violation_ids"] == [
        "entity:service:risk",
        "relation:relation:inspection-risk",
    ]
    assert all(
        item["declaration_evidence_ids"]
        for item in architecture["drift"]["findings"]
    )
    assert "architecture-doc" in {
        item["id"] for item in model["evidence"]
    }
    assert str(tmp_path) not in repr(model)


def test_invalid_architecture_reference_fails_closed(tmp_path: Path) -> None:
    _write_python_manifest(tmp_path)
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [],
            "current": {
                "complete": False,
                "entities": [],
                "relations": [
                    {
                        "id": "relation:missing",
                        "kind": "calls",
                        "source_id": "entity:missing",
                        "target_id": "python",
                        "label": "invalid",
                        "evidence_ids": [],
                    }
                ],
                "flows": [],
                "state_machines": [],
            },
            "desired": {
                "complete": False,
                "entities": [],
                "relations": [],
                "flows": [],
                "state_machines": [],
            },
        },
    )

    model = build_project_model(tmp_path)

    assert model["verdict"] == "FAIL"
    assert model["architecture"]["declaration_state"] == "INVALID"
    assert model["relations"] == [
        item
        for item in model["relations"]
        if item["kind"] == "uses_runtime"
    ]
    assert any(
        "unknown entity" in issue for issue in model["coverage"]["issues"]
    )


def test_architecture_evidence_cannot_escape_repository(tmp_path: Path) -> None:
    _write_python_manifest(tmp_path)
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [
                {
                    "id": "escape",
                    "kind": "architecture_document",
                    "path": "../secret.md",
                }
            ],
            "current": {
                "complete": False,
                "entities": [],
                "relations": [],
                "flows": [],
                "state_machines": [],
            },
            "desired": {
                "complete": False,
                "entities": [],
                "relations": [],
                "flows": [],
                "state_machines": [],
            },
        },
    )

    model = build_project_model(tmp_path)

    assert model["verdict"] == "FAIL"
    assert model["architecture"]["declaration_state"] == "INVALID"
    assert all("secret.md" not in item["locator"] for item in model["evidence"])


def test_incomplete_observation_cannot_claim_absent_constraint_result() -> None:
    empty_current = {
        "complete": False,
        "entities": [],
        "relations": [],
        "flows": [],
        "state_machines": [],
    }
    required = {
        "id": "service:missing",
        "kind": "service",
        "name": "Missing",
        "responsibility": "Required service.",
        "expectation": "REQUIRED",
        "evidence_ids": ["intent"],
    }
    forbidden = {
        **required,
        "id": "service:forbidden",
        "expectation": "FORBIDDEN",
    }

    result = build_architecture_drift(
        current=empty_current,
        desired={
            "entities": [required, forbidden],
            "relations": [],
            "flows": [],
            "state_machines": [],
        },
    )

    assert result["state"] == "UNVERIFIABLE"
    assert result["violation_ids"] == []
    assert result["unverifiable_ids"] == [
        "entity:service:forbidden",
        "entity:service:missing",
    ]


def test_observed_forbidden_subject_is_confirmed_drift_even_if_incomplete() -> None:
    forbidden = {
        "id": "service:forbidden",
        "kind": "service",
        "name": "Forbidden",
        "responsibility": "Must not exist.",
        "expectation": "FORBIDDEN",
        "evidence_ids": ["intent"],
    }
    observed = {
        key: value for key, value in forbidden.items() if key != "expectation"
    }
    observed["evidence_ids"] = ["observation"]

    result = build_architecture_drift(
        current={
            "complete": False,
            "entities": [observed],
            "relations": [],
            "flows": [],
            "state_machines": [],
        },
        desired={
            "entities": [forbidden],
            "relations": [],
            "flows": [],
            "state_machines": [],
        },
    )

    assert result["state"] == "DRIFT_DETECTED"
    assert result["violation_ids"] == ["entity:service:forbidden"]
    assert result["findings"][0]["observation_evidence_ids"] == ["observation"]
