from __future__ import annotations

from moth import workspace as workspace_module


def test_build_workspace_report_summarizes_snapshots(monkeypatch) -> None:
    monkeypatch.setattr(
        workspace_module,
        "build_profiles_report",
        lambda _workspace: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "WARN",
            "workspace_root": "/tmp/workspace",
            "registry_profiles": [],
            "workspace_profiles": [],
            "summary": {
                "registry_total": 0,
                "registry_pass_count": 0,
                "registry_warn_count": 0,
                "workspace_total": 0,
                "workspace_pass_count": 0,
                "workspace_warn_count": 0,
            },
            "issues": [],
            "warnings": ["no workspace-local profiles found under /tmp/workspace"],
        },
    )
    monkeypatch.setattr(
        workspace_module,
        "discover_profiles",
        lambda _workspace: [],
    )
    payload = workspace_module.build_workspace_report("/tmp/workspace")

    assert payload["schema_version"] == 1
    assert payload["status"] == "WARN"
    assert payload["workspace_root"] == "/tmp/workspace"
    assert payload["summary"]["snapshot_total"] == 0
    assert payload["warnings"]


def test_build_workspace_report_includes_snapshots(monkeypatch) -> None:
    profile = type(
        "Profile",
        (),
        {
            "kind": "profile",
            "name": "alpha",
            "repo_path": "/tmp/workspace/alpha",
            "codegraph_root": "/tmp/workspace/alpha",
            "instruction_sources": {"active": ["AGENTS.md"], "ignored_by_default": ["CLAUDE.md"]},
        },
    )()

    monkeypatch.setattr(
        workspace_module,
        "build_profiles_report",
        lambda _workspace: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "workspace_root": "/tmp/workspace",
            "registry_profiles": [],
            "workspace_profiles": [],
            "summary": {
                "registry_total": 0,
                "registry_pass_count": 0,
                "registry_warn_count": 0,
                "workspace_total": 0,
                "workspace_pass_count": 0,
                "workspace_warn_count": 0,
            },
            "issues": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(workspace_module, "discover_profiles", lambda _workspace: [profile])
    monkeypatch.setattr(
        workspace_module,
        "build_snapshot",
        lambda profile: {
            "status": "PASS",
            "issues": [],
            "warnings": [],
            "profile": {"name": profile.name, "repo_path": profile.repo_path},
        },
    )

    payload = workspace_module.build_workspace_report("/tmp/workspace")

    assert payload["status"] == "PASS"
    assert payload["summary"]["snapshot_total"] == 1
    assert payload["summary"]["snapshot_pass_count"] == 1
    assert payload["snapshots"][0]["profile"]["name"] == "alpha"
    assert payload["snapshots"][0]["profile"]["instruction_sources"]["ignored_by_default"] == ["CLAUDE.md"]
