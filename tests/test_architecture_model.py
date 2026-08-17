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


def _write_declared_sources(repo: Path, *relative_paths: str) -> None:
    """把声明里 current 段 locator 指到的文件真的建出来。

    current(当前结构)声明的是**已经存在**的东西, 所以它的 locator 必须指向真实文件 ——
    否则那是一条编造的架构。这条约束由 _validate_current_locators 执法, fixture 要么满足它,
    要么就是在测一个本就不该通过的声明。
    """
    for relative in relative_paths:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("", encoding="utf-8")


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
    _write_declared_sources(tmp_path, "src/moth/inspection.py")
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
    _write_declared_sources(tmp_path, "src/moth/inspection.py")
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
    _write_declared_sources(tmp_path, "src/moth/inspection.py")
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


def test_declared_and_detected_entities_are_told_apart(tmp_path: Path) -> None:
    """声明来的和检测来的必须分得开, 而且"当前结构"不能把一份手写 yaml 说成扫描结果。

    2026-08-17 实测: moth 自己 18 个实体里 15 个、13 条关系里 12 条只存在于
    .moth/architecture.yaml, 移走该文件后 as_is 只剩 3 实体 / 1 关系 —— 但界面上
    声明来的实体与检测来的实体标着**完全相同**的 OBSERVED, 区分不出来。
    """
    _write_python_manifest(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    _write_declared_sources(tmp_path, "src/moth/inspection.py")
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
                "complete": False,
                "entities": [
                    {
                        "id": "service:inspection",
                        "kind": "service",
                        "name": "Inspection service",
                        "responsibility": "Only this file says it exists.",
                        "locator": "src/moth/inspection.py",
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
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
    by_id = {item["id"]: item for item in model["entities"]}

    # 只在声明里出现的
    assert by_id["service:inspection"]["source"] == "DECLARED"
    # 检测器从 pyproject.toml 读出来的
    assert by_id["python:sample"]["source"] == "DETECTED"
    assert by_id["python-console:sample"]["source"] == "DETECTED"

    provenance = model["architecture"]["current"]["provenance"]
    assert provenance["declared"] == 1
    assert provenance["detected"] >= 2
    # 有检测器实际看到的东西, 所以 OBSERVED 名副其实
    assert model["architecture"]["current"]["state"] == "OBSERVED"


def test_architecture_built_only_from_a_declaration_does_not_claim_to_be_observed() -> None:
    """全靠声明拼出来的结构不叫"观察到的"。

    这是上一条的极端情形: 检测器一个实体都没产出(没有 pyproject.toml 之类的清单),
    结构 100% 来自人手写。此时说 OBSERVED 就是把"你告诉我的"说成"我看到的"。
    """
    from moth.architecture_model import _provenance_counts

    declared_entity = {"id": "service:x", "source": "DECLARED"}
    counts = _provenance_counts([declared_entity], [], [], [])
    assert counts == {"detected": 0, "declared": 1, "confirmed": 0}

    # flows 与 state_machines 无条件算声明 —— 没有任何检测器产出这两样
    counts = _provenance_counts([], [], [{"id": "flow:a"}], [{"id": "sm:a"}])
    assert counts["declared"] == 2
    assert counts["detected"] == 0


def test_current_locator_must_point_at_a_file_that_exists(tmp_path: Path) -> None:
    """声明当前结构时写的 locator 必须真的存在, 否则那是一条编造的架构。

    2026-08-17 实测(修复前): 插一个 locator 指向 THIS_FILE_DOES_NOT_EXIST.py、职责写着
    "这个组件不存在于代码库任何地方"的实体, build_project_model 给 verdict=PASS、
    issues 为空, 所有门全绿 —— 这个工具当时可以显示一整张虚构的架构图而无人拦。
    """
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
                "complete": False,
                "entities": [
                    {
                        "id": "service:totally-made-up",
                        "kind": "service",
                        "name": "Fabricated service",
                        "responsibility": "This component does not exist anywhere.",
                        "locator": "src/moth/THIS_FILE_DOES_NOT_EXIST.py",
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
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
    assert any(
        "THIS_FILE_DOES_NOT_EXIST.py" in issue and "locator does not exist" in issue
        for issue in model["architecture"]["issues"]
    ), model["architecture"]["issues"]


def test_desired_locator_may_point_at_a_file_that_does_not_exist_yet(tmp_path: Path) -> None:
    """目标结构描述的是**还不存在**的东西, 它的 locator 现在指不到文件是正常的。

    拿 current 那把尺子去量 desired, 会把"计划"误判成"错误" —— 那会逼着人为了过门
    先建空文件, 正好毁掉 to_be 的意义。
    """
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
                "complete": False,
                "entities": [],
                "relations": [],
                "flows": [],
                "state_machines": [],
            },
            "desired": {
                "complete": False,
                "entities": [
                    {
                        "id": "service:not-built-yet",
                        "kind": "service",
                        "name": "Planned service",
                        "responsibility": "We intend to build this.",
                        "locator": "src/moth/not_built_yet.py",
                        "expectation": "REQUIRED",
                        "evidence_ids": ["architecture-doc"],
                    }
                ],
                "relations": [],
                "flows": [],
                "state_machines": [],
            },
        },
    )

    model = build_project_model(tmp_path)

    assert model["architecture"]["declaration_state"] == "DECLARED"
    assert not [
        issue for issue in model["architecture"]["issues"] if "locator" in issue
    ]
