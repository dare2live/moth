"""Tests for the vendored built-in complexity analyzer (moth.analyzers.complexity).

Schema-frozen contract: findings JSON keys remain compatible with the upstream
complexity-optimizer script. Moth additionally calibrates repository boundary
and attention ordering.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import moth.profiles.loader as profile_loader
from moth.analyzers.complexity import run as analyzer_run
from moth.cli import main

ORIGINAL_SCRIPT = Path(
    "/Users/dp/.agents/skills/complexity-optimizer/scripts/analyze_complexity.py"
)

NESTED_LOOP_SOURCE = "for x in xs:\n    for y in ys:\n        total = x + y\n"


def _write_hot_file(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "hot.py"
    target.write_text(NESTED_LOOP_SOURCE, encoding="utf-8")
    return target


def test_cli_complexity_reports_nested_loop_with_frozen_schema(tmp_path, capsys) -> None:
    _write_hot_file(tmp_path)

    code = main(["complexity", str(tmp_path), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert isinstance(payload, list) and payload
    finding = next(item for item in payload if item["kind"] == "nested-loop")
    # 冻结 schema 关键键 (baseline diff / pre_push 消费):
    for key in ("path", "line", "severity", "kind", "message", "suggestion", "confidence"):
        assert key in finding
    assert finding["severity"] == "high"
    assert finding["path"] == "hot.py"
    assert finding["line"] == 2
    assert finding["confidence"] == "high"


def test_cli_complexity_exclude_is_repeatable(tmp_path, capsys) -> None:
    _write_hot_file(tmp_path / "keep")
    _write_hot_file(tmp_path / "skip_a")
    _write_hot_file(tmp_path / "skip_b")

    code = main(
        [
            "complexity",
            str(tmp_path),
            "--exclude",
            "skip_a",
            "--exclude",
            "skip_b",
            "--format",
            "json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert {item["path"] for item in payload} == {"keep/hot.py"}


def test_cli_complexity_markdown_is_default_format(tmp_path, capsys) -> None:
    _write_hot_file(tmp_path)

    code = main(["complexity", str(tmp_path)])
    out = capsys.readouterr().out

    assert code == 0
    assert "# Complexity Hotspots" in out
    assert "## HIGH nested-loop" in out
    assert "hot.py:2" in out


def test_run_pure_function_returns_findings_total_truncated(tmp_path) -> None:
    _write_hot_file(tmp_path)

    result = analyzer_run(tmp_path)

    assert result["total"] == len(result["findings"]) >= 1
    assert result["truncated"] is False
    assert result["findings"][0]["kind"] == "nested-loop"

    limited = analyzer_run(tmp_path, max_findings=0)
    assert limited["findings"] == []
    assert limited["total"] >= 1
    assert limited["truncated"] is True


def test_run_pure_function_applies_excludes(tmp_path) -> None:
    _write_hot_file(tmp_path / "keep")
    _write_hot_file(tmp_path / "vendored_stuff")

    result = analyzer_run(tmp_path, ["vendored_stuff"])

    assert {item["path"] for item in result["findings"]} == {"keep/hot.py"}


def test_run_respects_gitignore_unless_explicitly_included(tmp_path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _write_hot_file(tmp_path / "keep")
    _write_hot_file(tmp_path / "ignored")
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")

    default = analyzer_run(tmp_path)
    broad = analyzer_run(tmp_path, include_ignored=True)

    assert {item["path"] for item in default["findings"]} == {"keep/hot.py"}
    assert {item["path"] for item in broad["findings"]} == {
        "ignored/hot.py",
        "keep/hot.py",
    }


def test_attention_order_combines_severity_and_confidence(tmp_path) -> None:
    (tmp_path / "candidate.js").write_text(
        "for (const x of xs) {\n  ys.forEach((y) => out.push(x + y));\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "bounded.py").write_text(
        "for value in values:\n    if value in computed_values():\n        pass\n",
        encoding="utf-8",
    )

    findings = analyzer_run(tmp_path)["findings"]

    assert findings[0]["confidence"] == "high"
    assert findings[0]["severity"] == "medium"
    assert any(
        item["severity"] == "high" and item["confidence"] == "low"
        for item in findings[1:]
    )


def test_cli_complexity_applies_matching_profile(tmp_path, capsys) -> None:
    _write_hot_file(tmp_path / "keep")
    _write_hot_file(tmp_path / "scripts")
    profile_dir = tmp_path / ".moth"
    profile_dir.mkdir()
    (profile_dir / "profile.yaml").write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                "repo_path: ..",
                "codegraph_root: .",
                "complexity_excludes: [scripts]",
            ]
        ),
        encoding="utf-8",
    )

    code = main(["complexity", str(tmp_path), "--format", "json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert {item["path"] for item in payload} == {"keep/hot.py"}
    assert "profile applied: sample" in captured.err


def test_cli_complexity_respects_explicit_profile_command(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    analyzer = tmp_path / "external_analyzer.py"
    analyzer.write_text(
        "import json\n"
        "print(json.dumps([{"
        "'path':'external.py','line':7,'severity':'medium',"
        "'kind':'external-check','message':'external result',"
        "'suggestion':'review','confidence':'high'}]))\n",
        encoding="utf-8",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profile_path = profile_dir / "external.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: external-sample",
                "repo_path: ../repo",
                "codegraph_root: .",
                "complexity_command:",
                f"  - {json.dumps(sys.executable)}",
                f"  - {json.dumps(str(analyzer))}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(profile_loader, "PROFILES_DIR", profile_dir)

    code = main(
        [
            "complexity",
            str(repo),
            "--profile",
            str(profile_path),
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 0
    assert [item["kind"] for item in payload] == ["external-check"]
    assert "analyzer=external" in captured.err


def test_cli_complexity_can_write_baseline(tmp_path, capsys) -> None:
    _write_hot_file(tmp_path)
    baseline = tmp_path / "config" / "complexity-baseline.json"

    code = main(
        [
            "complexity",
            str(tmp_path),
            "--format",
            "json",
            "--write-baseline",
            str(baseline),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(baseline.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["schema_version"] == "moth.complexity-baseline.v1"
    assert payload["identity_mode"] == "path_kind_message"
    assert payload["findings"]
    assert "baseline written:" in captured.err


def test_cli_has_top_level_version(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("moth 1.0.0")


@pytest.mark.skipif(not ORIGINAL_SCRIPT.exists(), reason="original analyzer script not installed")
def test_output_schema_and_findings_match_original_script(tmp_path, capsys) -> None:
    # Moth may reorder findings by confidence, but keeps the upstream schema and observations.
    _write_hot_file(tmp_path / "pkg")
    (tmp_path / "pkg" / "sorty.py").write_text(
        "for x in xs:\n    ys = sorted(x)\n    if x in computed():\n        pass\n",
        encoding="utf-8",
    )
    (tmp_path / "app.js").write_text(
        "for (const a of items) {\n    rows.forEach((b) => {\n        out.push(a + b);\n    });\n}\n",
        encoding="utf-8",
    )

    original = subprocess.run(
        [sys.executable, str(ORIGINAL_SCRIPT), str(tmp_path), "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    code = main(
        [
            "complexity",
            str(tmp_path),
            "--format",
            "json",
            "--no-profile",
            "--include-ignored",
        ]
    )
    vendored = json.loads(capsys.readouterr().out)
    upstream = json.loads(original.stdout)

    assert code == 0
    identity = lambda item: (
        item["path"],
        item["line"],
        item["severity"],
        item["kind"],
        item["message"],
        item["suggestion"],
        item["confidence"],
    )
    assert sorted(map(identity, vendored)) == sorted(map(identity, upstream))
