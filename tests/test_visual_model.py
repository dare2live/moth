import json

from moth.visual_model import build_visual_model


def inspection_fixture() -> dict:
    digest = "sha256:" + "a" * 64
    return {
        "schema_version": "moth.inspection.v1",
        "status": "NEEDS_EXECUTOR",
        "project_health": "WARN",
        "context_readiness": "BLOCKED",
        "snapshot": {
            "status": "WARN",
            "issues": ["codegraph index is stale"],
            "warnings": ["python runtime coverage partial"],
            "dirty_worktree_count": 3,
            "project_model": {
                "schema_version": "moth.project-model.v1",
                "verdict": "WARN",
                "project": {
                    "id": "python:sample",
                    "name": "sample",
                    "version": "2.0.0",
                    "description": "Evidence-backed sample.",
                    "evidence_ids": ["manifest:pyproject.toml"],
                },
                "applications": [
                    {
                        "id": "python-console:sample",
                        "name": "sample",
                        "kind": "application",
                        "subtype": "python_console_script",
                        "entrypoint": "sample.cli:main",
                        "runtime_id": "python",
                        "evidence_ids": ["manifest:pyproject.toml"],
                    }
                ],
                "runtimes": [
                    {
                        "id": "python",
                        "kind": "runtime",
                        "constraint": ">=3.12",
                        "dependencies": ["PyYAML>=6"],
                        "evidence_ids": ["manifest:pyproject.toml"],
                    }
                ],
                "modules": [],
                "evidence": [
                    {
                        "id": "manifest:pyproject.toml",
                        "kind": "manifest",
                        "locator": "pyproject.toml",
                        "sha256": digest,
                    }
                ],
                "coverage": {
                    "detectors": [{"id": "python-project", "state": "DETECTED"}],
                    "issues": [],
                    "warnings": ["python runtime coverage partial"],
                },
            },
            "codegraph": {
                "verdict": "WARN",
                "state": "STALE",
                "index_up_to_date": False,
                "index_statistics": {"files": 12, "nodes": 42, "edges": 60},
            },
            "complexity": {
                "verdict": "PASS",
                "summary": {"finding_count": 2, "high_count": 1},
                "diff": {"status": "baseline_unavailable"},
            },
            "coupling": {"verdict": "PASS", "fail_count": 0, "warn_count": 1},
            "import_cycles": {"verdict": "PASS", "new_count": 0},
            "tool_evidence": {
                "tools": {
                    "omen": {
                        "state": "COMPLETE",
                        "compatible": True,
                        "compatibility_basis": "runtime_contract_probe",
                    }
                }
            },
            "assertions": {"verdict": "NONE", "totals": {}},
        },
        "orchestration": {
            "decision_context": {
                "context_readiness": "BLOCKED",
                "ordered_guidance_sources": ["mio", "architect-controller"],
                "missing_required_sources": ["mio", "architect-controller"],
            }
        },
    }


def test_visual_document_has_global_references_and_six_configured_layers() -> None:
    model = build_visual_model(inspection_fixture())

    assert model["schema_version"] == "moth.visual-document.v1"
    assert model["identity"]["name"] == "sample"
    assert list(model["entities"]) == sorted(model["entities"])
    assert [layer["id"] for layer in model["layers"]] == [
        "overview",
        "architecture",
        "stack",
        "flows",
        "code",
        "evidence",
    ]
    known_entities = set(model["entities"])
    known_findings = set(model["findings"])
    known_evidence = set(model["evidence"])
    for layer in model["layers"]:
        assert set(layer["entity_ids"]) <= known_entities
        assert set(layer["finding_ids"]) <= known_findings
        assert set(layer["evidence_ids"]) <= known_evidence


def test_architecture_separates_observed_from_undeclared_intent() -> None:
    model = build_visual_model(inspection_fixture())

    assert model["architecture"]["as_is"]["state"] == "OBSERVED"
    assert model["architecture"]["as_is"]["entity_ids"]
    assert model["architecture"]["to_be"] == {
        "state": "NOT_DECLARED",
        "entity_ids": [],
        "relation_ids": [],
        "evidence_ids": [],
        "omitted": {"entities": 0, "relations": 0},
    }
    assert model["architecture"]["drift"] == []
    assert model["architecture"]["summary"] == {
        "state": "NOT_DECLARED",
        "counts": {"CONFORMANT": 0, "VIOLATION": 0, "UNVERIFIABLE": 0},
    }


def test_home_actions_are_bounded_and_each_traces_to_evidence() -> None:
    model = build_visual_model(inspection_fixture())

    assert len(model["home"]["priority_finding_ids"]) <= 5
    assert len(model["home"]["avoid_action_ids"]) <= 5
    assert model["home"]["priority_finding_ids"]
    assert model["home"]["avoid_action_ids"]
    for finding_id in model["home"]["priority_finding_ids"]:
        finding = model["findings"][finding_id]
        assert finding["evidence_ids"]
        assert set(finding["evidence_ids"]) <= set(model["evidence"])
    for action_id in model["home"]["avoid_action_ids"]:
        action = model["actions"][action_id]
        assert action["basis_finding_id"] in model["findings"]
        assert action["evidence_ids"]


def test_clean_input_does_not_invent_priority_or_avoid_actions() -> None:
    clean = inspection_fixture()
    clean["status"] = "PASS"
    clean["project_health"] = "PASS"
    clean["context_readiness"] = "READY"
    clean["snapshot"]["status"] = "PASS"
    clean["snapshot"]["issues"] = []
    clean["snapshot"]["warnings"] = []
    clean["snapshot"]["dirty_worktree_count"] = 0
    clean["snapshot"]["codegraph"]["index_up_to_date"] = True
    clean["snapshot"]["codegraph"]["state"] = "UP_TO_DATE"
    clean["snapshot"]["complexity"]["summary"]["high_count"] = 0
    clean["snapshot"]["project_model"]["coverage"]["warnings"] = []
    clean["orchestration"]["decision_context"]["context_readiness"] = "READY"

    model = build_visual_model(clean)

    assert model["home"]["priority_finding_ids"] == []
    assert model["home"]["avoid_action_ids"] == []
    assert model["status"]["evidence_ids"]
    assert set(model["status"]["evidence_ids"]) <= set(model["evidence"])


def test_duplicate_snapshot_and_coverage_warning_is_shown_once() -> None:
    model = build_visual_model(inspection_fixture())

    matches = [
        finding
        for finding in model["findings"].values()
        if finding["why"] == "python runtime coverage partial"
    ]

    assert len(matches) == 1
    assert matches[0]["title"] == "检查覆盖仍不完整"


def test_missing_code_payloads_do_not_claim_code_layer_availability() -> None:
    inspection = {
        "status": "UNKNOWN",
        "project_health": "UNKNOWN",
        "context_readiness": "UNKNOWN",
        "snapshot": {},
    }

    model = build_visual_model(inspection)
    code_layer = next(layer for layer in model["layers"] if layer["id"] == "code")

    assert code_layer["availability"] == "PARTIAL"
    assert code_layer["entity_ids"] == []


def test_visual_document_is_deterministic_and_has_three_viewpoint_lenses() -> None:
    inspection = inspection_fixture()

    first = build_visual_model(inspection)
    second = build_visual_model(json.loads(json.dumps(inspection)))

    assert first == second
    assert [item["id"] for item in first["navigation"]["viewpoints"]] == [
        "product",
        "system",
        "risk",
    ]
    for viewpoint in first["navigation"]["viewpoints"]:
        assert len(viewpoint["finding_ids"]) == len(set(viewpoint["finding_ids"]))
        assert all(
            viewpoint["id"] in first["findings"][finding_id]["viewpoint_ids"]
            for finding_id in viewpoint["finding_ids"]
        )


def test_technologies_and_project_documents_use_learning_layers() -> None:
    inspection = inspection_fixture()
    project_model = inspection["snapshot"]["project_model"]
    project_model["modules"] = [
        {
            "id": "technology:duckdb",
            "kind": "technology",
            "name": "DuckDB",
            "subtype": "data",
            "evidence_ids": ["manifest:pyproject.toml"],
        }
    ]
    project_model["evidence"].append(
        {
            "id": "profile:overview",
            "kind": "project_document",
            "locator": "docs/overview.md",
            "sha256": "sha256:" + "b" * 64,
        }
    )

    model = build_visual_model(inspection)
    architecture = next(layer for layer in model["layers"] if layer["id"] == "architecture")
    stack = next(layer for layer in model["layers"] if layer["id"] == "stack")
    evidence = next(layer for layer in model["layers"] if layer["id"] == "evidence")

    assert "technology:duckdb" not in architecture["entity_ids"]
    assert "technology:duckdb" in stack["entity_ids"]
    assert "document:profile:overview" in evidence["entity_ids"]


def test_visual_document_bounds_architecture_refs_for_large_projects() -> None:
    inspection = inspection_fixture()
    template = inspection["snapshot"]["project_model"]["applications"][0]
    inspection["snapshot"]["project_model"]["applications"] = [
        {
            **template,
            "id": f"application:{index}",
            "name": f"application-{index}",
        }
        for index in range(10_000)
    ]

    model = build_visual_model(inspection)

    assert len(model["architecture"]["as_is"]["entity_ids"]) == 80
    assert model["architecture"]["as_is"]["omitted"]["entities"] == 9_920


def test_application_entrypoint_does_not_claim_business_flow_coverage() -> None:
    model = build_visual_model(inspection_fixture())
    flow_layer = next(layer for layer in model["layers"] if layer["id"] == "flows")

    assert flow_layer["availability"] == "PARTIAL"
    assert flow_layer["entity_ids"] == []
    assert flow_layer["relation_ids"] == []


def test_invalid_desired_architecture_cannot_claim_declared_state() -> None:
    inspection = inspection_fixture()
    inspection["snapshot"]["desired_architecture"] = {
        "entity_ids": ["entity:missing"],
        "relation_ids": ["relation:missing"],
        "evidence_ids": [],
    }

    model = build_visual_model(inspection)

    assert model["architecture"]["to_be"]["state"] == "NOT_DECLARED"
    assert model["architecture"]["to_be"]["entity_ids"] == []


def test_v2_topology_projects_real_flows_new_to_be_entities_and_drift() -> None:
    inspection = inspection_fixture()
    project_model = inspection["snapshot"]["project_model"]
    project_model.update(
        {
            "schema_version": "moth.project-model.v2",
            "entities": [
                {
                    "id": "python:sample",
                    "kind": "project",
                    "name": "sample",
                    "responsibility": "Sample project.",
                    "evidence_ids": ["manifest:pyproject.toml"],
                },
                {
                    "id": "service:inspection",
                    "kind": "service",
                    "name": "Inspection",
                    "responsibility": "Build inspections.",
                    "locator": "src/moth/inspection.py",
                    "evidence_ids": ["manifest:pyproject.toml"],
                },
            ],
            "relations": [],
            "flows": [
                {
                    "id": "flow:inspect",
                    "name": "Inspect",
                    "steps": [
                        {
                            "id": "step:start",
                            "entity_id": "service:inspection",
                            "action": "start",
                        },
                        {
                            "id": "step:finish",
                            "entity_id": "service:inspection",
                            "action": "finish",
                        },
                    ],
                    "evidence_ids": ["manifest:pyproject.toml"],
                }
            ],
            "state_machines": [],
            "architecture": {
                "declaration_state": "DECLARED",
                "current": {
                    "state": "OBSERVED",
                    "complete": True,
                    "entity_ids": ["python:sample", "service:inspection"],
                    "relation_ids": [],
                    "flow_ids": ["flow:inspect"],
                    "state_machine_ids": [],
                    "evidence_ids": ["manifest:pyproject.toml"],
                },
                "desired": {
                    "state": "DECLARED",
                    "complete": False,
                    "entities": [
                        {
                            "id": "service:risk",
                            "kind": "service",
                            "name": "Risk",
                            "responsibility": "Unify risk evidence.",
                            "locator": "src/moth/change_safety.py",
                            "expectation": "REQUIRED",
                            "evidence_ids": ["manifest:pyproject.toml"],
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
                            "evidence_ids": ["manifest:pyproject.toml"],
                        }
                    ],
                    "flows": [],
                    "state_machines": [],
                    "evidence_ids": ["manifest:pyproject.toml"],
                },
                "drift": {
                    "state": "DRIFT_DETECTED",
                    "findings": [
                        {
                            "id": "entity:service:risk",
                            "subject_id": "service:risk",
                            "subject_kind": "entity",
                            "expectation": "REQUIRED",
                            "status": "VIOLATION",
                            "reason": "required subject was not observed",
                            "declaration_evidence_ids": [
                                "manifest:pyproject.toml"
                            ],
                            "observation_evidence_ids": [],
                        }
                    ],
                    "violation_ids": ["entity:service:risk"],
                    "unverifiable_ids": [],
                    "conformant_ids": [],
                },
                "issues": [],
                "warnings": [],
            },
        }
    )

    model = build_visual_model(inspection)
    flow_layer = next(layer for layer in model["layers"] if layer["id"] == "flows")

    assert "flow:inspect" in model["entities"]
    assert flow_layer["availability"] == "AVAILABLE"
    assert flow_layer["entity_ids"] == ["flow:inspect"]
    assert model["entities"]["service:risk"]["status"] == "EXPECTED_REQUIRED"
    assert model["architecture"]["to_be"]["state"] == "DECLARED"
    assert model["architecture"]["to_be"]["entity_ids"] == ["service:risk"]
    assert model["architecture"]["to_be"]["relation_ids"] == [
        "relation:inspection-risk"
    ]
    assert model["architecture"]["drift"][0]["status"] == "VIOLATION"
    assert "architecture-drift:entity:service:risk" in model["findings"]


def test_change_safety_projects_exact_risk_path_without_claiming_cause() -> None:
    inspection = inspection_fixture()
    inspection["change_safety"] = {
        "phase": "pre_change",
        "verdict": "CAUTION",
        "reasons": ["heuristic_risk_observed"],
        "evidence_ids": ["change:risk"],
        "evidence": {
            "change:risk": {
                "id": "change:risk",
                "observation_kind": "HEURISTIC",
                "state": "PRESENT",
                "summary": "hotspot reported high heuristic evidence",
                "locator": "sample.cli:main",
                "entity_ids": ["python-console:sample"],
                "causal_claim": False,
            }
        },
        "associations": [
            {
                "path": "sample.cli:main",
                "entity_ids": ["python-console:sample"],
                "risk_levels": ["high"],
                "evidence_kinds": ["changed_file", "hotspot"],
            }
        ],
    }

    model = build_visual_model(inspection)

    assert model["entities"]["change:safety"]["status"] == "CAUTION"
    relation = model["relations"]["change-affects:1:python-console:sample"]
    assert relation["source_id"] == "change:safety"
    assert relation["target_id"] == "python-console:sample"
    assert model["findings"]["change-safety"]["severity"] == "medium"
    assert model["evidence"]["change:risk"]["kind"] == "HEURISTIC"
