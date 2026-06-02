import yaml

from moth.cli import main


def test_snapshot_emits_json_for_chunkymonkey(capsys) -> None:
    code = main(["snapshot", "--repo", "/Users/dp/Documents/M/stock/chunkymonkey", "--profile", "chunkymonkey", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"codegraph"' in captured.out
    assert '"complexity"' in captured.out


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
        lambda: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "profiles": [],
            "summary": {"total": 0, "pass_count": 0, "warn_count": 0},
            "issues": [],
            "warnings": [],
        },
    )
    code = main(["profiles", "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert '"schema_version"' in captured.out
    assert '"profiles"' in captured.out


def test_profiles_emits_markdown(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "moth.cli.build_profiles_report",
        lambda: {
            "schema_version": 1,
            "generated_at": "2026-06-02T12:00:00Z",
            "status": "PASS",
            "profiles": [
                {
                    "name": "chunkymonkey",
                    "repo_path": "/Users/dp/Documents/M/stock/chunkymonkey",
                    "codegraph_root": "/Users/dp/Documents/M/stock/chunkymonkey",
                    "notes": "Controller-first profile for the main stock repo.",
                    "status": "PASS",
                    "issues": [],
                }
            ],
            "summary": {"total": 1, "pass_count": 1, "warn_count": 0},
            "issues": [],
            "warnings": [],
        },
    )
    code = main(["profiles", "--format", "markdown"])
    captured = capsys.readouterr()
    assert code == 0
    assert "# Moth profiles" in captured.out
    assert "chunkymonkey" in captured.out


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
