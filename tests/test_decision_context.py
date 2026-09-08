import pytest

from moth.decision_context import build_decision_context


def _guidance() -> dict:
    return {
        "schema_version": "moth.guidance.v1",
        "verdict": "PASS",
        "issues": [],
        "warnings": [],
        "sources": [
            {
                "id": "architect-controller",
                "kind": "controller_protocol",
                "ref": "skill:architect-controller",
                "activation": "architecture_orchestration",
                "requirement": "required_when_active",
                "state": "DISCOVERED",
                "source_digest": "sha256:architect",
                "load_after": ["mio"],
            },
            {
                "id": "mio",
                "kind": "collaboration_lens",
                "ref": "skill:mio",
                "activation": "substantive_judgment",
                "requirement": "required_when_active",
                "state": "DISCOVERED",
                "source_digest": "sha256:mio",
                "load_after": [],
            },
        ],
    }


def test_architecture_task_requires_mio_then_architect_and_blocks_without_receipts() -> None:
    context = build_decision_context(
        _guidance(),
        task_kind="architecture_orchestration",
        run_id="run-001",
        receipts=[],
    )

    assert context["schema_version"] == "moth.decision_context.v1"
    assert context["task"]["kind"] == "architecture_orchestration"
    assert context["ordered_guidance_sources"] == ["mio", "architect-controller"]
    assert [item["applicability"] for item in context["guidance"]] == ["REQUIRED", "REQUIRED"]
    assert [item["receipt_state"] for item in context["guidance"]] == ["NONE", "NONE"]
    assert context["context_readiness"] == "BLOCKED"
    assert context["missing_required_sources"] == ["mio", "architect-controller"]
    assert context["self_attested_required_sources"] == []
    assert context["project_health_affected"] is False


def test_matching_executor_receipts_are_self_attested_not_machine_verified() -> None:
    receipts = [
        {
            "receipt_id": "receipt-mio",
            "run_id": "run-001",
            "source_id": "mio",
            "source_digest": "sha256:mio",
            "executor_id": "codex",
            "loaded_at": "2026-07-23T08:00:00Z",
            "contract_id": "contract-001",
            "evidence_refs": ["ev:executor:mio"],
        },
        {
            "receipt_id": "receipt-architect",
            "run_id": "run-001",
            "source_id": "architect-controller",
            "source_digest": "sha256:architect",
            "executor_id": "codex",
            "loaded_at": "2026-07-23T08:00:01Z",
            "contract_id": "contract-001",
            "evidence_refs": ["ev:executor:architect"],
        },
    ]

    context = build_decision_context(
        _guidance(),
        task_kind="architecture_orchestration",
        run_id="run-001",
        receipts=receipts,
    )

    assert context["context_readiness"] == "SELF_ATTESTED"
    assert context["missing_required_sources"] == []
    assert context["self_attested_required_sources"] == ["mio", "architect-controller"]
    assert [item["receipt_state"] for item in context["guidance"]] == [
        "SELF_ATTESTED",
        "SELF_ATTESTED",
    ]
    assert context["activation_receipts"] == [
        {
            "source_id": "mio",
            "receipt_state": "SELF_ATTESTED",
            "attestation_kind": "executor_self_attested",
        },
        {
            "source_id": "architect-controller",
            "receipt_state": "SELF_ATTESTED",
            "attestation_kind": "executor_self_attested",
        },
    ]


def test_mechanical_task_marks_guidance_not_applicable_without_blocking() -> None:
    context = build_decision_context(
        _guidance(),
        task_kind="mechanical",
        run_id="run-mechanical",
        receipts=[],
    )

    assert context["context_readiness"] == "READY"
    assert context["ordered_guidance_sources"] == []
    assert context["guidance"] == []
    assert context["not_applicable_sources"] == ["architect-controller", "mio"]


def test_changed_skill_digest_makes_old_receipt_stale_and_blocks() -> None:
    guidance = _guidance()
    guidance["sources"][1]["source_digest"] = "sha256:mio-new"
    receipt = {
        "receipt_id": "receipt-mio-old",
        "run_id": "run-001",
        "source_id": "mio",
        "source_digest": "sha256:mio",
        "executor_id": "codex",
        "loaded_at": "2026-07-23T08:00:00Z",
        "contract_id": "contract-001",
        "evidence_refs": ["ev:executor:mio"],
    }

    context = build_decision_context(
        guidance,
        task_kind="substantive_judgment",
        run_id="run-001",
        receipts=[receipt],
    )

    assert context["guidance"][0]["source_id"] == "mio"
    assert context["guidance"][0]["receipt_state"] == "STALE"
    assert context["context_readiness"] == "BLOCKED"
    assert context["missing_required_sources"] == ["mio"]


def test_guidance_load_order_cycle_fails_closed() -> None:
    guidance = _guidance()
    guidance["sources"][1]["load_after"] = ["architect-controller"]

    with pytest.raises(ValueError, match="guidance load order contains a cycle"):
        build_decision_context(
            guidance,
            task_kind="architecture_orchestration",
            run_id="run-cycle",
            receipts=[],
        )


def test_guidance_load_order_missing_dependency_fails_closed() -> None:
    guidance = _guidance()
    guidance["sources"][0]["load_after"] = ["missing-controller"]

    with pytest.raises(ValueError, match="missing guidance dependency"):
        build_decision_context(
            guidance,
            task_kind="architecture_orchestration",
            run_id="run-missing",
            receipts=[],
        )


def test_receipt_cannot_override_unavailable_guidance() -> None:
    guidance = _guidance()
    guidance["sources"][1]["state"] = "UNAVAILABLE"
    guidance["sources"][1]["source_digest"] = None
    receipt = {
        "receipt_id": "receipt-for-unavailable-source",
        "run_id": "run-001",
        "source_id": "mio",
        "source_digest": None,
        "executor_id": "codex",
        "loaded_at": "2026-07-23T08:00:00Z",
        "contract_id": "contract-001",
        "evidence_refs": ["ev:executor:mio"],
    }

    context = build_decision_context(
        guidance,
        task_kind="substantive_judgment",
        run_id="run-001",
        receipts=[receipt],
    )

    assert context["guidance"][0]["receipt_state"] == "INVALID"
    assert context["context_readiness"] == "BLOCKED"
    assert context["missing_required_sources"] == ["mio"]


def test_duplicate_guidance_source_ids_fail_closed() -> None:
    guidance = _guidance()
    guidance["sources"].append(dict(guidance["sources"][1]))

    with pytest.raises(ValueError, match="duplicate guidance source id"):
        build_decision_context(
            guidance,
            task_kind="substantive_judgment",
            run_id="run-duplicate-source",
            receipts=[],
        )


def test_duplicate_or_unknown_receipt_sources_fail_closed() -> None:
    duplicate_receipt = {
        "receipt_id": "receipt-mio",
        "run_id": "run-001",
        "source_id": "mio",
        "source_digest": "sha256:mio",
        "executor_id": "codex",
        "loaded_at": "2026-07-23T08:00:00Z",
        "contract_id": "contract-001",
        "evidence_refs": ["ev:executor:mio"],
    }

    with pytest.raises(ValueError, match="duplicate activation receipt"):
        build_decision_context(
            _guidance(),
            task_kind="substantive_judgment",
            run_id="run-001",
            receipts=[duplicate_receipt, dict(duplicate_receipt)],
        )

    with pytest.raises(ValueError, match="unknown guidance source"):
        build_decision_context(
            _guidance(),
            task_kind="substantive_judgment",
            run_id="run-001",
            receipts=[{**duplicate_receipt, "source_id": "not-registered"}],
        )


def test_malformed_receipt_is_invalid_and_private_values_are_not_echoed() -> None:
    malicious = {
        "receipt_id": "/Users/private/receipt",
        "run_id": "run-001",
        "source_id": "mio",
        "source_digest": "sha256:mio",
        "executor_id": "private@example.test",
        "loaded_at": "not-a-date",
        "contract_id": "contract-001",
        "evidence_refs": ["/Users/private/evidence"],
    }

    context = build_decision_context(
        _guidance(),
        task_kind="substantive_judgment",
        run_id="run-001",
        receipts=[malicious],
    )

    assert context["context_readiness"] == "BLOCKED"
    assert context["guidance"][0]["receipt_state"] == "INVALID"
    serialized = repr(context)
    assert "/Users/private" not in serialized
    assert "private@example.test" not in serialized
    assert "not-a-date" not in serialized


def test_run_id_must_be_portable_and_is_not_echoed() -> None:
    with pytest.raises(ValueError, match="bounded portable identifier") as error:
        build_decision_context(
            _guidance(),
            task_kind="mechanical",
            run_id="/Users/private/leak",
            receipts=[],
        )

    assert "/Users/private" not in str(error.value)
