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
