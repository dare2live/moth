import json

import pytest
import yaml

from moth.cli import main


def test_inspect_is_single_moth_entry_for_snapshot_and_task_guidance(
    capsys, monkeypatch, tmp_path
) -> None:
    captured_call = {}

    def fake_inspection(
        profile,
        *,
        task_kind,
        run_id,
        receipts,
        application_reports,
        codex_home,
    ):
        captured_call.update(
            {
                "profile": profile.name,
                "task_kind": task_kind,
                "run_id": run_id,
                "receipts": receipts,
                "application_reports": application_reports,
                "codex_home": codex_home,
            }
        )
        return {
            "schema_version": "moth.inspection.v1",
            "status": "NEEDS_EXECUTOR",
            "project_health": "PASS",
            "context_readiness": "BLOCKED",
            "snapshot": {"status": "PASS"},
            "orchestration": {
                "decision_context": {
                    "ordered_guidance_sources": [
                        "mio",
                        "architect-controller",
                    ]
                }
            },
        }

    monkeypatch.setattr("moth.cli.build_inspection", fake_inspection)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    code = main(
        [
            "inspect",
            "--repo",
            "/Users/dp/Documents/M/stock/chunkymonkey",
            "--profile",
            "chunkymonkey",
            "--task-kind",
            "architecture_orchestration",
            "--run-id",
            "run-001",
            "--plan-only",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "NEEDS_EXECUTOR"
    assert captured_call == {
        "profile": "chunkymonkey",
        "task_kind": "architecture_orchestration",
        "run_id": "run-001",
        "receipts": [],
        "application_reports": [],
        "codex_home": tmp_path,
    }


def test_inspect_passes_structured_application_reports(
    capsys, monkeypatch, tmp_path
) -> None:
    reports_path = tmp_path / "application-reports.json"
    reports_path.write_text('[{"source_id": "mio"}]\n', encoding="utf-8")
    captured = {}

    def fake_inspection(_profile, **kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "moth.inspection.v1",
            "status": "PASS",
            "project_health": "PASS",
            "context_readiness": "READY",
            "snapshot": {"status": "PASS"},
            "orchestration": {"decision_context": {}},
        }

    monkeypatch.setattr("moth.cli.build_inspection", fake_inspection)

    code = main(
        [
            "inspect",
            "--repo",
            str(tmp_path),
            "--application-reports",
            str(reports_path),
            "--format",
            "json",
        ]
    )

    assert code == 0
    assert captured["application_reports"] == [{"source_id": "mio"}]
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"


def test_inspect_can_render_self_contained_html(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "moth.cli.build_inspection",
        lambda *_args, **_kwargs: {
            "schema_version": "moth.inspection.v1",
            "status": "PASS",
            "project_health": "PASS",
            "context_readiness": "READY",
            "snapshot": {
                "status": "PASS",
                "issues": [],
                "warnings": [],
                "dirty_worktree_count": 0,
                "project_model": {
                    "verdict": "PASS",
                    "project": {
                        "id": "project:sample",
                        "name": "sample",
                        "description": "Sample project",
                        "version": None,
                        "evidence_ids": [],
                    },
                    "applications": [],
                    "runtimes": [],
                    "modules": [],
                    "evidence": [],
                    "coverage": {"detectors": [], "issues": [], "warnings": []},
                },
                "codegraph": {},
                "complexity": {},
                "coupling": {},
                "import_cycles": {},
                "tool_evidence": {"tools": {}},
                "assertions": {},
            },
            "orchestration": {"decision_context": {"context_readiness": "READY"}},
        },
    )
    output = tmp_path / "moth.html"

    code = main(
        [
            "inspect",
            "--repo",
            str(tmp_path),
            "--format",
            "html",
            "--output",
            str(output),
        ]
    )
    rendered = capsys.readouterr().out

    assert code == 0
    assert rendered.startswith("<!doctype html>")
    assert output.read_text(encoding="utf-8") == rendered
    assert '<meta http-equiv="Content-Security-Policy"' in rendered


def test_inspect_uses_ephemeral_profile_without_writing_target_repo(
    capsys, monkeypatch, tmp_path
) -> None:
    repo = tmp_path / "unconfigured"
    repo.mkdir()
    seen = {}

    def fake_inspection(profile, **_kwargs):
        seen["kind"] = profile.kind
        seen["repo_path"] = profile.repo_path
        return {
            "schema_version": "moth.inspection.v1",
            "status": "READY",
            "project_health": "PASS",
            "context_readiness": "READY",
            "snapshot": {"status": "PASS"},
            "orchestration": {"decision_context": {}},
        }

    monkeypatch.setattr("moth.cli.build_inspection", fake_inspection)

    code = main(["inspect", "--repo", str(repo), "--format", "json"])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "READY"
    assert seen == {
        "kind": "ephemeral_profile",
        "repo_path": repo.resolve(),
    }
    assert not (repo / ".moth").exists()


@pytest.mark.parametrize(
    ("change_verdict", "expected_code"),
    [("GO", 0), ("CAUTION", 2), ("NO_GO", 1)],
)
def test_inspect_change_safety_verdict_controls_exit_code(
    change_verdict, expected_code, capsys, monkeypatch, tmp_path
) -> None:
    captured = {}

    def fake_inspection(_profile, **kwargs):
        captured.update(kwargs)
        return {
            "schema_version": "moth.inspection.v1",
            "status": "PASS",
            "project_health": "PASS",
            "context_readiness": "READY",
            "change_safety_verdict": change_verdict,
            "change_safety": {
                "phase": "pre_change",
                "verdict": change_verdict,
            },
            "snapshot": {"status": "PASS"},
            "orchestration": {"decision_context": {}},
        }

    monkeypatch.setattr("moth.cli.build_inspection", fake_inspection)

    code = main(
        [
            "inspect",
            "--repo",
            str(tmp_path),
            "--change-phase",
            "pre",
            "--file",
            "src/example.py",
            "--gate",
            "release",
            "--plan-only",
            "--format",
            "json",
        ]
    )

    assert code == expected_code
    assert json.loads(capsys.readouterr().out)["change_safety_verdict"] == (
        change_verdict
    )
    assert captured["change_phase"] == "pre_change"
    assert captured["changed_files"] == ["src/example.py"]
    assert captured["gate_names"] == ["release"]
    assert captured["execute_gates"] is False


def test_inspect_change_options_require_change_phase(capsys, tmp_path) -> None:
    code = main(
        [
            "inspect",
            "--repo",
            str(tmp_path),
            "--file",
            "src/example.py",
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "FAIL"
    assert "require --change-phase" in payload["issues"][0]


@pytest.mark.parametrize("output_format", ["json", "markdown", "html"])
def test_inspect_invalid_receipts_fail_consistently_without_traceback(
    output_format, capsys, tmp_path
) -> None:
    receipts = tmp_path / "receipts.json"
    receipts.write_text("not-json", encoding="utf-8")

    code = main(
        [
            "inspect",
            "--repo",
            str(tmp_path),
            "--receipts",
            str(receipts),
            "--format",
            output_format,
        ]
    )
    rendered = capsys.readouterr().out

    assert code == 1
    assert "inspection failed" in rendered
    assert "Traceback" not in rendered


def test_snapshot_emits_json_for_chunkymonkey(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_snapshot",
        lambda _profile: {"status": "PASS", "codegraph": {}, "complexity": {}, "issues": [], "warnings": []},
    )
    code = main(["snapshot", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"codegraph"' in captured.out
    assert '"complexity"' in captured.out


def test_snapshot_writes_json_output(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_snapshot",
        lambda _profile: {"status": "PASS", "codegraph": {}, "complexity": {}, "issues": [], "warnings": []},
    )
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


def test_doctor_passes_for_chunkymonkey(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_snapshot",
        lambda _profile: {"status": "PASS", "codegraph": {}, "complexity": {}, "issues": [], "warnings": []},
    )
    code = main(["doctor", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"warnings"' in captured.out


def test_sync_emits_sync_and_snapshot_json(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_sync_report",
        lambda _profile: {
            "schema_version": 1,
            "generated_at": "2026-06-18T12:00:00Z",
            "status": "PASS",
            "sync": {},
            "snapshot": {},
            "issues": [],
            "warnings": [],
        },
    )
    code = main(["sync", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"schema_version"' in captured.out
    assert '"sync"' in captured.out
    assert '"snapshot"' in captured.out


def test_affected_emits_json(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_affected_report",
        lambda profile, files, depth=5, test_filter=None: {
            "schema_version": 1,
            "generated_at": "2026-06-18T12:00:00Z",
            "status": "PASS",
            "profile": {"name": profile.name, "repo_path": str(profile.repo_path)},
            "input_files": files,
            "depth": depth,
            "test_filter": test_filter,
            "codegraph_affected": {
                "verdict": "PASS",
                "affectedTests": ["tests/test_example.py"],
                "totalDependentsTraversed": 1,
                "issues": [],
            },
            "complexity": {"verdict": "PASS", "summary": {"finding_count": 0}, "findings": []},
            "issues": [],
            "warnings": [],
        },
    )

    code = main(
        [
            "affected",
            "--repo",
            "/Users/dp/Documents/M/stock/chunkymonkey",
            "--profile",
            "chunkymonkey",
            "--file",
            "src/new.py",
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["input_files"] == ["src/new.py"]
    assert payload["codegraph_affected"]["affectedTests"] == ["tests/test_example.py"]


def test_affected_warn_exit_is_nonzero_to_prevent_false_green(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(
        "moth.cli.build_affected_report",
        lambda *_args, **_kwargs: {
            "status": "WARN",
            "affected_test_coverage": "UNKNOWN_EMPTY",
            "codegraph_affected": {"affectedTests": []},
            "warnings": ["affected test coverage unknown"],
            "issues": [],
        },
    )

    code = main(
        [
            "affected",
            "--repo",
            "/Users/dp/Documents/M/stock/chunkymonkey",
            "--profile",
            "chunkymonkey",
            "--file",
            "src/new.py",
            "--format",
            "json",
        ]
    )

    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "WARN"


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


def test_profile_resolves_guidance_sources_json(tmp_path, monkeypatch, capsys) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    codex_home = tmp_path / "codex-home"
    skill_dir = codex_home / "skills" / "mio"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: mio\ndescription: Personal collaboration lens.\n---\n# Mio\n",
        encoding="utf-8",
    )
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "instruction_sources:",
                "  sources:",
                "    - id: mio",
                "      kind: collaboration_lens",
                "      provider: codex_skill",
                "      ref: skill:mio",
                "      activation: substantive_judgment",
                "      requirement: required_when_active",
                "      scope: user",
                "      owner: user",
                "      sensitivity: personal",
                "      egress_policy: metadata_only",
                "      state: APPLIED_WITH_EVIDENCE",
                "      body: private amend trail",
                f"      resolved_path_local_only: {skill_dir / 'SKILL.md'}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    code = main(["profile", str(profile_path), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["guidance"]["verdict"] == "PASS"
    assert payload["guidance"]["sources"][0]["state"] == "DISCOVERED"
    assert payload["guidance"]["sources"][0]["ref"] == "skill:mio"
    assert str(tmp_path) not in json.dumps(payload["guidance"])
    public_sources = payload["instruction_sources"]["sources"]
    assert "state" not in public_sources[0]
    assert "body" not in public_sources[0]
    assert "resolved_path_local_only" not in public_sources[0]
    assert "private amend trail" not in json.dumps(payload)


def test_profile_name_emits_registry_instruction_sources(capsys) -> None:
    code = main(["profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert payload["instruction_sources"]["active"] == [
        "AGENTS.md",
        "goal.md",
        "SESSION_HANDOFF.md",
        "analysis/workflow_checkpoint.md",
        "docs/",
        "Codex skills",
        "live tooling output",
    ]
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
    assert payload["complexity_command"] == []
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
