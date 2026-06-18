import json
import sys

from moth.adapters.complexity import command_for_target
from moth.adapters.complexity import run_analysis
from moth.adapters.complexity import run_analysis_for_paths


def test_run_analysis_summarizes_confidence(tmp_path) -> None:
    scanner = tmp_path / "scanner.py"
    scanner.write_text(
        "\n".join(
            [
                "import json",
                "print(json.dumps([",
                "  {'path': 'src/a.py', 'line': 1, 'severity': 'high', 'kind': 'nested-loop', 'message': 'hot', 'suggestion': 'index', 'confidence': 'high'},",
                "  {'path': 'src/b.js', 'line': 2, 'severity': 'medium', 'kind': 'render-derived-work', 'message': 'hot', 'suggestion': 'memo', 'confidence': 'low'},",
                "]))",
            ]
        ),
        encoding="utf-8",
    )

    result = run_analysis(tmp_path, [sys.executable, str(scanner), str(tmp_path), "--format", "markdown"])

    assert result["verdict"] == "PASS"
    assert result["summary"]["confidence_counts"] == {"high": 1, "low": 1}
    assert result["summary"]["high_confidence_count"] == 1
    assert result["summary"]["low_confidence_count"] == 1


def test_run_analysis_for_paths_scans_each_target_file(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    src = repo / "src"
    src.mkdir()
    target = src / "hot.py"
    target.write_text("for x in xs:\n    for y in ys:\n        pass\n", encoding="utf-8")
    scanner = tmp_path / "scanner.py"
    scanner.write_text(
        "\n".join(
            [
                "import json, pathlib, sys",
                "target = pathlib.Path(sys.argv[1])",
                "print(json.dumps([{'path': str(target), 'line': 1, 'severity': 'high', 'kind': 'nested-loop', 'message': 'hot', 'suggestion': 'index', 'confidence': 'high'}]))",
            ]
        ),
        encoding="utf-8",
    )
    command = [sys.executable, str(scanner), str(repo), "--format", "markdown"]

    result = run_analysis_for_paths(repo, command, ["src/hot.py"])

    assert result["verdict"] == "PASS"
    assert result["summary"]["finding_count"] == 1
    assert result["summary"]["confidence_counts"] == {"high": 1}
    assert result["files"][0]["path"] == "src/hot.py"
    assert result["findings"][0]["path"] == "src/hot.py"
    assert str(target) in result["files"][0]["command"]


def test_command_for_target_replaces_profile_repo_root(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "src" / "hot.py"
    command = [sys.executable, "/tool/scanner.py", str(repo), "--format", "markdown"]

    rewritten = command_for_target(repo, command, target)

    assert str(target) in rewritten
    assert str(repo) not in rewritten
    assert rewritten[-1] == "json"
