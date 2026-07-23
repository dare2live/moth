import json
from pathlib import Path

from jsonschema import Draft202012Validator

from moth.guidance_application import evaluate_guidance_applications


_DIGEST = "sha256:" + ("a" * 64)
_LOADED_AT = "2026-07-23T08:00:00Z"


def _source() -> dict:
    return {
        "id": "mio",
        "state": "DISCOVERED",
        "source_digest": _DIGEST,
    }


def _report(**overrides: object) -> dict:
    report = {
        "schema_version": "moth.guidance_application.v1",
        "report_id": "application-mio",
        "contract_id": "contract-001",
        "run_id": "run-001",
        "source_id": "mio",
        "source_digest": _DIGEST,
        "loaded_at": _LOADED_AT,
        "decision_summary": "Use repository-owned configuration as the policy authority.",
        "evidence_refs": ["ev:decision-log:001"],
        "decisions_influenced": [
            {
                "decision_id": "decision:architecture-boundary",
                "summary": "Keep policy out of the renderer.",
                "evidence_refs": ["ev:decision-log:001"],
            }
        ],
        "conflicts": [
            {
                "conflict_id": "conflict:simplicity-vs-extensibility",
                "with_source_ids": ["architect-controller"],
                "resolution": "MERGED",
                "evidence_refs": ["ev:conflict-resolution:001"],
            }
        ],
    }
    report.update(overrides)
    return report


def _evaluate(
    reports: list[dict],
    *,
    run_id: str = "run-001",
    evidence_ids: set[str] | None = None,
    activation_bindings: dict | None = None,
) -> list[dict]:
    return evaluate_guidance_applications(
        [_source()],
        run_id=run_id,
        reports=reports,
        available_evidence_ids=(
            {"ev:decision-log:001", "ev:conflict-resolution:001"}
            if evidence_ids is None
            else evidence_ids
        ),
        activation_bindings=(
            {
                "mio": {
                    "receipt_state": "SELF_ATTESTED",
                    "contract_id": "contract-001",
                    "loaded_at": _LOADED_AT,
                }
            }
            if activation_bindings is None
            else activation_bindings
        ),
    )


def test_public_and_packaged_application_schema_are_identical_and_valid() -> None:
    root = Path(__file__).parents[1]
    public = root / "schemas" / "moth.guidance-application.schema.json"
    packaged = (
        root
        / "src"
        / "moth"
        / "schemas"
        / "moth.guidance-application.schema.json"
    )

    assert public.read_bytes() == packaged.read_bytes()
    schema = json.loads(public.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_report())


def test_valid_bound_report_claims_application_with_structured_evidence() -> None:
    result = _evaluate([_report()])

    assert result == [
        {
            "source_id": "mio",
            "report_state": "VALID",
            "application_state": "APPLIED_WITH_EVIDENCE",
            "contract_id": "contract-001",
            "loaded_at": _LOADED_AT,
            "decision_summary": "Use repository-owned configuration as the policy authority.",
            "evidence_refs": ["ev:decision-log:001"],
            "decisions_influenced": [
                {
                    "decision_id": "decision:architecture-boundary",
                    "summary": "Keep policy out of the renderer.",
                    "evidence_refs": ["ev:decision-log:001"],
                }
            ],
            "conflicts": [
                {
                    "conflict_id": "conflict:simplicity-vs-extensibility",
                    "with_source_ids": ["architect-controller"],
                    "resolution": "MERGED",
                    "evidence_refs": ["ev:conflict-resolution:001"],
                }
            ],
        }
    ]


def test_stale_binding_cannot_claim_application() -> None:
    result = _evaluate([_report()], run_id="run-002")

    assert result[0]["report_state"] == "STALE"
    assert result[0]["application_state"] == "NOT_CLAIMED"
    assert result[0]["evidence_refs"] == []
    assert result[0]["decisions_influenced"] == []
    assert result[0]["conflicts"] == []


def test_invalid_or_incomplete_report_cannot_claim_application() -> None:
    report = _report(conflicts=[
        {
            "conflict_id": "conflict:unresolved",
            "with_source_ids": ["architect-controller"],
            "resolution": "MERGED",
        }
    ])

    result = _evaluate([report])

    assert result[0]["report_state"] == "INVALID"
    assert result[0]["application_state"] == "NOT_CLAIMED"


def test_duplicate_decision_identity_cannot_claim_application() -> None:
    decision = {
        "decision_id": "decision:duplicate",
        "summary": "Duplicate identity.",
        "evidence_refs": ["ev:decision-log:001"],
    }
    result = _evaluate(
        [_report(decisions_influenced=[decision, dict(decision)])]
    )

    assert result[0]["report_state"] == "INVALID"
    assert result[0]["application_state"] == "NOT_CLAIMED"


def test_missing_report_is_not_claimed() -> None:
    result = _evaluate([])

    assert result[0]["report_state"] == "NONE"
    assert result[0]["application_state"] == "NOT_CLAIMED"


def test_dangling_evidence_reference_cannot_claim_application() -> None:
    report = _report(
        evidence_refs=["invented:unresolved"],
        decisions_influenced=[
            {
                "decision_id": "decision:architecture-boundary",
                "summary": "Keep policy out of the renderer.",
                "evidence_refs": ["invented:unresolved"],
            }
        ],
    )

    result = _evaluate([report])

    assert result[0]["report_state"] == "INVALID"
    assert result[0]["application_state"] == "NOT_CLAIMED"


def test_application_requires_a_matching_activation_binding() -> None:
    result = _evaluate([_report()], activation_bindings={})

    assert result[0]["report_state"] == "INVALID"
    assert result[0]["application_state"] == "NOT_CLAIMED"
