from pathlib import Path
from types import SimpleNamespace

from moth import tool_evidence as tool_module


def _profile(*, enabled: bool = True, required: bool = False):
    return SimpleNamespace(
        repo_path=Path("/"),
        tools={
            "omen": {
                "enabled": enabled,
                "required": required,
                "config_path": Path("/config/omen.toml"),
                "top": 20,
                "diff_target": None,
                "timeout_seconds": 30.0,
            }
        },
    )


def test_optional_omen_failure_is_warning_not_project_failure(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        tool_module,
        "run_omen_evidence",
        lambda *_args, **_kwargs: {
            "tool": "omen",
            "scope": "evidence_only",
            "state": "BINARY_UNAVAILABLE",
            "evidence": [],
            "issues": ["unable to verify Omen version"],
        },
    )

    evidence = tool_module.collect_tool_evidence(
        _profile(), installations={"omen": {"executable": "omen"}}
    )
    issues, warnings = tool_module.tool_health_messages(evidence)

    assert evidence["tools"]["omen"]["required"] is False
    assert issues == []
    assert warnings == ["omen evidence unavailable: BINARY_UNAVAILABLE"]


def test_required_omen_failure_is_project_issue(monkeypatch) -> None:
    monkeypatch.setattr(
        tool_module,
        "run_omen_evidence",
        lambda *_args, **_kwargs: {
            "tool": "omen",
            "scope": "evidence_only",
            "state": "UNSUPPORTED_OUTPUT",
            "evidence": [],
            "issues": ["Omen output contract is unsupported"],
        },
    )

    evidence = tool_module.collect_tool_evidence(
        _profile(required=True), installations={"omen": {"executable": "omen"}}
    )
    issues, warnings = tool_module.tool_health_messages(evidence)

    assert issues == ["required omen evidence unavailable: UNSUPPORTED_OUTPUT"]
    assert warnings == []


def test_unconfigured_or_complete_omen_does_not_change_health(
    monkeypatch,
) -> None:
    unconfigured = tool_module.collect_tool_evidence(
        SimpleNamespace(repo_path="/repo", tools={})
    )
    assert unconfigured["tools"] == {}
    assert tool_module.tool_health_messages(unconfigured) == ([], [])

    monkeypatch.setattr(
        tool_module,
        "run_omen_evidence",
        lambda *_args, **_kwargs: {
            "tool": "omen",
            "scope": "evidence_only",
            "state": "COMPLETE",
            "evidence": [{"kind": "hotspot", "findings": [{"file": "x.py"}]}],
            "issues": [],
        },
    )
    complete = tool_module.collect_tool_evidence(
        _profile(required=True), installations={"omen": {"executable": "omen"}}
    )
    assert tool_module.tool_health_messages(complete) == ([], [])


def test_second_registered_tool_uses_generic_profile_and_bundle_without_core_changes(
    monkeypatch,
) -> None:
    contract = {
        "profile": {
            "allowed_keys": [
                "enabled",
                "required",
                "config_path",
                "top",
                "timeout_seconds",
            ],
            "required_when_enabled": [],
            "defaults": {
                "enabled": False,
                "required": False,
                "config_path": None,
                "top": 1,
                "timeout_seconds": 5,
            },
        },
        "bounds": {
            "max_findings": 10,
            "default_timeout_seconds": 5,
            "max_timeout_seconds": 10,
        },
    }
    monkeypatch.setattr(tool_module, "load_tool_contract", lambda _tool_id: contract)
    monkeypatch.setitem(
        tool_module._ADAPTERS,
        "fake",
        lambda *_args: {
            "schema_version": 1,
            "tool": "fake",
            "scope": "evidence_only",
            "state": "COMPLETE",
            "version": "99.0.0",
            "compatible": True,
            "compatibility_basis": "runtime_contract_probe",
            "evidence": [],
            "issues": [],
        },
    )
    profile = SimpleNamespace(
        repo_path=Path("/"),
        tools={"fake": {"enabled": True, "required": False}},
    )

    bundle = tool_module.collect_tool_evidence(
        profile,
        installations={"fake": {"executable": "fake"}},
    )

    assert bundle["tools"]["fake"]["state"] == "COMPLETE"
    assert tool_module.tool_health_messages(bundle) == ([], [])
