import json
import sys

from moth.adapters import complexity as complexity_adapter
from moth.adapters.complexity import DEFAULT_IGNORED_PATH_PARTS
from moth.adapters.complexity import build_complexity_diff_report
from moth.adapters.complexity import command_for_target
from moth.adapters.complexity import run_analysis
from moth.adapters.complexity import run_analysis_for_paths


def _finding(path: str, line: int = 1, severity: str = "high") -> dict:
    return {
        "path": path,
        "line": line,
        "severity": severity,
        "kind": "nested-loop",
        "message": f"hot at {path}",
        "suggestion": "index",
    }


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


def test_diff_ignores_worktree_copies_by_default() -> None:
    # 回归 (lifehack 实战): .claude/worktrees/ 里的 agent worktree 副本被扫出
    # 大批假 new_high 拦 push; 默认排除后 new_high 不计入且计数显式上报。
    current = [
        _finding("src/real.py"),
        _finding(".claude/worktrees/agent-a/src/real.py"),
        _finding(".claude/worktrees/agent-b/src/other.py"),
        _finding("node_modules/pkg/index.js"),
    ]
    baseline = [_finding("src/real.py")]

    diff = build_complexity_diff_report(current, baseline, baseline_status="loaded")

    assert diff["status"] == "compared"
    assert diff["new_count"] == 0
    assert diff["new_high_count"] == 0
    assert diff["current_count"] == 1
    assert diff["ignored_count"] == 3
    assert diff["unchanged_count"] == 1


def test_diff_ignored_parts_filter_baseline_too_and_can_be_disabled() -> None:
    current = [_finding("src/real.py")]
    baseline = [_finding("src/real.py"), _finding(".claude/worktrees/agent-a/src/stale.py")]

    filtered = build_complexity_diff_report(current, baseline, baseline_status="loaded")
    assert filtered["ignored_count"] == 1
    assert filtered["resolved_count"] == 0

    # 显式空列表 = 关闭过滤 (向后可控): worktree 条目按普通 finding 参与比对。
    unfiltered = build_complexity_diff_report(
        current, baseline, baseline_status="loaded", ignored_path_parts=[]
    )
    assert unfiltered["ignored_count"] == 0
    assert unfiltered["resolved_count"] == 1


def test_diff_default_parameters_backward_compatible() -> None:
    # 不含 ignored 路径的 findings: 默认参数下行为与旧版一致, 仅多 ignored_count=0。
    current = [_finding("src/a.py"), _finding("src/b.py", severity="medium")]
    baseline = [_finding("src/a.py")]

    diff = build_complexity_diff_report(current, baseline, baseline_status="loaded")

    assert diff["ignored_count"] == 0
    assert diff["new_count"] == 1
    assert diff["unchanged_count"] == 1
    assert diff["resolved_count"] == 0

    unavailable = build_complexity_diff_report(current, [], baseline_status="missing")
    assert unavailable["status"] == "baseline_unavailable"
    assert unavailable["ignored_count"] == 0
    assert unavailable["unclassified_count"] == 2


def test_default_ignored_path_parts_cover_worktrees() -> None:
    assert ".claude/worktrees/" in DEFAULT_IGNORED_PATH_PARTS
    assert "node_modules/" in DEFAULT_IGNORED_PATH_PARTS


def test_command_for_target_replaces_profile_repo_root(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "src" / "hot.py"
    command = [sys.executable, "/tool/scanner.py", str(repo), "--format", "markdown"]

    rewritten = command_for_target(repo, command, target)

    assert str(target) in rewritten
    assert str(repo) not in rewritten
    assert rewritten[-1] == "json"


NESTED_LOOP_SOURCE = "for x in xs:\n    for y in ys:\n        total = x + y\n"


def _write_hot(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(NESTED_LOOP_SOURCE, encoding="utf-8")


def test_run_analysis_builtin_when_command_missing(tmp_path) -> None:
    # command 为 None/空 → 进程内 vendored 分析器, 不 subprocess。
    repo = tmp_path / "repo"
    _write_hot(repo / "src" / "stable.py")
    _write_hot(repo / "src" / "fresh.py")

    for command in (None, []):
        result = run_analysis(repo, command)
        assert result["verdict"] == "PASS"
        assert result["returncode"] == 0
        assert result["command"][0] == "<builtin:moth.analyzers.complexity>"
        assert {f["path"] for f in result["findings"]} == {"src/fresh.py", "src/stable.py"}
        assert result["summary"]["high_count"] == 2
        # stdout 与外部脚本 --format json 打印保持一致 (下游读 stdout 不受影响)。
        assert json.loads(result["stdout"]) == result["findings"]


def test_run_analysis_builtin_applies_excludes(tmp_path) -> None:
    repo = tmp_path / "repo"
    _write_hot(repo / "src" / "keep.py")
    _write_hot(repo / ".venv_scrape" / "skip.py")

    result = run_analysis(repo, None, excludes=[".venv_scrape"])

    assert result["verdict"] == "PASS"
    assert {f["path"] for f in result["findings"]} == {"src/keep.py"}
    assert "--exclude" in result["command"]
    assert ".venv_scrape" in result["command"]


def test_builtin_findings_are_baseline_diff_compatible(tmp_path) -> None:
    # 内建 findings 直接喂 baseline diff: new/resolved/unchanged 计算与外部路径一致。
    repo = tmp_path / "repo"
    _write_hot(repo / "src" / "stable.py")
    _write_hot(repo / "src" / "fresh.py")
    result = run_analysis(repo, None)
    stable = [f for f in result["findings"] if f["path"] == "src/stable.py"]
    assert len(stable) == 1

    from moth.adapters.complexity import load_complexity_baseline
    from pathlib import Path

    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps({"findings": stable + [_finding("src/gone.py", line=3)]}),
        encoding="utf-8",
    )
    baseline_findings, baseline_status = load_complexity_baseline(baseline_path)
    assert baseline_status == "loaded"

    diff = build_complexity_diff_report(
        result["findings"], baseline_findings, baseline_status=baseline_status, repo_root=repo
    )

    assert diff["status"] == "compared"
    assert diff["unchanged_count"] == 1
    assert diff["new_count"] == 1
    assert diff["new_high_count"] == 1
    assert diff["new_findings"][0]["path"] == "src/fresh.py"
    assert diff["resolved_count"] == 1
    assert diff["resolved_findings"][0]["path"] == "src/gone.py"


def test_run_analysis_for_paths_builtin_scans_directory_targets(tmp_path) -> None:
    repo = tmp_path / "repo"
    _write_hot(repo / "src" / "pkg" / "hot.py")
    _write_hot(repo / "src" / ".venv_scrape" / "skip.py")

    result = run_analysis_for_paths(repo, None, ["src"], excludes=[".venv_scrape"])

    assert result["verdict"] == "PASS"
    assert result["command_template"][0] == "<builtin:moth.analyzers.complexity>"
    assert result["files"][0]["path"] == "src"
    assert result["files"][0]["command"][0] == "<builtin:moth.analyzers.complexity>"
    # 与外部脚本被指到 target 的语义一致: 路径相对 target 根。
    assert {f["path"] for f in result["findings"]} == {"pkg/hot.py"}


def test_run_analysis_for_paths_builtin_missing_target_fails(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    result = run_analysis_for_paths(repo, None, ["nope"])

    assert result["verdict"] == "FAIL"
    assert any("complexity target missing" in issue for issue in result["issues"])


def test_run_analysis_explicit_command_still_uses_subprocess(tmp_path, monkeypatch) -> None:
    # 显式 command 仍走共享安全进程边界（不真跑外部程序）。

    calls = {}

    def fake_run(command, **kwargs):
        calls["command"] = command

        class Completed:
            returncode = 0
            stdout = "[]"
            stderr = ""

        return Completed()

    monkeypatch.setattr(complexity_adapter, "run_safe_process", fake_run)

    result = run_analysis(tmp_path, ["python", "/tool/scanner.py", str(tmp_path), "--format", "markdown"])

    assert result["verdict"] == "PASS"
    assert calls["command"][-1] == "json"
    assert result["command"][0] == "python"
