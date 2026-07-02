from __future__ import annotations

import json
from pathlib import Path

from moth.checks.import_cycles import audit_import_cycles
from moth.checks.import_cycles import audit_import_cycles_for_profile
from moth.checks.import_cycles import render_markdown
from moth.cli import main
from moth.profiles.loader import load_profile


def _make_cycle_repo(tmp_path: Path) -> Path:
    """tmp 仓 fixture: pkg.services.a -> pkg.services.b -> pkg.services.a (环)
    + pkg.services.c -> pkg.services.a (非环, relative import)。"""
    repo = tmp_path / "repo"
    services = repo / "pkg" / "services"
    services.mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (services / "__init__.py").write_text("", encoding="utf-8")
    (services / "a.py").write_text("from pkg.services.b import helper\n", encoding="utf-8")
    (services / "b.py").write_text("import pkg.services.a\n", encoding="utf-8")
    (services / "c.py").write_text("from .a import helper\n", encoding="utf-8")
    return repo


def test_detects_new_cycle_and_fails(tmp_path: Path) -> None:
    repo = _make_cycle_repo(tmp_path)

    result = audit_import_cycles(repo, ["pkg/services"], "pkg")

    assert result["verdict"] == "FAIL"
    assert result["new_count"] == 1
    assert result["known_count"] == 0
    assert result["new_cycles"] == [{"members": ["pkg.services.a", "pkg.services.b"]}]
    assert any("pkg.services.a" in issue for issue in result["issues"])
    assert result["module_count"] >= 3
    assert result["edge_count"] >= 3
    rendered = render_markdown(result)
    assert "FAIL" in rendered and "pkg.services.a" in rendered


def test_allowlist_exempts_known_cycle(tmp_path: Path) -> None:
    repo = _make_cycle_repo(tmp_path)
    allowlist = repo / "known_cycles.json"
    allowlist.write_text(
        json.dumps({"cycles": [{"name": "legacy a<->b", "members": ["pkg.services.a", "pkg.services.b"]}]}),
        encoding="utf-8",
    )

    result = audit_import_cycles(repo, ["pkg/services"], "pkg", allowlist_path="known_cycles.json")

    assert result["verdict"] == "PASS"
    assert result["known_count"] == 1
    assert result["new_count"] == 0
    assert result["cycles"][0]["status"] == "known"


def test_allowlist_subset_semantics(tmp_path: Path) -> None:
    # 环 members ⊆ allowlist 条目 members → known (契约: 子集判定, 非严格相等)。
    repo = _make_cycle_repo(tmp_path)
    allowlist = repo / "known_cycles.json"
    allowlist.write_text(
        json.dumps({"cycles": [{"name": "superset", "members": ["pkg.services.a", "pkg.services.b", "pkg.services.z"]}]}),
        encoding="utf-8",
    )

    result = audit_import_cycles(repo, ["pkg/services"], "pkg", allowlist_path="known_cycles.json")

    assert result["verdict"] == "PASS"
    assert result["known_count"] == 1


def test_missing_or_invalid_allowlist_fails_closed(tmp_path: Path) -> None:
    repo = _make_cycle_repo(tmp_path)

    missing = audit_import_cycles(repo, ["pkg/services"], "pkg", allowlist_path="nope.json")
    assert missing["verdict"] == "FAIL"
    assert any("allowlist not found" in issue for issue in missing["issues"])

    bad = repo / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    invalid = audit_import_cycles(repo, ["pkg/services"], "pkg", allowlist_path="bad.json")
    assert invalid["verdict"] == "FAIL"
    assert any("invalid JSON" in issue for issue in invalid["issues"])


def test_unconfigured_or_missing_scan_paths_pass_with_note(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    empty = audit_import_cycles(repo, [], "pkg")
    assert empty["verdict"] == "PASS"
    assert "no scan_paths configured" in (empty["note"] or "")

    nonexistent = audit_import_cycles(repo, ["does/not/exist"], "pkg")
    assert nonexistent["verdict"] == "PASS"
    assert "do not exist" in (nonexistent["note"] or "")


def test_no_cycle_repo_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    services = repo / "pkg" / "services"
    services.mkdir(parents=True)
    (services / "a.py").write_text("import json\n", encoding="utf-8")
    (services / "b.py").write_text("from pkg.services import a\n", encoding="utf-8")

    result = audit_import_cycles(repo, ["pkg/services"], "pkg")

    assert result["verdict"] == "PASS"
    assert result["cycles"] == []
    assert result["new_count"] == 0


def _write_profile(tmp_path: Path, repo: Path, extra_lines: list[str]) -> Path:
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "complexity_command: []",
                *extra_lines,
            ]
        ),
        encoding="utf-8",
    )
    return profile_path


def test_profile_loads_import_cycles_config_and_runs(tmp_path: Path) -> None:
    repo = _make_cycle_repo(tmp_path)
    profile_path = _write_profile(
        tmp_path,
        repo,
        [
            "import_cycles:",
            "  scan_paths: [pkg/services]",
            "  package_prefix: pkg",
        ],
    )

    profile = load_profile(profile_path)
    assert profile.import_cycles == {"scan_paths": ["pkg/services"], "package_prefix": "pkg"}

    result = audit_import_cycles_for_profile(profile)
    assert result["verdict"] == "FAIL"
    assert result["new_count"] == 1


def test_profile_without_import_cycles_defaults_none(tmp_path: Path) -> None:
    repo = tmp_path / "plain-repo"
    repo.mkdir()
    profile = load_profile(_write_profile(tmp_path, repo, []))
    assert profile.import_cycles is None


def test_cli_cycles_reports_unconfigured_profile(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "plain-repo"
    repo.mkdir()
    profile_path = _write_profile(tmp_path, repo, [])

    rc = main(["cycles", "--repo", str(repo), "--profile", str(profile_path)])
    out = capsys.readouterr().out

    assert rc == 2
    assert "未配置 import_cycles" in out


def test_cli_cycles_runs_configured_profile(tmp_path: Path, capsys) -> None:
    repo = _make_cycle_repo(tmp_path)
    profile_path = _write_profile(
        tmp_path,
        repo,
        [
            "import_cycles:",
            "  scan_paths: [pkg/services]",
            "  package_prefix: pkg",
        ],
    )

    rc = main(["cycles", "--repo", str(repo), "--profile", str(profile_path), "--format", "json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert rc == 1
    assert payload["verdict"] == "FAIL"
    assert payload["new_cycles"] == [{"members": ["pkg.services.a", "pkg.services.b"]}]
