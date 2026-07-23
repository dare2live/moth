import json
import subprocess
from pathlib import Path

import pytest

from moth.adapters import omen


FIXTURES = Path(__file__).parent / "fixtures" / "omen"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _configured_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = tmp_path / "explicit-omen.toml"
    config.write_text("", encoding="utf-8")
    return repo, config


def test_commands_are_explicit_uncached_and_bounded() -> None:
    command = omen.hotspot_command("/repo", "/config/omen.toml", top=250)

    assert command == [
        "omen",
        "--path",
        "/repo",
        "--format",
        "json",
        "--compact",
        "--config",
        "/config/omen.toml",
        "--no-cache",
        "hotspot",
        "--top",
        "100",
    ]
    assert omen.changes_command("/repo", "/config/omen.toml", top=3)[-3:] == [
        "changes",
        "--top",
        "3",
    ]
    assert omen.hotspot_command(
        "/repo", "/config/omen.toml", top=float("inf")
    )[-1] == "1"


def test_diff_requires_an_explicit_target() -> None:
    assert omen.diff_command("/repo", "/config/omen.toml", target="origin/main")[-3:] == [
        "diff",
        "--target",
        "origin/main",
    ]

    try:
        omen.diff_command("/repo", "/config/omen.toml", target="")
    except ValueError as exc:
        assert "explicit diff target" in str(exc)
    else:
        raise AssertionError("diff without a target must be rejected")


def test_official_hotspot_moderate_severity_is_preserved(tmp_path: Path) -> None:
    result = omen.normalize_hotspots(
        {
            "hotspots": [
                {
                    "file": "src/example.py",
                    "severity": "Moderate",
                    "score": 0.42,
                    "avg_complexity": 2.0,
                    "commits": 1,
                }
            ],
            "summary": {},
        },
        tmp_path,
    )

    assert result["findings"][0]["severity"] == "moderate"


def test_run_evidence_strips_all_omen_environment_and_normalizes_payloads(
    tmp_path: Path, monkeypatch
) -> None:
    repo, config = _configured_repo(tmp_path)
    calls: list[tuple[list[str], dict[str, str]]] = []
    outputs = iter(
        [
            ("omen 4.25.0\n", ""),
            (_fixture("hotspot-4.25.0.json"), ""),
            (_fixture("changes-4.25.0.json"), ""),
        ]
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["environment"]))
        stdout, stderr = next(outputs)
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=stderr)

    monkeypatch.setenv("OMEN_CONFIG", "/private/shadow.toml")
    monkeypatch.setenv("OMEN_CACHE_DIR", "/private/cache")
    monkeypatch.setattr(omen, "run_safe_process", fake_run)

    result = omen.run_evidence(repo, config, top=2)

    assert result["state"] == "COMPLETE"
    assert result["version"] == "4.25.0"
    assert result["compatible"] is True
    assert [item["kind"] for item in result["evidence"]] == ["hotspot", "changes"]
    assert result["evidence"][0]["findings"][0]["file"] == "src/moth/cli.py"
    serialized = json.dumps(result)
    assert "Private Person" not in serialized
    assert "private@example.test" not in serialized
    assert "private release details" not in serialized
    assert '"author"' not in serialized
    assert '"message"' not in serialized
    assert all(not any(key.startswith("OMEN_") for key in env) for _, env in calls)
    assert all("--no-cache" in command and "--config" in command for command, _ in calls[1:])


@pytest.mark.parametrize("relative", [Path("omen.toml"), Path(".omen") / "omen.toml"])
def test_run_evidence_fails_closed_on_unconfigured_shadow_config(
    tmp_path: Path, monkeypatch, relative: Path
) -> None:
    repo, config = _configured_repo(tmp_path)
    (repo / relative).parent.mkdir(parents=True, exist_ok=True)
    (repo / relative).write_text("", encoding="utf-8")
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("shadow config must block execution")

    monkeypatch.setattr(omen, "run_safe_process", fake_run)

    result = omen.run_evidence(repo, config)

    assert result["state"] == "BLOCKED_SHADOW_CONFIG"
    assert result["issues"] == [
        f"unconfigured Omen config detected: {relative.as_posix()}"
    ]
    assert calls == 0


def test_configured_repo_config_is_not_misclassified_as_shadow(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / "omen.toml"
    config.write_text("", encoding="utf-8")
    outputs = iter(
        [
            "omen 4.25.0\n",
            _fixture("hotspot-4.25.0.json"),
            _fixture("changes-4.25.0.json"),
        ]
    )
    monkeypatch.setattr(
        omen,
        "run_safe_process",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=next(outputs), stderr=""
        ),
    )

    assert omen.run_evidence(repo, config)["state"] == "COMPLETE"


def test_unparsed_version_does_not_block_capability_probe_and_future_version_works(
    tmp_path: Path, monkeypatch
) -> None:
    repo, config = _configured_repo(tmp_path)
    calls: list[list[str]] = []

    outputs = iter(
        [
            "omen nightly build\n",
            _fixture("hotspot-4.25.0.json"),
            _fixture("changes-4.25.0.json"),
        ]
    )

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout=next(outputs), stderr=""
        )

    monkeypatch.setattr(omen, "run_safe_process", fake_run)

    unknown = omen.run_evidence(repo, config)

    assert unknown["state"] == "COMPLETE"
    assert unknown["version"] is None
    assert unknown["version_state"] == "UNPARSED"
    assert unknown["compatible"] is True
    assert len(calls) == 3

    calls.clear()
    outputs = iter(
        [
            "omen 9.1.0\n",
            _fixture("hotspot-4.25.0.json"),
            _fixture("changes-4.25.0.json"),
        ]
    )

    def future_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=next(outputs),
            stderr="",
        )

    monkeypatch.setattr(omen, "run_safe_process", future_run)
    future = omen.run_evidence(repo, config)

    assert future["state"] == "COMPLETE"
    assert future["version"] == "9.1.0"
    assert future["compatible"] is True
    assert future["compatibility_basis"] == "runtime_contract_probe"
    assert len(calls) == 3


def test_missing_binary_timeout_nonzero_and_bad_json_are_structured(
    tmp_path: Path, monkeypatch
) -> None:
    repo, config = _configured_repo(tmp_path)

    monkeypatch.setattr(
        omen,
        "run_safe_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    missing = omen.run_evidence(repo, config)
    assert missing["state"] == "BINARY_UNAVAILABLE"
    assert "stdout" not in missing and "stderr" not in missing

    monkeypatch.setattr(
        omen,
        "run_safe_process",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(cmd=["omen"], timeout=1)
        ),
    )
    timed_out = omen.run_evidence(repo, config)
    assert timed_out["state"] == "TIMEOUT"

    outputs = iter(
        [
            subprocess.CompletedProcess(["omen"], 0, stdout="omen 4.25.0\n", stderr=""),
            subprocess.CompletedProcess(
                ["omen"], 7, stdout='{"secret":"raw"}', stderr="private stderr"
            ),
        ]
    )
    monkeypatch.setattr(omen, "run_safe_process", lambda *args, **kwargs: next(outputs))
    nonzero = omen.run_evidence(repo, config)
    assert nonzero["state"] == "FAILED"
    assert nonzero["evidence"][0] == {
        "kind": "hotspot",
        "state": "COMMAND_FAILED",
        "exit_code": 7,
    }
    assert "private stderr" not in json.dumps(nonzero)
    assert '"secret"' not in json.dumps(nonzero)

    outputs = iter(
        [
            subprocess.CompletedProcess(["omen"], 0, stdout="omen 4.25.0\n", stderr=""),
            subprocess.CompletedProcess(["omen"], 0, stdout="not-json", stderr=""),
        ]
    )
    monkeypatch.setattr(omen, "run_safe_process", lambda *args, **kwargs: next(outputs))
    malformed = omen.run_evidence(repo, config)
    assert malformed["state"] == "FAILED"
    assert malformed["evidence"][0] == {
        "kind": "hotspot",
        "state": "MALFORMED_OUTPUT",
    }


def test_changes_normalization_drops_pii_and_caps_records(tmp_path: Path) -> None:
    repo, _ = _configured_repo(tmp_path)
    payload = json.loads(_fixture("changes-4.25.0.json"))
    payload["commits"] *= 120
    payload["commits"][0]["files_modified"].append("/Users/private/secret.py")
    payload["commits"][0]["files_modified"].append("../outside.py")
    payload["commits"][0]["files_modified"].append('"Moth_Next_\\345\\244.md"')

    normalized = omen.normalize_changes(payload, repo, limit=100)

    assert len(normalized["findings"]) == 100
    assert normalized["truncated"] is True
    serialized = json.dumps(normalized)
    assert "Private Person" not in serialized
    assert "private@example.test" not in serialized
    assert "/Users/private" not in serialized
    assert "../outside.py" not in serialized
    assert "a@b.co" not in serialized
    assert "\\345\\244" not in serialized
    assert "recommendations" not in serialized


def test_invalid_records_and_enum_pii_fail_closed(tmp_path: Path) -> None:
    repo, _ = _configured_repo(tmp_path)

    with pytest.raises(ValueError):
        omen.normalize_hotspots({"hotspots": [{"author": "secret"}]}, repo)
    with pytest.raises(ValueError):
        omen.normalize_changes(
            {"commits": [{"author": "secret", "message": "secret"}]}, repo
        )

    with pytest.raises(ValueError):
        omen.normalize_hotspots(
            {
                "hotspots": [
                    {
                        "file": "src/moth/cli.py",
                        "severity": "a@b.co",
                        "score": 0.9,
                    }
                ]
            },
            repo,
        )
    with pytest.raises(ValueError):
        omen.normalize_changes(
            {
                "commits": [
                    {
                        "commit_hash": "abcdef1234567",
                        "risk_level": "a@b.co",
                        "risk_score": 0.5,
                    }
                ]
            },
            repo,
        )
    with pytest.raises(ValueError):
        omen.normalize_diff({"level": "a@b.co", "score": 0.5})


def test_diff_is_opt_in_and_normalized(tmp_path: Path, monkeypatch) -> None:
    repo, config = _configured_repo(tmp_path)
    outputs = iter(
        [
            "omen 4.25.0\n",
            _fixture("hotspot-4.25.0.json"),
            _fixture("changes-4.25.0.json"),
            _fixture("diff-4.25.0.json"),
        ]
    )
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(omen, "run_safe_process", fake_run)

    result = omen.run_evidence(repo, config, diff_target="origin/main")

    assert [item["kind"] for item in result["evidence"]] == [
        "hotspot",
        "changes",
        "diff",
    ]
    assert calls[-1][-3:] == ["diff", "--target", "origin/main"]
    assert result["evidence"][-1]["finding"]["level"] == "medium"


def test_invalid_paths_are_structured_and_do_not_execute(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    def fake_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("invalid request must not execute")

    monkeypatch.setattr(omen, "run_safe_process", fake_run)

    missing_repo = omen.run_evidence(tmp_path / "missing-repo", tmp_path / "missing.toml")
    assert missing_repo["state"] == "INVALID_REQUEST"
    assert missing_repo["issues"] == ["repository path is not a directory"]

    repo = tmp_path / "repo"
    repo.mkdir()
    missing_config = omen.run_evidence(repo, tmp_path / "missing.toml")
    assert missing_config["state"] == "INVALID_REQUEST"
    assert missing_config["issues"] == ["explicit Omen config is not a file"]
    assert calls == 0
