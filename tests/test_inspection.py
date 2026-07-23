from types import SimpleNamespace
import json

from moth import inspection as inspection_module


def test_one_inspection_separates_project_health_from_context_readiness(
    monkeypatch, tmp_path
) -> None:
    profile = SimpleNamespace(instruction_sources={"sources": []})
    monkeypatch.setattr(
        inspection_module,
        "build_snapshot",
        lambda _profile: {"status": "PASS", "issues": [], "warnings": []},
    )
    monkeypatch.setattr(
        inspection_module,
        "prepare_task_context",
        lambda *_args, **_kwargs: {
            "schema_version": "moth.orchestration.v1",
            "registry": {"verdict": "PASS"},
            "guidance": {"verdict": "PASS"},
            "decision_context": {
                "context_readiness": "BLOCKED",
                "missing_required_sources": ["mio", "architect-controller"],
            },
        },
    )

    result = inspection_module.build_inspection(
        profile,
        task_kind="architecture_orchestration",
        run_id="run-001",
        receipts=[],
        codex_home=tmp_path,
    )

    assert result["schema_version"] == "moth.inspection.v1"
    assert result["status"] == "NEEDS_EXECUTOR"
    assert result["project_health"] == "PASS"
    assert result["context_readiness"] == "BLOCKED"
    assert result["snapshot"]["status"] == "PASS"


def test_inspection_failure_precedes_executor_need(monkeypatch, tmp_path) -> None:
    profile = SimpleNamespace(instruction_sources={"sources": []})
    monkeypatch.setattr(
        inspection_module,
        "build_snapshot",
        lambda _profile: {"status": "FAIL", "issues": ["broken"], "warnings": []},
    )
    monkeypatch.setattr(
        inspection_module,
        "prepare_task_context",
        lambda *_args, **_kwargs: {
            "schema_version": "moth.orchestration.v1",
            "registry": {"verdict": "PASS"},
            "guidance": {"verdict": "PASS"},
            "decision_context": {
                "context_readiness": "BLOCKED",
                "missing_required_sources": ["mio"],
            },
        },
    )

    result = inspection_module.build_inspection(
        profile,
        task_kind="substantive_judgment",
        run_id="run-002",
        receipts=[],
        codex_home=tmp_path,
    )

    assert result["status"] == "FAIL"
    assert result["project_health"] == "FAIL"
    assert result["context_readiness"] == "BLOCKED"


def test_inspection_public_snapshot_strips_paths_and_raw_streams(monkeypatch, tmp_path) -> None:
    profile = SimpleNamespace(instruction_sources={"sources": []})
    monkeypatch.setattr(
        inspection_module,
        "build_snapshot",
        lambda _profile: {
            "schema_version": 1,
            "status": "PASS",
            "issues": [],
            "warnings": [],
            "profile": {"repo_path": "/Users/private/repo"},
            "dirty_worktree": ["/Users/private/secret.py"],
            "codegraph": {
                "verdict": "PASS",
                "state": "UP_TO_DATE",
                "stdout": "private@example.test",
                "rendered_stdout": "/Users/private/index",
                "command": ["/Users/private/bin"],
            },
            "complexity": {
                "verdict": "PASS",
                "summary": {"finding_count": 0},
                "stdout": "secret",
            },
            "coupling": {"verdict": "PASS", "fails": [], "warns": []},
            "assertions": {"verdict": "PASS", "totals": {}},
        },
    )
    monkeypatch.setattr(
        inspection_module,
        "prepare_task_context",
        lambda *_args, **_kwargs: {
            "schema_version": "moth.orchestration.v1",
            "registry": {"verdict": "PASS"},
            "guidance": {"verdict": "PASS"},
            "decision_context": {"context_readiness": "READY"},
        },
    )

    result = inspection_module.build_inspection(
        profile,
        task_kind="mechanical",
        run_id="run-safe",
        receipts=[],
        codex_home=tmp_path,
    )
    serialized = json.dumps(result)

    assert "/Users/private" not in serialized
    assert "private@example.test" not in serialized
    assert '"stdout"' not in serialized
    assert '"command"' not in serialized


def test_minimal_failure_snapshot_also_redacts_private_issue_text(
    monkeypatch, tmp_path
) -> None:
    profile = SimpleNamespace(instruction_sources={"sources": []})
    monkeypatch.setattr(
        inspection_module,
        "build_snapshot",
        lambda _profile: {
            "status": "FAIL",
            "issues": ["missing /Users/private/secret.json"],
            "warnings": ["owner dp@example.com"],
        },
    )
    monkeypatch.setattr(
        inspection_module,
        "prepare_task_context",
        lambda *_args, **_kwargs: {
            "decision_context": {"context_readiness": "BLOCKED"},
        },
    )

    result = inspection_module.build_inspection(
        profile,
        task_kind="mechanical",
        run_id="run-safe",
        receipts=[],
        codex_home=tmp_path,
    )
    serialized = json.dumps(result)

    assert "/Users/private" not in serialized
    assert "dp@example.com" not in serialized


def test_public_text_redacts_portable_absolute_paths_without_damaging_urls() -> None:
    text = inspection_module.sanitize_public_text(
        "missing /etc/passwd, /opt/private/data, "
        r"C:\Users\private\secret.txt and \\server\share\secret; "
        "docs https://example.test/reference/path"
    )

    assert "/etc/passwd" not in text
    assert "/opt" not in text
    assert r"C:\Users" not in text
    assert r"\\server\share" not in text
    assert text.count("<private-path>") == 4
    assert "https://example.test/reference/path" in text


def test_public_snapshot_recursively_redacts_nested_tool_and_cycle_details(
    monkeypatch, tmp_path
) -> None:
    profile = SimpleNamespace(instruction_sources={"sources": []})
    monkeypatch.setattr(
        inspection_module,
        "build_snapshot",
        lambda _profile: {
            "status": "WARN",
            "issues": [],
            "warnings": [],
            "import_cycles": {"note": "scanned /Users/private/repo"},
            "tool_evidence": {
                "tools": {
                    "fake": {
                        "issues": [
                            r"failed C:\Users\private\bin.exe",
                            "fallback /opt/private/tool",
                        ]
                    }
                }
            },
        },
    )
    monkeypatch.setattr(
        inspection_module,
        "prepare_task_context",
        lambda *_args, **_kwargs: {
            "decision_context": {
                "context_readiness": "READY",
                "detail": "receipt at /etc/moth/receipt.json",
            },
        },
    )

    result = inspection_module.build_inspection(
        profile,
        task_kind="mechanical",
        run_id="run-safe",
        receipts=[],
        codex_home=tmp_path,
    )
    serialized = json.dumps(result)

    assert "/Users/private" not in serialized
    assert "/opt/private" not in serialized
    assert "/etc/moth" not in serialized
    assert "C:\\\\Users" not in serialized
    assert serialized.count("<private-path>") == 4
