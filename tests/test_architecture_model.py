from pathlib import Path

import yaml

from moth.architecture_drift import build_architecture_drift
from moth.architecture_model import build_architecture_model
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
    # flow 步骤的 from_state/to_state (idle/requested/reported) 都在
    # state-machine:inspection 的 states 里声明过 —— 这是应当放行的绿色场景。
    assert architecture["issues"] == []
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


def _flow_state_fixture_entity() -> dict:
    return {
        "id": "service:x",
        "kind": "service",
        "name": "X service",
        "responsibility": "Do X.",
        "locator": "src/moth/inspection.py",
        "evidence_ids": [],
    }


def test_flow_step_state_not_declared_in_any_state_machine_is_an_issue(
    tmp_path: Path,
) -> None:
    """flow step 用的 from_state/to_state 必须真的在某台状态机的 states 里声明过。

    2026-09 实测: moth 自己的 .moth/architecture.yaml 里, flow:inspect 的步骤用了
    snapshot_ready / guidance_assessed / modeled 这三个状态词, 但唯一的状态机
    state-machine:inspection 的 states 里压根没有它们 —— 因为当时只校验了 transition
    的 from/to, 没校验 flow step 的, 这条内容矛盾一路绿灯, 两个渲染端都不显示。
    """
    _write_python_manifest(tmp_path)
    _write_declared_sources(tmp_path, "src/moth/inspection.py")
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [],
            "current": {
                "complete": False,
                "entities": [_flow_state_fixture_entity()],
                "relations": [],
                "flows": [
                    {
                        "id": "flow:test",
                        "name": "Test flow",
                        "steps": [
                            {
                                "id": "step:one",
                                "entity_id": "service:x",
                                "action": "start",
                                "from_state": "idle",
                                "to_state": "snapshot_ready",
                            },
                            {
                                "id": "step:two",
                                "entity_id": "service:x",
                                "action": "finish",
                                "from_state": "snapshot_ready",
                                "to_state": "done",
                            },
                        ],
                        "evidence_ids": [],
                    }
                ],
                "state_machines": [
                    {
                        "id": "state-machine:x",
                        "entity_id": "service:x",
                        "initial_state": "idle",
                        "states": ["idle", "done"],
                        "transitions": [],
                        "evidence_ids": [],
                    }
                ],
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

    assert model["architecture"]["declaration_state"] == "INVALID"
    issues = model["architecture"]["issues"]
    assert any(
        "flow:test" in issue and "snapshot_ready" in issue for issue in issues
    ), issues


def test_flow_step_without_state_fields_is_not_checked(tmp_path: Path) -> None:
    """flow step 不写 from_state/to_state 时不该被这条新校验拦下。

    flow:change-safety 的步骤就是这个形状(没有状态转移语义) —— 即使声明里存在状态机,
    没提 from/to 的步骤必须继续放行。
    """
    _write_python_manifest(tmp_path)
    _write_declared_sources(tmp_path, "src/moth/inspection.py")
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [],
            "current": {
                "complete": False,
                "entities": [_flow_state_fixture_entity()],
                "relations": [],
                "flows": [
                    {
                        "id": "flow:test",
                        "name": "Test flow",
                        "steps": [
                            {
                                "id": "step:one",
                                "entity_id": "service:x",
                                "action": "receive request",
                            },
                            {
                                "id": "step:two",
                                "entity_id": "service:x",
                                "action": "produce result",
                            },
                        ],
                        "evidence_ids": [],
                    }
                ],
                "state_machines": [
                    {
                        "id": "state-machine:x",
                        "entity_id": "service:x",
                        "initial_state": "idle",
                        "states": ["idle", "done"],
                        "transitions": [],
                        "evidence_ids": [],
                    }
                ],
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

    assert model["architecture"]["declaration_state"] == "DECLARED"
    assert model["architecture"]["issues"] == []


def test_flow_step_state_with_no_state_machines_declared_is_an_issue(
    tmp_path: Path,
) -> None:
    """声明里一台状态机都没有时, 任何带 from_state/to_state 的 flow step 都该报 issue

    ——状态词没有任何定义来源, 无从判断它是否合法。
    """
    _write_python_manifest(tmp_path)
    _write_declared_sources(tmp_path, "src/moth/inspection.py")
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [],
            "current": {
                "complete": False,
                "entities": [_flow_state_fixture_entity()],
                "relations": [],
                "flows": [
                    {
                        "id": "flow:test",
                        "name": "Test flow",
                        "steps": [
                            {
                                "id": "step:one",
                                "entity_id": "service:x",
                                "action": "start",
                                "from_state": "idle",
                                "to_state": "running",
                            },
                            {
                                "id": "step:two",
                                "entity_id": "service:x",
                                "action": "finish",
                                "from_state": "running",
                                "to_state": "done",
                            },
                        ],
                        "evidence_ids": [],
                    }
                ],
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

    assert model["architecture"]["declaration_state"] == "INVALID"
    issues = model["architecture"]["issues"]
    assert any("flow:test" in issue and "idle" in issue for issue in issues), issues


def test_flow_step_without_states_and_no_state_machines_is_not_checked(
    tmp_path: Path,
) -> None:
    """边界: 声明里没有任何状态机, 且 flow step 也不带 from/to —— 无从谈起的校验不该触发。"""
    _write_python_manifest(tmp_path)
    _write_declared_sources(tmp_path, "src/moth/inspection.py")
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [],
            "current": {
                "complete": False,
                "entities": [_flow_state_fixture_entity()],
                "relations": [],
                "flows": [
                    {
                        "id": "flow:test",
                        "name": "Test flow",
                        "steps": [
                            {
                                "id": "step:one",
                                "entity_id": "service:x",
                                "action": "receive request",
                            },
                            {
                                "id": "step:two",
                                "entity_id": "service:x",
                                "action": "produce result",
                            },
                        ],
                        "evidence_ids": [],
                    }
                ],
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

    assert model["architecture"]["declaration_state"] == "DECLARED"
    assert model["architecture"]["issues"] == []


# ---------------------------------------------------------------------------
# Phase 2: import graph elevated to the declared component layer (three-tier
# verification). See module docstring history for the acceptance anchors this
# was built against (moth's own .moth/architecture.yaml).
# ---------------------------------------------------------------------------


def _synthetic_import_graph(*, roots: list[str], modules: list[str], edges: list[dict]) -> dict:
    return {
        "state": "OK",
        "roots": roots,
        "modules": sorted(modules),
        "edges": edges,
        "omitted": {"files": 0, "edges": 0},
        "notes": [],
        "issues": [],
    }


def _write_component_architecture(repo: Path) -> None:
    """A small declared graph covering every branch of the M3 decision table.

    service:a -> service:b   elevated edge exists              -> CONFIRMED
    service:a -> service:c   no elevated edge, kind refutable   -> NOT_OBSERVED
    application:ui -> service:a  ui is non-python (cross_language) -> NOT_VERIFIABLE
    service:a -> service:d   no elevated edge, kind not refutable  -> NOT_VERIFIABLE
    (service:a -> service:e exists as an elevated edge but is never declared
     -> a new DETECTED "imports" relation must appear)
    """
    _write_declared_sources(
        repo,
        "src/pkg/a.py",
        "src/pkg/b.py",
        "src/pkg/c.py",
        "src/pkg/d.py",
        "src/pkg/e.py",
        "ui/index.html",
    )

    def _entity(entity_id: str, kind: str, locator: str) -> dict:
        return {
            "id": entity_id,
            "kind": kind,
            "name": entity_id,
            "responsibility": f"Fixture entity {entity_id}.",
            "locator": locator,
            "evidence_ids": ["doc"],
        }

    def _relation(rel_id: str, kind: str, source_id: str, target_id: str) -> dict:
        return {
            "id": rel_id,
            "kind": kind,
            "source_id": source_id,
            "target_id": target_id,
            "label": rel_id,
            "evidence_ids": ["doc"],
        }

    _write_architecture(
        repo,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [
                {"id": "doc", "kind": "architecture_document", "path": "docs/architecture.md"}
            ],
            "current": {
                "complete": True,
                "entities": [
                    _entity("service:a", "service", "src/pkg/a.py"),
                    _entity("service:b", "service", "src/pkg/b.py"),
                    _entity("service:c", "service", "src/pkg/c.py"),
                    _entity("service:d", "service", "src/pkg/d.py"),
                    _entity("service:e", "service", "src/pkg/e.py"),
                    _entity("application:ui", "application", "ui/index.html"),
                ],
                "relations": [
                    _relation("relation:confirmed", "calls", "service:a", "service:b"),
                    _relation("relation:not-observed", "calls", "service:a", "service:c"),
                    _relation("relation:cross-lang", "depends_on", "application:ui", "service:a"),
                    _relation("relation:kind-scope", "depends_on", "service:a", "service:d"),
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
    docs = repo / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "architecture.md").write_text("# Architecture\n", encoding="utf-8")


def test_import_graph_elevates_direct_edges_to_the_three_tier_verdict(
    tmp_path: Path,
) -> None:
    _write_component_architecture(tmp_path)
    import_graph = _synthetic_import_graph(
        roots=["src"],
        modules=["pkg.a", "pkg.b", "pkg.c", "pkg.d", "pkg.e"],
        edges=[
            {
                "source": "pkg.a",
                "target": "pkg.b",
                "locations": [{"path": "src/pkg/a.py", "line": 5}],
            },
            {
                "source": "pkg.a",
                "target": "pkg.e",
                "locations": [{"path": "src/pkg/a.py", "line": 9}],
            },
        ],
    )

    result = build_architecture_model(
        tmp_path,
        project=None,
        applications=[],
        runtimes=[],
        modules=[],
        import_graph=import_graph,
    )

    assert result["architecture"]["issues"] == []
    assert result["architecture"]["declaration_state"] == "DECLARED"

    relations_by_id = {item["id"]: item for item in result["relations"]}

    confirmed = relations_by_id["relation:confirmed"]
    assert confirmed["source"] == "CONFIRMED"
    assert confirmed["verification"]["status"] == "CONFIRMED_BY_IMPORT"
    assert confirmed["verification"]["locations"] == [{"path": "src/pkg/a.py", "line": 5}]

    not_observed = relations_by_id["relation:not-observed"]
    assert not_observed["source"] == "DECLARED"
    assert not_observed["verification"]["status"] == "NOT_OBSERVED"

    cross_lang = relations_by_id["relation:cross-lang"]
    assert cross_lang["source"] == "DECLARED"
    assert cross_lang["verification"] == {
        "status": "NOT_VERIFIABLE",
        "reason": "cross_language",
    }

    kind_scope = relations_by_id["relation:kind-scope"]
    assert kind_scope["source"] == "DECLARED"
    assert kind_scope["verification"] == {
        "status": "NOT_VERIFIABLE",
        "reason": "kind_outside_import_scope",
    }

    # Elevated edge with no matching declaration: a new DETECTED relation.
    synthesized = relations_by_id["imports:service:a:service:e"]
    assert synthesized["kind"] == "imports"
    assert synthesized["source"] == "DETECTED"
    assert synthesized["verification"]["status"] == "CONFIRMED_BY_IMPORT"
    assert synthesized["verification"]["locations"] == [{"path": "src/pkg/a.py", "line": 9}]

    entities_by_id = {item["id"]: item for item in result["entities"]}
    assert entities_by_id["service:a"]["import_module"] == "pkg.a"
    assert entities_by_id["application:ui"]["import_scope"] == "outside"
    assert "import_module" not in entities_by_id["application:ui"]


def test_import_graph_misconfigured_root_fails_closed(tmp_path: Path) -> None:
    """A `.py` locator that cannot be mapped into any known module must be a loud
    issue, not a silent NOT_VERIFIABLE -- otherwise one bad `roots` entry quietly
    turns every relation unverifiable while the gate still looks green."""
    _write_declared_sources(tmp_path, "src/pkg/a.py")
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [],
            "current": {
                "complete": False,
                "entities": [
                    {
                        "id": "service:a",
                        "kind": "service",
                        "name": "A",
                        "responsibility": "Fixture entity.",
                        "locator": "src/pkg/a.py",
                        "evidence_ids": [],
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
    # Import graph configured with a root that does not cover src/pkg/a.py at all.
    import_graph = _synthetic_import_graph(roots=["elsewhere"], modules=["unrelated"], edges=[])

    result = build_architecture_model(
        tmp_path,
        project=None,
        applications=[],
        runtimes=[],
        modules=[],
        import_graph=import_graph,
    )

    assert result["architecture"]["declaration_state"] == "INVALID"
    assert any(
        "service:a" in issue and "src/pkg/a.py" in issue
        for issue in result["architecture"]["issues"]
    ), result["architecture"]["issues"]


def test_import_graph_not_configured_makes_declared_relations_unverifiable(
    tmp_path: Path,
) -> None:
    """M5: no import graph must never manufacture a NOT_OBSERVED verdict, and must
    never flip declaration_state to INVALID by itself."""
    _write_declared_sources(tmp_path, "src/pkg/a.py", "src/pkg/b.py")
    _write_architecture(
        tmp_path,
        {
            "schema_version": "moth.architecture-declaration.v1",
            "evidence": [],
            "current": {
                "complete": True,
                "entities": [
                    {
                        "id": "service:a",
                        "kind": "service",
                        "name": "A",
                        "responsibility": "Fixture entity.",
                        "locator": "src/pkg/a.py",
                        "evidence_ids": [],
                    },
                    {
                        "id": "service:b",
                        "kind": "service",
                        "name": "B",
                        "responsibility": "Fixture entity.",
                        "locator": "src/pkg/b.py",
                        "evidence_ids": [],
                    },
                ],
                "relations": [
                    {
                        "id": "relation:a-b",
                        "kind": "calls",
                        "source_id": "service:a",
                        "target_id": "service:b",
                        "label": "calls",
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
    # No pyproject.toml at all -> self-derivation cannot infer any roots.

    result = build_architecture_model(
        tmp_path,
        project=None,
        applications=[],
        runtimes=[],
        modules=[],
    )

    assert result["architecture"]["declaration_state"] == "DECLARED"
    relation = next(
        item for item in result["relations"] if item["id"] == "relation:a-b"
    )
    assert relation["verification"] == {
        "status": "NOT_VERIFIABLE",
        "reason": "import_graph_not_configured",
    }
    assert relation["source"] == "DECLARED"


def test_declared_relation_without_import_confirmation_is_unverifiable_drift() -> None:
    """M6: a relation that is only DECLARED (no import evidence) can no longer be
    reported CONFORMANT -- that was the bug this whole step exists to fix."""
    current = {
        "complete": True,
        "entities": [],
        "relations": [
            {
                "id": "relation:x",
                "kind": "calls",
                "source_id": "service:a",
                "target_id": "service:b",
                "label": "calls",
                "evidence_ids": ["observed"],
                "source": "DECLARED",
                "verification": {
                    "status": "NOT_OBSERVED",
                    "reason": "not_observed_in_static_imports",
                },
            }
        ],
        "flows": [],
        "state_machines": [],
    }
    desired = {
        "entities": [],
        "relations": [
            {
                "id": "relation:x",
                "kind": "calls",
                "source_id": "service:a",
                "target_id": "service:b",
                "label": "calls",
                "expectation": "REQUIRED",
                "evidence_ids": ["declared"],
            }
        ],
        "flows": [],
        "state_machines": [],
    }

    drift = build_architecture_drift(current=current, desired=desired)

    assert drift["state"] == "UNVERIFIABLE"
    finding = drift["findings"][0]
    assert finding["status"] == "UNVERIFIABLE"
    assert "NOT_OBSERVED" in finding["reason"]
    assert "observation_basis" not in finding


def test_confirmed_relation_is_conformant_with_import_graph_observation_basis() -> None:
    current = {
        "complete": True,
        "entities": [],
        "relations": [
            {
                "id": "relation:x",
                "kind": "calls",
                "source_id": "service:a",
                "target_id": "service:b",
                "label": "calls",
                "evidence_ids": ["observed"],
                "source": "CONFIRMED",
                "verification": {
                    "status": "CONFIRMED_BY_IMPORT",
                    "reason": "confirmed_by_import_edge",
                    "locations": [{"path": "src/a.py", "line": 3}],
                },
            }
        ],
        "flows": [],
        "state_machines": [],
    }
    desired = {
        "entities": [],
        "relations": [
            {
                "id": "relation:x",
                "kind": "calls",
                "source_id": "service:a",
                "target_id": "service:b",
                "label": "calls",
                "expectation": "REQUIRED",
                "evidence_ids": ["declared"],
            }
        ],
        "flows": [],
        "state_machines": [],
    }

    drift = build_architecture_drift(current=current, desired=desired)

    finding = drift["findings"][0]
    assert finding["status"] == "CONFORMANT"
    assert finding["observation_basis"] == "import_graph"
    assert drift["state"] == "CONFORMANT"


def test_required_entity_conformance_notes_locator_only_observation_basis() -> None:
    """Entities keep their existing CONFORMANT verdict (their locator was already
    checked to exist), but must not claim the responsibility text was verified."""
    entity = {
        "id": "service:x",
        "kind": "service",
        "name": "X",
        "responsibility": "Do X.",
        "locator": "src/x.py",
        "evidence_ids": ["observed"],
        "source": "DECLARED",
    }
    current = {
        "complete": True,
        "entities": [entity],
        "relations": [],
        "flows": [],
        "state_machines": [],
    }
    desired_entity = {
        "id": "service:x",
        "kind": "service",
        "name": "X",
        "responsibility": "Do X.",
        "locator": "src/x.py",
        "expectation": "REQUIRED",
        "evidence_ids": ["declared"],
    }
    desired = {
        "entities": [desired_entity],
        "relations": [],
        "flows": [],
        "state_machines": [],
    }

    drift = build_architecture_drift(current=current, desired=desired)

    finding = drift["findings"][0]
    assert finding["status"] == "CONFORMANT"
    assert finding["observation_basis"] == "locator_exists"


def test_required_flow_match_is_always_unverifiable_no_detector() -> None:
    """M6: flows and state machines have no detector at all, so a match against
    the declaration can never be treated as independently observed."""
    flow = {
        "id": "flow:x",
        "name": "Flow X",
        "steps": [],
        "evidence_ids": ["observed"],
    }
    current = {
        "complete": True,
        "entities": [],
        "relations": [],
        "flows": [flow],
        "state_machines": [],
    }
    desired_flow = {
        "id": "flow:x",
        "name": "Flow X",
        "steps": [],
        "expectation": "REQUIRED",
        "evidence_ids": ["declared"],
    }
    desired = {
        "entities": [],
        "relations": [],
        "flows": [desired_flow],
        "state_machines": [],
    }

    drift = build_architecture_drift(current=current, desired=desired)

    finding = drift["findings"][0]
    assert finding["status"] == "UNVERIFIABLE"
    assert "observation_basis" not in finding


def test_moth_self_hosting_import_graph_verification_matches_accepted_anchors() -> None:
    """End-to-end acceptance anchor: moth inspecting itself.

    These exact counts were measured by hand against moth's own
    .moth/architecture.yaml and are pinned here as a regression net. If this
    goes red because the declaration or the source tree changed, update the
    anchor -- do not loosen the assertions to make it pass.
    """
    repo_root = Path(__file__).resolve().parents[1]

    model = build_project_model(repo_root)
    architecture = model["architecture"]

    assert architecture["declaration_state"] == "DECLARED"
    assert architecture["issues"] == []

    relations = model["relations"]
    declared_ids = {
        "relation:inspection-snapshot",
        "relation:project-architecture",
        "relation:inspection-change-safety",
        "relation:inspection-guidance-application",
        "relation:visual-html",
        "relation:web-service-inspection",
        "relation:web-service-visual",
        "relation:web-app-service",
        "relation:web-launcher-server",
        "relation:web-server-app",
        "relation:web-registry-config",
        "relation:web-console-api",
    }
    by_id = {item["id"]: item for item in relations if item["id"] in declared_ids}
    assert set(by_id) == declared_ids

    confirmed_ids = {
        rel_id
        for rel_id, rel in by_id.items()
        if rel["verification"]["status"] == "CONFIRMED_BY_IMPORT"
    }
    not_observed_ids = {
        rel_id
        for rel_id, rel in by_id.items()
        if rel["verification"]["status"] == "NOT_OBSERVED"
    }
    not_verifiable_ids = {
        rel_id
        for rel_id, rel in by_id.items()
        if rel["verification"]["status"] == "NOT_VERIFIABLE"
    }

    assert len(confirmed_ids) == 8, confirmed_ids
    assert not_observed_ids == {"relation:inspection-guidance-application"}
    assert not_verifiable_ids == {
        "relation:web-console-api",
        "relation:web-launcher-server",
        "relation:visual-html",
    }

    detected_import_relations = [
        item for item in relations if item.get("kind") == "imports"
    ]
    assert len(detected_import_relations) >= 4, len(detected_import_relations)
    detected_pairs = {
        (item["source_id"], item["target_id"]) for item in detected_import_relations
    }
    for pair in [
        ("service:web-app", "service:web-config"),
        ("service:web-server", "service:web-config"),
        ("service:web-server", "service:web-registry"),
        ("service:web-service", "service:web-config"),
    ]:
        assert pair in detected_pairs, (pair, detected_pairs)
