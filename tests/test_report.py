from __future__ import annotations

from moth import report as report_module
from moth.profiles.loader import load_profile


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

    payload = report_module.build_report(profile)

    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert payload["status"] == "WARN"
    assert payload["codegraph"]["state"] == "NOT_INITIALIZED"
    assert payload["complexity"]["summary"]["finding_count"] == 1
    assert payload["warnings"]


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
    monkeypatch.setattr(report_module, "git_status", lambda _repo_path: [])

    payload = report_module.build_sync_report(profile)

    assert payload["schema_version"] == 1
    assert payload["generated_at"]
    assert payload["status"] == "PASS"
    assert payload["sync"]["verdict"] == "PASS"
    assert payload["snapshot"]["status"] == "PASS"
    assert payload["snapshot"]["dirty_worktree"] == []
    assert payload["warnings"] == []
