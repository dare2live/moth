import json
from pathlib import Path

from jsonschema import Draft202012Validator

from moth.visual_model import (
    build_visual_model,
    validate_visual_document_schema,
    validate_visual_model,
)

from test_visual_model import inspection_fixture


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
