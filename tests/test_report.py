from __future__ import annotations

from pathlib import Path

import pytest

from moth.adapters.complexity import build_complexity_diff_report
from moth import report as report_module
from moth.profiles.loader import load_profile
from moth.profiles.loader import RepoProfile


@pytest.fixture(autouse=True)
def _coupling_pass(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "run_coupling_orphans",
        lambda _repo_path: {"verdict": "PASS", "fails": [], "warns": []},
    )


def test_build_report_surfaces_tooling_evidence(monkeypatch, tmp_path) -> None:
    codex_home = tmp_path / "codex-home"
    skill_dir = codex_home / "skills" / "mio"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: mio\ndescription: Personal collaboration lens.\n---\n# Mio\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    base_profile = load_profile("chunkymonkey")
    profile = RepoProfile(
        kind=base_profile.kind,
        name=base_profile.name,
        repo_path=base_profile.repo_path,
        codegraph_root=base_profile.codegraph_root,
        complexity_command=base_profile.complexity_command,
        complexity_baseline_path=base_profile.complexity_baseline_path,
        evidence_paths=base_profile.evidence_paths,
        instruction_sources={
            "active": ["AGENTS.md"],
            "ignored_by_default": ["CLAUDE.md"],
            "sources": [
                {
                    "id": "mio",
                    "kind": "collaboration_lens",
                    "provider": "codex_skill",
                    "ref": "skill:mio",
                    "activation": "substantive_judgment",
                    "requirement": "required_when_active",
                    "scope": "user",
                    "owner": "user",
                    "sensitivity": "personal",
                    "egress_policy": "metadata_only",
                    "state": "APPLIED_WITH_EVIDENCE",
                    "body": "private amend trail",
                    "resolved_path_local_only": str(skill_dir / "SKILL.md"),
                }
            ],
        },
        notes=base_profile.notes,
    )

    def fake_codegraph(root):
        return {
            "command": ["codegraph", "status", str(root)],
            "returncode": 0,
            "stdout": "Index Statistics:\nFiles: 10\n",
            "stderr": "",
            "verdict": "WARN",
            "state": "NOT_INITIALIZED",
            "index_up_to_date": False,
            "issues": ["codegraph not initialized"],
            "index_statistics": {"files": 10},
            "nodes_by_kind": {},
            "files_by_language": {},
        }

    def fake_complexity(root, command, **_kwargs):
        return {
            "command": list(command),
            "returncode": 0,
            "stdout": "[]",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "findings": [
                {
                    "path": "src/example.py",
                    "line": 12,
                    "severity": "high",
                    "kind": "nested-loop",
                    "message": "Nested loop may create O(n^2) or worse behavior.",
                    "suggestion": "Use an index.",
                }
            ],
            "summary": {
                "finding_count": 1,
                "severity_counts": {"high": 1},
                "kind_counts": {"nested-loop": 1},
                "high_count": 1,
                "medium_count": 0,
                "info_count": 0,
            },
        }

    monkeypatch.setattr(report_module, "run_codegraph_status", fake_codegraph)
    monkeypatch.setattr(report_module, "run_complexity_analysis", fake_complexity)
    monkeypatch.setattr(report_module, "load_complexity_baseline", lambda _path: ([], "not_configured"))
    monkeypatch.setattr(report_module, "check_profile", lambda _profile: [])
    monkeypatch.setattr(
        report_module,
        "collect_tool_evidence",
        lambda _profile: {
            "schema_version": "moth.tool-evidence.v1",
            "tools": {
                "omen": {
                    "tool": "omen",
                    "scope": "evidence_only",
                    "state": "COMPLETE",
                    "required": False,
                    "version": "4.25.0",
                    "compatible": True,
                    "compatibility_basis": "runtime_contract_probe",
                    "evidence": [],
                    "issues": [],
                }
            },
        },
    )
    monkeypatch.setattr(
        report_module,
        "build_project_model",
        lambda _repo_path, **_kwargs: {
            "schema_version": "moth.project-model.v1",
            "verdict": "PASS",
            "project": {"id": "project:moth", "name": "moth"},
            "applications": [],
            "runtimes": [],
            "modules": [],
            "evidence": [],
            "coverage": {"detectors": [], "issues": [], "warnings": []},
        },
    )

    payload = report_module.build_report(profile)

    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert payload["status"] == "WARN"
    assert payload["codegraph"]["state"] == "NOT_INITIALIZED"
    assert payload["complexity"]["summary"]["finding_count"] == 1
    assert payload["complexity"]["baseline"]["status"] == "not_configured"
    assert payload["complexity"]["scan_health"] == "PASS"
    assert payload["complexity"]["governance_state"] == "UNBASELINED"
    assert any("baseline unavailable" in warning for warning in payload["warnings"])
    assert payload["profile"]["instruction_sources"]["ignored_by_default"] == ["CLAUDE.md"]
    assert "body" not in payload["profile"]["instruction_sources"]["sources"][0]
    assert "resolved_path_local_only" not in payload["profile"]["instruction_sources"]["sources"][0]
    assert payload["guidance"]["verdict"] == "PASS"
    assert payload["guidance"]["sources"][0]["state"] == "DISCOVERED"
    assert payload["project_model"]["project"]["name"] == "moth"
    assert payload["tool_evidence"]["tools"]["omen"]["state"] == "COMPLETE"
    assert (
        payload["tool_evidence"]["tools"]["omen"]["scope"]
        == "evidence_only"
    )
    assert payload["warnings"]
    rendered = report_module.render_markdown(payload)
    assert "## Guidance" in rendered
    assert "## Project model" in rendered
    assert "## External tool evidence" in rendered
    assert "private amend trail" not in rendered
    assert str(skill_dir) not in rendered


def test_build_report_fails_on_coupling_orphans(monkeypatch) -> None:
    profile = load_profile("chunkymonkey")
    monkeypatch.setattr(report_module, "check_profile", lambda _profile: [])
    monkeypatch.setattr(report_module, "git_status", lambda _path: [])
    monkeypatch.setattr(
        report_module,
        "run_codegraph_status",
        lambda _root: {
            "command": ["codegraph", "status"],
            "returncode": 0,
            "stdout": "Index is up to date",
            "stderr": "",
            "verdict": "PASS",
            "state": "UP_TO_DATE",
            "index_up_to_date": True,
            "issues": [],
            "index_statistics": {},
            "nodes_by_kind": {},
            "files_by_language": {},
        },
    )
    monkeypatch.setattr(
        report_module,
        "run_complexity_analysis",
        lambda _root, command, **_kwargs: {
            "command": list(command),
            "returncode": 0,
            "stdout": "[]",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "findings": [],
            "summary": {"finding_count": 0, "severity_counts": {}, "kind_counts": {}, "confidence_counts": {}},
        },
    )
    monkeypatch.setattr(report_module, "load_complexity_baseline", lambda _path: ([], "not_configured"))
    monkeypatch.setattr(
        report_module,
        "run_coupling_orphans",
        lambda _repo_path: {"verdict": "FAIL", "fails": ["T4 missing file"], "warns": []},
    )

    payload = report_module.build_report(profile)
    rendered = report_module.render_markdown(payload)

    assert payload["status"] == "FAIL"
    assert payload["coupling"]["verdict"] == "FAIL"
    assert "T4 missing file" in payload["issues"]
    assert "## Coupling" in rendered


def test_build_report_warns_on_new_complexity_high_with_loaded_baseline(monkeypatch) -> None:
    profile = load_profile("chunkymonkey")

    def fake_codegraph(root):
        return {
            "command": ["codegraph", "status", str(root)],
            "returncode": 0,
            "stdout": "Index is up to date",
            "stderr": "",
            "verdict": "PASS",
            "state": "UP_TO_DATE",
            "index_up_to_date": True,
            "issues": [],
            "index_statistics": {},
            "nodes_by_kind": {},
            "files_by_language": {},
        }

    def fake_complexity(root, command, **_kwargs):
        return {
            "command": list(command),
            "returncode": 0,
            "stdout": "[]",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "findings": [
                {
                    "path": "src/stable.py",
                    "line": 12,
                    "severity": "high",
                    "kind": "nested-loop",
                    "message": "Nested loop may create O(n^2) or worse behavior.",
                    "suggestion": "Use an index.",
                },
                {
                    "path": "src/new.py",
                    "line": 42,
                    "severity": "high",
                    "kind": "nested-loop",
                    "message": "Another nested loop may create O(n^2) or worse behavior.",
                    "suggestion": "Use an index.",
                },
            ],
            "summary": {
                "finding_count": 2,
                "severity_counts": {"high": 2},
                "kind_counts": {"nested-loop": 2},
                "high_count": 2,
                "medium_count": 0,
                "info_count": 0,
            },
        }

    monkeypatch.setattr(report_module, "run_codegraph_status", fake_codegraph)
    monkeypatch.setattr(report_module, "run_complexity_analysis", fake_complexity)
    monkeypatch.setattr(report_module, "check_profile", lambda _profile: [])
    monkeypatch.setattr(
        report_module,
        "load_complexity_baseline",
        lambda _path: (
            [
                {
                    "path": "src/stable.py",
                    "line": 99,
                    "severity": "high",
                    "kind": "nested-loop",
                    "message": "Nested loop may create O(n^2) or worse behavior.",
                    "suggestion": "Use an index.",
                }
            ],
            "loaded",
        ),
    )

    payload = report_module.build_report(profile)

    assert payload["status"] == "WARN"
    assert payload["complexity"]["baseline"]["status"] == "loaded"
    assert payload["complexity"]["diff"]["status"] == "compared"
    assert payload["complexity"]["diff"]["new_high_count"] == 1
    assert payload["complexity"]["governance_state"] == "CAUTION"
    assert any("complexity new high findings" in warning for warning in payload["warnings"])
    assert payload["issues"] == []


def test_build_report_does_not_warn_on_unchanged_complexity_with_loaded_baseline(monkeypatch) -> None:
    profile = load_profile("chunkymonkey")

    def fake_codegraph(root):
        return {
            "command": ["codegraph", "status", str(root)],
            "returncode": 0,
            "stdout": "Index is up to date",
            "stderr": "",
            "verdict": "PASS",
            "state": "UP_TO_DATE",
            "index_up_to_date": True,
            "issues": [],
            "index_statistics": {},
            "nodes_by_kind": {},
            "files_by_language": {},
        }

    finding = {
        "path": "src/stable.py",
        "line": 12,
        "severity": "high",
        "kind": "nested-loop",
        "message": "Nested loop may create O(n^2) or worse behavior.",
        "suggestion": "Use an index.",
    }

    def fake_complexity(root, command, **_kwargs):
        return {
            "command": list(command),
            "returncode": 0,
            "stdout": "[]",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "findings": [finding],
            "summary": {
                "finding_count": 1,
                "severity_counts": {"high": 1},
                "kind_counts": {"nested-loop": 1},
                "high_count": 1,
                "medium_count": 0,
                "info_count": 0,
            },
        }

    monkeypatch.setattr(report_module, "run_codegraph_status", fake_codegraph)
    monkeypatch.setattr(report_module, "run_complexity_analysis", fake_complexity)
    monkeypatch.setattr(report_module, "load_complexity_baseline", lambda _path: ([finding], "loaded"))
    monkeypatch.setattr(report_module, "git_status", lambda _path: [])
    monkeypatch.setattr(report_module, "check_profile", lambda _profile: [])

    payload = report_module.build_report(profile)

    assert payload["status"] == "PASS"
    assert payload["complexity"]["diff"]["status"] == "compared"
    assert payload["complexity"]["diff"]["new_high_count"] == 0
    assert payload["complexity"]["governance_state"] == "STABLE"
    assert payload["warnings"] == []
    assert payload["issues"] == []


def test_build_report_compares_disjoint_complexity_roots(monkeypatch) -> None:
    profile = load_profile("chunkymonkey")

    def fake_codegraph(root):
        return {
            "command": ["codegraph", "status", str(root)],
            "returncode": 0,
            "stdout": "Index is up to date",
            "stderr": "",
            "verdict": "PASS",
            "state": "UP_TO_DATE",
            "index_up_to_date": True,
            "issues": [],
            "index_statistics": {},
            "nodes_by_kind": {},
            "files_by_language": {},
        }

    def fake_complexity(root, command, **_kwargs):
        return {
            "command": list(command),
            "returncode": 0,
            "stdout": "[]",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "findings": [
                {
                    "path": "assets/js/app.js",
                    "line": 12,
                    "severity": "high",
                    "kind": "nested-or-callback-loop",
                    "message": "Loop or array iteration appears inside another loop/callback.",
                    "suggestion": "Use an index.",
                },
            ],
            "summary": {
                "finding_count": 1,
                "severity_counts": {"high": 1},
                "kind_counts": {"nested-or-callback-loop": 1},
                "high_count": 1,
                "medium_count": 0,
                "info_count": 0,
            },
        }

    monkeypatch.setattr(report_module, "run_codegraph_status", fake_codegraph)
    monkeypatch.setattr(report_module, "run_complexity_analysis", fake_complexity)
    monkeypatch.setattr(report_module, "check_profile", lambda _profile: [])
    monkeypatch.setattr(
        report_module,
        "load_complexity_baseline",
        lambda _path: (
            [
                {
                    "path": "scripts/legacy.py",
                    "line": 99,
                    "severity": "HIGH",
                    "kind": "nested-loop",
                    "finding": "Nested loop may create O(n^2) or worse behavior.",
                    "suggestion": "Use an index.",
                }
            ],
            "loaded",
        ),
    )

    payload = report_module.build_report(profile)
    diff = payload["complexity"]["diff"]

    assert payload["status"] == "WARN"
    assert diff["status"] == "compared"
    assert diff["new_high_count"] == 1
    assert diff["new_count"] == 1
    assert diff["resolved_count"] == 1
    assert any("complexity new high findings" in warning for warning in payload["warnings"])
    assert not any("complexity baseline incompatible" in warning for warning in payload["warnings"])
    assert payload["issues"] == []


def test_complexity_diff_normalizes_absolute_paths_against_repo_root() -> None:
    diff = build_complexity_diff_report(
        [
            {
                "path": "src/moth/report.py",
                "line": 12,
                "severity": "high",
                "kind": "nested-loop",
                "message": "Nested loop may create O(n^2) or worse behavior.",
            }
        ],
        [
            {
                "path": "/Users/dp/Documents/M/moth/src/moth/report.py",
                "line": 99,
                "severity": "HIGH",
                "kind": "nested-loop",
                "finding": "Nested loop may create O(n^2) or worse behavior.",
            }
        ],
        baseline_status="loaded",
        repo_root="/Users/dp/Documents/M/moth",
    )

    assert diff["status"] == "compared"
    assert diff["unchanged_count"] == 1
    assert diff["new_count"] == 0
    assert diff["resolved_count"] == 0
    assert diff["new_high_count"] == 0


def test_build_sync_report_combines_sync_and_snapshot(monkeypatch) -> None:
    profile = load_profile("chunkymonkey")

    def fake_sync(root):
        return {
            "command": ["codegraph", "sync", str(root)],
            "returncode": 0,
            "stdout": "synced",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
        }

    def fake_codegraph(root):
        return {
            "command": ["codegraph", "status", str(root)],
            "returncode": 0,
            "stdout": "Index is up to date",
            "stderr": "",
            "verdict": "PASS",
            "state": "UP_TO_DATE",
            "index_up_to_date": True,
            "issues": [],
            "index_statistics": {},
            "nodes_by_kind": {},
            "files_by_language": {},
        }

    def fake_complexity(root, command, **_kwargs):
        return {
            "command": list(command),
            "returncode": 0,
            "stdout": "[]",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "findings": [],
            "summary": {
                "finding_count": 0,
                "severity_counts": {},
                "kind_counts": {},
                "high_count": 0,
                "medium_count": 0,
                "info_count": 0,
            },
        }

    monkeypatch.setattr(report_module, "run_codegraph_sync", fake_sync)
    monkeypatch.setattr(report_module, "run_codegraph_status", fake_codegraph)
    monkeypatch.setattr(report_module, "run_complexity_analysis", fake_complexity)
    monkeypatch.setattr(report_module, "load_complexity_baseline", lambda _path: ([], "not_configured"))
    monkeypatch.setattr(report_module, "git_status", lambda _repo_path: [])
    monkeypatch.setattr(report_module, "check_profile", lambda _profile: [])

    payload = report_module.build_sync_report(profile)

    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert payload["status"] == "PASS"
    assert payload["sync"]["verdict"] == "PASS"
    assert payload["snapshot"]["status"] == "PASS"
    assert payload["snapshot"]["dirty_worktree"] == []
    assert payload["warnings"] == []


def test_build_affected_report_combines_codegraph_and_complexity(monkeypatch) -> None:
    profile = load_profile("chunkymonkey")

    def fake_affected(root, files, *, depth=5, test_filter=None):
        return {
            "command": ["codegraph", "affected", "--path", str(root), "--json", *files],
            "returncode": 0,
            "stdout": "{}",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "changedFiles": files,
            "affectedTests": ["tests/test_example.py"],
            "totalDependentsTraversed": 3,
        }

    def fake_complexity(root, command, files, **_kwargs):
        return {
            "command_template": list(command),
            "verdict": "PASS",
            "issues": [],
            "files": [
                {
                    "path": files[0],
                    "verdict": "PASS",
                    "issues": [],
                    "findings": [],
                    "summary": {"finding_count": 0, "severity_counts": {}, "confidence_counts": {}},
                }
            ],
            "findings": [
                {
                    "path": files[0],
                    "line": 7,
                    "severity": "high",
                    "kind": "nested-loop",
                    "message": "Nested loop may create O(n^2) or worse behavior.",
                    "suggestion": "Use an index.",
                    "confidence": "high",
                }
            ],
            "summary": {
                "finding_count": 1,
                "severity_counts": {"high": 1},
                "kind_counts": {"nested-loop": 1},
                "confidence_counts": {"high": 1},
                "high_count": 1,
                "medium_count": 0,
                "info_count": 0,
            },
        }

    monkeypatch.setattr(report_module, "run_codegraph_affected", fake_affected)
    monkeypatch.setattr(report_module, "run_complexity_analysis_for_paths", fake_complexity)

    payload = report_module.build_affected_report(profile, ["src/new.py"])
    rendered = report_module.render_affected_markdown(payload)

    assert payload["status"] == "WARN"
    assert payload["codegraph_affected"]["affectedTests"] == ["tests/test_example.py"]
    assert payload["complexity"]["summary"]["confidence_counts"] == {"high": 1}
    assert any("complexity hotspots in affected files" in warning for warning in payload["warnings"])
    assert "Confidence counts" in rendered


def test_build_affected_report_does_not_green_empty_unknown_test_coverage(
    monkeypatch,
) -> None:
    profile = load_profile("chunkymonkey")
    monkeypatch.setattr(
        report_module,
        "run_codegraph_affected",
        lambda *_args, **_kwargs: {
            "verdict": "PASS",
            "issues": [],
            "affectedTests": [],
            "totalDependentsTraversed": 0,
        },
    )
    monkeypatch.setattr(
        report_module,
        "run_complexity_analysis_for_paths",
        lambda *_args, **_kwargs: {
            "verdict": "PASS",
            "issues": [],
            "findings": [],
            "summary": {"finding_count": 0},
        },
    )

    payload = report_module.build_affected_report(
        profile, ["src/moth/visual_model.py"]
    )

    assert payload["status"] == "WARN"
    assert payload["affected_test_coverage"] == "UNKNOWN_EMPTY"
    assert payload["coverage_complete"] is False
    assert any("coverage unknown" in item for item in payload["warnings"])


def test_build_profiles_report_summarizes_registry(monkeypatch) -> None:
    profile_ok = RepoProfile(
        kind="profile",
        name="ok",
        repo_path=load_profile("chunkymonkey").repo_path,
        codegraph_root=load_profile("chunkymonkey").codegraph_root,
        complexity_command=["python", "-m", "moth"],
        evidence_paths={},
        instruction_sources={"active": ["AGENTS.md"], "ignored_by_default": ["CLAUDE.md"]},
        notes="ready",
    )
    profile_warn = RepoProfile(
        kind="profile",
        name="warn",
        repo_path=load_profile("chunkymonkey").repo_path / "missing",
        codegraph_root=load_profile("chunkymonkey").codegraph_root,
        complexity_command=[],
        evidence_paths={},
        notes="needs attention",
    )

    monkeypatch.setattr(report_module, "list_profiles", lambda: [profile_ok])
    # build_profiles_report 现在走带失败清单的入口(一份坏 profile 不得带走整批, 且必须点名)
    monkeypatch.setattr(
        report_module, "discover_profiles_with_failures", lambda _root: ([profile_warn], [])
    )
    monkeypatch.setattr(report_module, "check_profile", lambda profile: [] if profile.name == "ok" else ["missing complexity command"])

    payload = report_module.build_profiles_report("/tmp/workspace")

    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert payload["status"] == "WARN"
    assert payload["workspace_root"] == "/tmp/workspace"
    assert payload["summary"]["registry_total"] == 1
    assert payload["summary"]["registry_pass_count"] == 1
    assert payload["summary"]["registry_warn_count"] == 0
    assert payload["summary"]["workspace_total"] == 1
    assert payload["summary"]["workspace_pass_count"] == 0
    assert payload["summary"]["workspace_warn_count"] == 1
    assert payload["registry_profiles"][0]["status"] == "PASS"
    assert payload["registry_profiles"][0]["instruction_sources"]["ignored_by_default"] == ["CLAUDE.md"]
    assert payload["workspace_profiles"][0]["status"] == "WARN"


def _fake_codegraph_pass(root):
    return {
        "command": ["codegraph", "status", str(root)],
        "returncode": 0,
        "stdout": "Index is up to date",
        "stderr": "",
        "verdict": "PASS",
        "state": "UP_TO_DATE",
        "index_up_to_date": True,
        "issues": [],
        "index_statistics": {},
        "nodes_by_kind": {},
        "files_by_language": {},
    }


def test_build_report_uses_builtin_analyzer_when_no_command(tmp_path, monkeypatch) -> None:
    # profile 未配置 complexity_command → 内建分析器真跑 (进程内), 不 SKIP 不 FAIL。
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hot.py").write_text(
        "for x in xs:\n    for y in ys:\n        total = x + y\n", encoding="utf-8"
    )
    profile = RepoProfile(kind="profile", name="builtin-sample", repo_path=repo, codegraph_root=repo)
    monkeypatch.setattr(report_module, "run_codegraph_status", _fake_codegraph_pass)
    monkeypatch.setattr(report_module, "git_status", lambda _path: [])

    payload = report_module.build_report(profile)

    assert payload["complexity"]["verdict"] == "PASS"
    assert payload["complexity"]["command"][0] == "<builtin:moth.analyzers.complexity>"
    assert payload["complexity"]["summary"]["finding_count"] >= 1
    assert payload["complexity"]["baseline"]["status"] == "not_configured"
    # startup check 不再把缺 complexity_command 当问题。
    assert payload["issues"] == []
    assert any("complexity hotspots" in warning for warning in payload["warnings"])
    assert payload["status"] == "WARN"


def test_build_report_notes_ignored_excludes_with_explicit_command(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = RepoProfile(
        kind="profile",
        name="explicit-sample",
        repo_path=repo,
        codegraph_root=repo,
        complexity_command=["python", "/tool/scanner.py", str(repo), "--format", "markdown"],
        complexity_excludes=[".venv_scrape"],
    )
    monkeypatch.setattr(report_module, "run_codegraph_status", _fake_codegraph_pass)
    monkeypatch.setattr(report_module, "git_status", lambda _path: [])
    monkeypatch.setattr(
        report_module,
        "run_complexity_analysis",
        lambda _root, command, **_kwargs: {
            "command": list(command),
            "returncode": 0,
            "stdout": "[]",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "findings": [],
            "summary": {"finding_count": 0, "severity_counts": {}, "kind_counts": {}, "confidence_counts": {}},
        },
    )

    payload = report_module.build_report(profile)

    assert any("complexity_excludes is ignored" in warning for warning in payload["warnings"])
    assert payload["status"] == "WARN"
