from pathlib import Path

from moth.orchestration import prepare_task_context


def _write_skill(codex_home: Path, source_id: str) -> None:
    skill_dir = codex_home / "skills" / source_id
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {source_id}\ndescription: Test guidance.\n---\n# Private body\n",
        encoding="utf-8",
    )


def test_one_core_call_discovers_and_plans_mio_and_architect(tmp_path: Path) -> None:
    _write_skill(tmp_path, "mio")
    _write_skill(tmp_path, "architect-controller")
    registry_dir = tmp_path / "moth"
    registry_dir.mkdir()
    (registry_dir / "guidance.yaml").write_text(
        """
kind: moth_guidance_registry
sources:
  - id: mio
    kind: collaboration_lens
    provider: codex_skill
    ref: skill:mio
    activation: substantive_judgment
    requirement: required_when_active
    scope: user
    owner: user
    sensitivity: personal
    egress_policy: metadata_only
  - id: architect-controller
    kind: controller_protocol
    provider: codex_skill
    ref: skill:architect-controller
    activation: architecture_orchestration
    requirement: required_when_active
    scope: user
    owner: user
    sensitivity: internal
    egress_policy: metadata_only
    load_after: [mio]
""".strip(),
        encoding="utf-8",
    )

    result = prepare_task_context(
        {},
        task_kind="architecture_orchestration",
        run_id="run-one-call",
        receipts=[],
        codex_home=tmp_path,
    )

    assert result["registry"]["verdict"] == "PASS"
    assert result["guidance"]["verdict"] == "PASS"
    assert result["decision_context"]["ordered_guidance_sources"] == [
        "mio",
        "architect-controller",
    ]
    assert result["decision_context"]["context_readiness"] == "BLOCKED"
    assert result["decision_context"]["guidance_applications"] == [
        {
            "source_id": "mio",
            "report_state": "NONE",
            "application_state": "NOT_CLAIMED",
            "contract_id": None,
            "loaded_at": None,
            "decision_summary": None,
            "evidence_refs": [],
            "decisions_influenced": [],
            "conflicts": [],
        },
        {
            "source_id": "architect-controller",
            "report_state": "NONE",
            "application_state": "NOT_CLAIMED",
            "contract_id": None,
            "loaded_at": None,
            "decision_summary": None,
            "evidence_refs": [],
            "decisions_influenced": [],
            "conflicts": [],
        },
    ]
    assert str(tmp_path) not in repr(result)
    assert "Private body" not in repr(result)
