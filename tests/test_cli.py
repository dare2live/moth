import json

import yaml

from moth.cli import main


def test_snapshot_emits_json_for_chunkymonkey(capsys) -> None:
    code = main(["snapshot", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"codegraph"' in captured.out
    assert '"complexity"' in captured.out


def test_snapshot_writes_json_output(tmp_path, capsys) -> None:
    output = tmp_path / "snapshot.json"
    code = main(
        [
            "snapshot",
            "--repo",
            "/Users/dp/Documents/M/stock/chunkymonkey",
            "--profile",
            "chunkymonkey",
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert output.exists()
    assert output.read_text(encoding="utf-8") == captured.out
    assert '"codegraph"' in output.read_text(encoding="utf-8")


def test_doctor_passes_for_chunkymonkey(capsys) -> None:
    code = main(["doctor", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"warnings"' in captured.out


def test_sync_emits_sync_and_snapshot_json(capsys) -> None:
    code = main(["sync", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"schema_version"' in captured.out
    assert '"sync"' in captured.out
    assert '"snapshot"' in captured.out


def test_profiles_emits_json(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_profiles_report",
        lambda _workspace=None: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "workspace_root": None,
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
    code = main(["profiles", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"schema_version"' in captured.out
    assert '"registry_profiles"' in captured.out
    assert '"workspace_profiles"' in captured.out


def test_profiles_emits_markdown(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_profiles_report",
        lambda _workspace=None: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "workspace_root": None,
            "registry_profiles": [
                {
                    "kind": "profile",
                    "name": "chunkymonkey",
                    "repo_path": "/Users/dp/Documents/M/stock/chunkymonkey",
                    "codegraph_root": "/Users/dp/Documents/M/stock/chunkymonkey",
                    "notes": "Controller-first profile for the main stock repo.",
                    "status": "PASS",
                    "issues": [],
                }
            ],
            "workspace_profiles": [],
            "summary": {
                "registry_total": 1,
                "registry_pass_count": 1,
                "registry_warn_count": 0,
                "workspace_total": 0,
                "workspace_pass_count": 0,
                "workspace_warn_count": 0,
            },
            "issues": [],
            "warnings": [],
        },
    )
    code = main(["profiles", "--format", "markdown"])
    captured = capsys.readouterr()
    assert code == 0
    assert "# Moth profiles" in captured.out
    assert "chunkymonkey" in captured.out


def test_profiles_emits_workspace_json(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_profiles_report",
        lambda workspace_root=None: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "workspace_root": workspace_root,
            "registry_profiles": [],
            "workspace_profiles": [
                {
                    "kind": "profile",
                    "name": "alpha",
                    "repo_path": "/tmp/workspace/alpha",
                    "codegraph_root": "/tmp/workspace/alpha",
                    "notes": "local",
                    "status": "PASS",
                    "issues": [],
                }
            ],
            "summary": {
                "registry_total": 0,
                "registry_pass_count": 0,
                "registry_warn_count": 0,
                "workspace_total": 1,
                "workspace_pass_count": 1,
                "workspace_warn_count": 0,
            },
            "issues": [],
            "warnings": [],
        },
    )
    code = main(["profiles", "--workspace", "/tmp/workspace", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"workspace_root": "/tmp/workspace"' in captured.out
    assert '"workspace_profiles"' in captured.out


def test_profile_emits_instruction_sources_json(tmp_path, capsys) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "complexity_command: []",
                "instruction_sources:",
                "  active:",
                "    - AGENTS.md",
                "  ignored_by_default:",
                "    - CLAUDE.md",
            ]
        ),
        encoding="utf-8",
    )

    code = main(["profile", str(profile_path), "--format", "json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["instruction_sources"]["active"] == ["AGENTS.md"]
    assert payload["instruction_sources"]["ignored_by_default"] == ["CLAUDE.md"]


def test_init_writes_repo_local_profile(tmp_path, capsys) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    output = repo / ".moth" / "profile.yaml"
    code = main(
        [
            "init",
            "--repo",
            str(repo),
            "--name",
            "sample-repo",
            "--complexity-command",
            "python -m moth",
            "--evidence-path",
            "goal=goal.md",
            "--output",
            str(output),
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    assert '"status": "PASS"' in captured.out
    assert output.exists()
    payload = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert payload["kind"] == "profile"
    assert payload["name"] == "sample-repo"
    assert payload["complexity_command"] == ["python", "-m", "moth"]
    assert payload["evidence_paths"]["goal"] == "goal.md"


def test_workspace_emits_json(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_workspace_report",
        lambda workspace_root: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "workspace_root": workspace_root,
            "profiles_report": {},
            "snapshots": [],
            "summary": {
                "snapshot_total": 0,
                "snapshot_pass_count": 0,
                "snapshot_warn_count": 0,
                "snapshot_fail_count": 0,
            },
            "issues": [],
            "warnings": [],
        },
    )
    code = main(["workspace", "--workspace", "/tmp/workspace", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"workspace_root": "/tmp/workspace"' in captured.out
    assert '"snapshots"' in captured.out


def test_workspace_emits_markdown(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_workspace_report",
        lambda workspace_root: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "workspace_root": workspace_root,
            "profiles_report": {},
            "snapshots": [
                {
                    "profile": {
                        "kind": "profile",
                        "name": "alpha",
                        "repo_path": "/tmp/workspace/alpha",
                        "codegraph_root": "/tmp/workspace/alpha",
                    },
                    "snapshot": {
                        "issues": [],
                        "warnings": [],
                    },
                    "status": "PASS",
                    "issues": [],
                    "warnings": [],
                }
            ],
            "summary": {
                "snapshot_total": 1,
                "snapshot_pass_count": 1,
                "snapshot_warn_count": 0,
                "snapshot_fail_count": 0,
            },
            "issues": [],
            "warnings": [],
        },
    )
    code = main(["workspace", "--workspace", "/tmp/workspace", "--format", "markdown"])
    captured = capsys.readouterr()
    assert code == 0
    assert "# Moth workspace" in captured.out
    assert "alpha" in captured.out


def test_workspace_writes_markdown_output(tmp_path, capsys, monkeypatch) -> None:
    output = tmp_path / "workspace.md"
    monkeypatch.setattr(
        "moth.cli.build_workspace_report",
        lambda workspace_root: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "workspace_root": workspace_root,
            "profiles_report": {},
            "snapshots": [
                {
                    "profile": {
                        "kind": "profile",
                        "name": "alpha",
                        "repo_path": "/tmp/workspace/alpha",
                        "codegraph_root": "/tmp/workspace/alpha",
                    },
                    "snapshot": {
                        "issues": [],
                        "warnings": [],
                    },
                    "status": "PASS",
                    "issues": [],
                    "warnings": [],
                }
            ],
            "summary": {
                "snapshot_total": 1,
                "snapshot_pass_count": 1,
                "snapshot_warn_count": 0,
                "snapshot_fail_count": 0,
            },
            "issues": [],
            "warnings": [],
        },
    )
    code = main(["workspace", "--workspace", "/tmp/workspace", "--format", "markdown", "--output", str(output)])
    captured = capsys.readouterr()
    assert code == 0
    assert output.exists()
    assert output.read_text(encoding="utf-8") == captured.out
    assert "# Moth workspace" in output.read_text(encoding="utf-8")
