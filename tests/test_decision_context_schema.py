import json
from pathlib import Path

from jsonschema import Draft202012Validator

from moth.decision_context import build_decision_context

def test_decision_context_schema_freezes_orthogonal_states_and_receipts() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "schemas"
        / "moth.decision-context.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["schema_version"]["const"] == (
        "moth.decision_context.v1"
    )
    assert schema["properties"]["context_readiness"]["enum"] == [
        "READY",
        "SELF_ATTESTED",
        "BLOCKED",
    ]
    guidance = schema["properties"]["guidance"]["items"]["properties"]
    assert guidance["discovery_state"]["enum"] == [
        "UNAVAILABLE",
        "INVALID",
        "DISCOVERED",
    ]
    assert guidance["applicability"]["enum"] == ["OPTIONAL", "REQUIRED"]
    assert guidance["receipt_state"]["enum"] == [
        "NONE",
        "SELF_ATTESTED",
        "PLATFORM_VERIFIED",
        "INVALID",
        "STALE",
    ]
    receipt = schema["properties"]["activation_receipts"]["items"]
    assert set(receipt["required"]) == {
        "source_id",
        "receipt_state",
        "attestation_kind",
    }
    assert receipt["additionalProperties"] is False
    # The guidance-application evidence layer (schema field "guidance_applications")
    # was retired 2026-09 because no host ever produced application reports, so it
    # had no consumer outside its own tests. It did NOT depend on an unreachable
    # activation state: its policy accepted SELF_ATTESTED and reached
    # APPLIED_WITH_EVIDENCE on it. See docs/migration-next.md.
    assert "guidance_applications" not in schema["properties"]
    assert "application_readiness" not in schema["properties"]
    assert "missing_application_sources" not in schema["properties"]
    # The deleted subtrees were $defs/ref_list's only consumers; it went with them.
    assert set(schema["$defs"]) == {"id", "id_list"}


def test_runtime_decision_context_validates_against_schema() -> None:
    schema_path = (
        Path(__file__).parents[1]
        / "schemas"
        / "moth.decision-context.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    context = build_decision_context(
        {"sources": []},
        task_kind="mechanical",
        run_id="run-schema",
        receipts=[],
    )

    Draft202012Validator(schema).validate(context)
