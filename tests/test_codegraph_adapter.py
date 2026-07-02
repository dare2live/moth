import subprocess

from moth.adapters import codegraph


def test_status_command_requests_json() -> None:
    assert codegraph.status_command("/repo") == ["codegraph", "status", "/repo", "--json"]


def test_status_json_reports_pending_changes_as_stale(monkeypatch) -> None:
    stdout = (
        '{"initialized":true,"version":"1.1.3","projectPath":"/repo",'
        '"indexPath":"/repo/.codegraph","lastIndexed":"2026-06-29T00:00:00.000Z",'
        '"fileCount":27,"nodeCount":295,"edgeCount":658,"dbSizeBytes":1003520,'
        '"backend":"node-sqlite","journalMode":"wal",'
        '"nodesByKind":{"function":142},"languages":["python"],'
        '"pendingChanges":{"added":1,"modified":2,"removed":0},'
        '"worktreeMismatch":null,'
        '"index":{"builtWithVersion":"1.0.1","currentExtractionVersion":24,'
        '"reindexRecommended":false}}'
    )

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=stdout, stderr=""),
    )

    result = codegraph.run_status("/repo")

    assert result["verdict"] == "WARN"
    assert result["state"] == "STALE"
    assert result["version"] == "1.1.3"
    assert result["index_statistics"]["files"] == 27
    assert result["nodes_by_kind"] == {"function": 142}
    assert result["pending_changes"] == {"added": 1, "modified": 2, "removed": 0}
    assert result["issues"] == ["codegraph pending changes: added=1, modified=2, removed=0"]


def test_query_and_explore_commands_use_current_codegraph_path_option() -> None:
    assert codegraph.query_command("/repo", "Service") == [
        "codegraph",
        "query",
        "Service",
        "--path",
        "/repo",
    ]
    assert codegraph.context_command("/repo", "Service flow") == [
        "codegraph",
        "explore",
        "Service flow",
        "--path",
        "/repo",
    ]
    assert codegraph.explore_command("/repo", "Service flow", max_files=3) == [
        "codegraph",
        "explore",
        "Service flow",
        "--path",
        "/repo",
        "--max-files",
        "3",
    ]
