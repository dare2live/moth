import json
from pathlib import Path


def test_snapshot_schema_declares_guidance_discovery_contract() -> None:
    schema_path = Path(__file__).parents[1] / "schemas" / "moth.snapshot.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    guidance = schema["properties"]["guidance"]
    assert set(guidance["required"]) == {
        "schema_version",
        "verdict",
        "sources",
        "issues",
        "warnings",
    }
    source = guidance["properties"]["sources"]["items"]
    assert source["properties"]["state"]["enum"] == [
        "UNAVAILABLE",
        "INVALID",
        "DISCOVERED",
    ]
    assert source["properties"]["body_exported"]["const"] is False
    discovered_contract = source["allOf"][0]
    assert discovered_contract["if"]["properties"]["state"]["enum"] == [
        "UNAVAILABLE",
        "DISCOVERED",
    ]
    assert discovered_contract["then"]["properties"]["provider"]["const"] == "codex_skill"
    assert "architecture_orchestration" in discovered_contract["then"]["properties"]["activation"]["enum"]
    assert source["properties"]["load_after"]["items"]["pattern"]


def test_snapshot_schema_links_portable_project_model() -> None:
    schema_path = Path(__file__).parents[1] / "schemas" / "moth.snapshot.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["project_model"] == {
        "$ref": "moth.project-model.schema.json"
    }


def test_snapshot_schema_models_external_tools_without_omen_top_level() -> None:
    schema_path = Path(__file__).parents[1] / "schemas" / "moth.snapshot.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert "omen" not in schema["properties"]
    tool_evidence = schema["properties"]["tool_evidence"]
    omen = tool_evidence["properties"]["tools"]["additionalProperties"]
    assert omen["properties"]["scope"]["const"] == "evidence_only"
    assert "COMPLETE" in omen["properties"]["state"]["enum"]
    assert omen["properties"]["required"]["type"] == "boolean"
    assert omen["properties"]["compatibility_basis"]["const"] == (
        "runtime_contract_probe"
    )
