from __future__ import annotations

from moth import report as report_module
from moth.profiles.loader import load_profile
from moth.profiles.loader import RepoProfile


def test_build_report_surfaces_tooling_evidence(monkeypatch) -> None:
    profile = load_profile("chunkymonkey")

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

    def fake_complexity(root, command):
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

    payload = report_module.build_report(profile)

    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert payload["status"] == "WARN"
    assert payload["codegraph"]["state"] == "NOT_INITIALIZED"
    assert payload["complexity"]["summary"]["finding_count"] == 1
    assert payload["complexity"]["baseline"]["status"] == "not_configured"
    assert payload["warnings"]


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

    def fake_complexity(root, command):
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
    assert any("complexity new high findings" in warning for warning in payload["warnings"])
    assert payload["issues"] == []


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

    def fake_complexity(root, command):
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

    payload = report_module.build_sync_report(profile)

    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert payload["status"] == "PASS"
    assert payload["sync"]["verdict"] == "PASS"
    assert payload["snapshot"]["status"] == "PASS"
    assert payload["snapshot"]["dirty_worktree"] == []
    assert payload["warnings"] == []


def test_build_profiles_report_summarizes_registry(monkeypatch) -> None:
    profile_ok = RepoProfile(
        kind="profile",
        name="ok",
        repo_path=load_profile("chunkymonkey").repo_path,
        codegraph_root=load_profile("chunkymonkey").codegraph_root,
        complexity_command=["python", "-m", "moth"],
        evidence_paths={},
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
    monkeypatch.setattr(report_module, "discover_profiles", lambda _root: [profile_warn])
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
    assert payload["workspace_profiles"][0]["status"] == "WARN"
