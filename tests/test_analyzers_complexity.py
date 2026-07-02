"""Tests for the vendored built-in complexity analyzer (moth.analyzers.complexity).

Schema-frozen contract: findings JSON keys and CLI semantics (--exclude 可多次 /
--format json) must match the upstream complexity-optimizer script byte for
byte — downstream baseline JSONs and pre_push gates consume this schema.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.skipif(not ORIGINAL_SCRIPT.exists(), reason="original analyzer script not installed")
@pytest.mark.parametrize("output_format", ["json", "markdown"])
def test_output_parity_with_original_script(tmp_path, capsys, output_format) -> None:
    # schema 等价性证明: 同一目录, 原脚本 vs moth complexity, 输出逐字节一致。
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
        [sys.executable, str(ORIGINAL_SCRIPT), str(tmp_path), "--format", output_format],
        capture_output=True,
        text=True,
        check=True,
    )
    code = main(["complexity", str(tmp_path), "--format", output_format])
    vendored_out = capsys.readouterr().out

    assert code == 0
    assert vendored_out == original.stdout
