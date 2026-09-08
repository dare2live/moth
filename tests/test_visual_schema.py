import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from moth.visual_model import (
    build_visual_model,
    validate_visual_document_schema,
    validate_visual_model,
)

from test_visual_model import inspection_fixture, topology_fixture


def test_visual_document_matches_public_schema() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "moth"
        / "schemas"
        / "moth.visual-document.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(schema).iter_errors(
            build_visual_model(inspection_fixture())
        )
    )

    assert errors == []
    assert validate_visual_document_schema(
        build_visual_model(inspection_fixture())
    ) == []
    assert validate_visual_model(build_visual_model(inspection_fixture())) == []


def test_visual_document_v1_keeps_new_projection_fields_optional() -> None:
    model = build_visual_model(inspection_fixture())
    for viewpoint in model["navigation"]["viewpoints"]:
        viewpoint.pop("entity_ids", None)
        viewpoint.pop("relation_ids", None)
        viewpoint.pop("finding_ids", None)
    model["architecture"].pop("summary", None)

    assert validate_visual_document_schema(model) == []


def test_visual_semantic_validator_rejects_dangling_references() -> None:
    model = build_visual_model(inspection_fixture())
    model["home"]["priority_finding_ids"].append("finding:missing")
    model["relations"]["broken"] = {
        "id": "broken",
        "kind": "calls",
        "source_id": "entity:missing",
        "target_id": "python",
        "label": "调用",
        "evidence_ids": ["evidence:missing"],
    }

    errors = validate_visual_model(model)

    assert any("priority finding" in error for error in errors)
    assert any("relation broken source" in error for error in errors)
    assert any("relation broken evidence" in error for error in errors)


def test_visual_semantic_validator_rejects_empty_declared_to_be() -> None:
    model = build_visual_model(inspection_fixture())
    model["architecture"]["to_be"]["state"] = "DECLARED"

    errors = validate_visual_model(model)

    assert any("declared To-Be" in error for error in errors)


def test_visual_validators_reject_missing_status_evidence_and_schema_fields() -> None:
    model = build_visual_model(inspection_fixture())
    model["status"]["evidence_ids"] = []

    assert any("status requires" in error for error in validate_visual_model(model))
    del model["source"]
    assert validate_visual_document_schema(model)


def test_relation_source_field_is_accepted_by_schema_but_stays_optional() -> None:
    """S6: relation.source 是可选枚举字段, 不加进 required, 且非法取值必须被 schema 拒绝。"""
    model = build_visual_model(inspection_fixture())
    relation_id = next(iter(model["relations"]))

    model["relations"][relation_id]["source"] = "DETECTED"
    assert validate_visual_document_schema(model) == []

    model["relations"][relation_id]["source"] = "MADE_UP"
    assert validate_visual_document_schema(model) != []


def test_architecture_state_complete_field_is_accepted_by_schema_but_stays_optional() -> None:
    """S6: architectureState.complete 是可选布尔字段, 不加进 required。"""
    model = build_visual_model(inspection_fixture())

    model["architecture"]["as_is"]["complete"] = True
    assert validate_visual_document_schema(model) == []

    model["architecture"]["as_is"]["complete"] = "yes"
    assert validate_visual_document_schema(model) != []


def test_diagram_policy_field_is_accepted_by_schema_and_stays_optional() -> None:
    """S6: 根对象的 diagram_policy 是可选字段 —— build_visual_model 总会填它,
    但 schema 本身不能强制要求它存在(旧文档不带这个字段也得能过 schema)。
    """
    model = build_visual_model(inspection_fixture())
    assert validate_visual_document_schema(model) == []

    without_diagram_policy = dict(model)
    del without_diagram_policy["diagram_policy"]
    assert validate_visual_document_schema(without_diagram_policy) == []

    model["diagram_policy"] = "not an object"
    assert validate_visual_document_schema(model) != []


def test_semantic_validator_flags_as_is_relation_with_endpoint_missing_from_entity_ids() -> None:
    """S5(a): as_is.relation_ids 里每条关系的两端都必须在 as_is.entity_ids 里,
    否则报错必须点名这条 relation 的 id。
    """
    model = build_visual_model(inspection_fixture())
    as_is = model["architecture"]["as_is"]
    entity_id = as_is["entity_ids"][0]
    model["relations"]["synthetic:dangling"] = {
        "id": "synthetic:dangling",
        "kind": "uses_runtime",
        "source_id": entity_id,
        "target_id": "python",  # 存在于 entities, 但不在 as_is.entity_ids 里
        "label": "uses runtime",
        "evidence_ids": [],
        "source": "DETECTED",
    }
    as_is["relation_ids"] = as_is["relation_ids"] + ["synthetic:dangling"]

    errors = validate_visual_model(model)

    assert any("synthetic:dangling" in error for error in errors)


def test_semantic_validator_flags_as_is_relation_missing_source() -> None:
    """S5(b): as_is.relation_ids 里每条关系都必须带 source, 否则报错必须点名 relation id。"""
    model = build_visual_model(inspection_fixture())
    as_is = model["architecture"]["as_is"]
    entity_id = as_is["entity_ids"][0]
    model["relations"]["synthetic:no-source"] = {
        "id": "synthetic:no-source",
        "kind": "calls",
        "source_id": entity_id,
        "target_id": entity_id,
        "label": "自环",
        "evidence_ids": [],
    }
    as_is["relation_ids"] = as_is["relation_ids"] + ["synthetic:no-source"]

    errors = validate_visual_model(model)

    assert any("synthetic:no-source" in error for error in errors)


def test_load_visual_policy_rejects_invalid_diagram_policy(tmp_path, monkeypatch) -> None:
    """S4: load_visual_policy() 必须真的校验 diagram 段, 不是加了字段没人验。"""
    from moth import visual_policy as visual_policy_module

    source_path = Path(visual_policy_module.__file__).with_name("visual_policy.yaml")
    payload = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    payload["diagram"]["provenance_legend"][0]["line"] = "zigzag"
    broken_path = tmp_path / "visual_policy.yaml"
    broken_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    monkeypatch.setattr(visual_policy_module, "files", lambda package: tmp_path)
    visual_policy_module.load_visual_policy.cache_clear()
    try:
        with pytest.raises(ValueError):
            visual_policy_module.load_visual_policy()
    finally:
        visual_policy_module.load_visual_policy.cache_clear()


def test_html_renderer_does_not_import_collectors_or_filesystem() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "moth" / "html_report.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "moth.adapters",
        "moth.detectors",
        "moth.snapshot",
        "subprocess",
        "pathlib",
    ):
        assert forbidden not in source


def test_visual_document_with_flows_and_state_machines_matches_public_schema() -> None:
    """schema 校验必须跑在**走过流程/状态机分支**的文档上。

    v1 fixture 一条 flow_step 都不产生, 所以它证明不了 relation 的形状 ——
    给 flow_step 加 ``order`` 时全绿而 Web Console 500, 就是这么来的。
    """
    model = build_visual_model(topology_fixture())

    steps = [r for r in model["relations"].values() if r["kind"] == "flow_step"]
    assert steps, "样本里没有 flow_step, 这个用例就没在验它该验的东西"
    assert all("order" in step for step in steps)
    assert any(e["kind"] == "state_machine" for e in model["entities"].values())

    assert validate_visual_document_schema(model) == []
    assert validate_visual_model(model) == []
