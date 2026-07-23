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
    assert guidance["application_state"]["enum"] == [
        "NOT_CLAIMED",
        "APPLIED_WITH_EVIDENCE",
    ]
    receipt = schema["properties"]["activation_receipts"]["items"]
    assert set(receipt["required"]) == {
        "source_id",
        "receipt_state",
        "attestation_kind",
    }
    assert receipt["additionalProperties"] is False
    application = schema["properties"]["guidance_applications"]["items"]
    assert set(application["required"]) == {
        "source_id",
        "report_state",
        "application_state",
        "contract_id",
        "loaded_at",
        "decision_summary",
        "evidence_refs",
        "decisions_influenced",
        "conflicts",
    }
    assert application["properties"]["report_state"]["enum"] == [
        "NONE",
        "VALID",
        "INVALID",
        "STALE",
    ]
    decision = application["properties"]["decisions_influenced"]["items"]
    assert set(decision["required"]) == {
        "decision_id",
        "summary",
        "evidence_refs",
    }
    assert application["additionalProperties"] is False


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
