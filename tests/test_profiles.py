import re
from pathlib import Path

import pytest

import moth.profiles.loader as profile_loader
from moth.profiles.loader import (
    build_default_profile,
    list_profiles,
    load_profile,
    match_profile,
)
from moth.profiles.loader import discover_profiles
from moth.profiles.scaffold import build_profile_scaffold
from moth.profiles.scaffold import default_profile_path
from moth.profiles.scaffold import write_profile_scaffold


def test_load_chunkymonkey_profile() -> None:
    profile = load_profile("chunkymonkey")
    assert profile.name == "chunkymonkey"
    assert profile.repo_path == Path("/Users/dp/Documents/M/stock/chunkymonkey")
    assert profile.evidence_paths["goal"].name == "goal.md"
    assert profile.codegraph_root == Path("/Users/dp/Documents/M/stock/chunkymonkey")
    assert profile.complexity_baseline_path == Path(
        "/Users/dp/Documents/M/stock/chunkymonkey/data/reports/tooling/complexity_baseline.json"
    )
    # complexity_command 已注释掉 → 内建分析器模式。
    assert profile.complexity_command == []
    assert profile.complexity_excludes == []


def test_load_profile_without_complexity_command_defaults_to_builtin(tmp_path) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "complexity_excludes:",
                "  - .venv_scrape",
                "  - fixtures",
            ]
        ),
        encoding="utf-8",
    )

    profile = load_profile(profile_path)

    assert profile.complexity_command == []
    assert profile.complexity_excludes == [".venv_scrape", "fixtures"]


def test_load_profile_preserves_instruction_sources(tmp_path) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "complexity_command: []",
                "instruction_sources:",
                "  active:",
                "    - AGENTS.md",
                "    - docs/",
                "  ignored_by_default:",
                "    - CLAUDE.md",
                "  legacy_exception: historical comparison only",
            ]
        ),
        encoding="utf-8",
    )

    profile = load_profile(profile_path)

    assert profile.instruction_sources["active"] == ["AGENTS.md", "docs/"]
    assert profile.instruction_sources["ignored_by_default"] == ["CLAUDE.md"]
    assert profile.instruction_sources["legacy_exception"] == "historical comparison only"


def test_non_bundled_profile_rejects_external_complexity_command(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "complexity_command:",
                "  - python",
                "  - $CODEX_HOME/skills/complexity-optimizer/scripts/analyze_complexity.py",
                "  - ~/repo",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="non-bundled profiles cannot select external complexity executables",
    ):
        load_profile(profile_path)


def test_load_profile_reads_complexity_ignored_path_parts(tmp_path) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    default_profile = tmp_path / "default.yaml"
    default_profile.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "complexity_command: []",
            ]
        ),
        encoding="utf-8",
    )
    override_profile = tmp_path / "override.yaml"
    override_profile.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: sample",
                f"repo_path: {repo}",
                "codegraph_root: .",
                "complexity_command: []",
                "complexity_ignored_path_parts:",
                "  - vendored/",
            ]
        ),
        encoding="utf-8",
    )

    # 未配置 = None (report 层落到 DEFAULT_IGNORED_PATH_PARTS); 配置 = 覆盖。
    assert load_profile(default_profile).complexity_ignored_path_parts is None
    assert load_profile(override_profile).complexity_ignored_path_parts == ["vendored/"]


def test_relative_profile_path_resolves_against_cwd(tmp_path, monkeypatch) -> None:
    # 回归 (lifehack 2026-06-14): `moth profile .moth/profile.yaml` 相对路径须相对 cwd 解析,
    # 不是 moth 仓 ROOT (否则在别项目下读成 moth 自己的文件; 之前要用绝对路径才正常)。
    repo = tmp_path / "other-project"
    (repo / ".moth").mkdir(parents=True)
    profile_path = default_profile_path(repo)
    payload = build_profile_scaffold(
        repo, name="other-project",
        evidence_paths={"goal": "goal.md"}, notes="local",
    )
    write_profile_scaffold(profile_path, payload, force=True)

    monkeypatch.chdir(repo)
    profile = load_profile(".moth/profile.yaml")  # 相对路径
    assert profile.name == "other-project"
    assert profile.repo_path == repo.resolve()


def test_profile_scaffold_declares_empty_typed_guidance_sources(tmp_path) -> None:
    payload = build_profile_scaffold(tmp_path / "sample-repo")

    assert payload["instruction_sources"] == {"sources": []}


def test_match_profile_by_repo_path(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profiles_dir = tmp_path / "moth-owned-profiles"
    profiles_dir.mkdir()
    (profiles_dir / "repo.yaml").write_text(
        "\n".join(
            [
                "kind: profile",
                "name: repo",
                f"repo_path: {repo}",
                "codegraph_root: .",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(profile_loader, "PROFILES_DIR", profiles_dir)

    profile = match_profile(repo)

    assert profile is not None
    assert profile.name == "repo"


def test_list_profiles_excludes_template() -> None:
    profiles = list_profiles()
    assert profiles
    assert all(profile.kind == "profile" for profile in profiles)
    assert {profile.name for profile in profiles} == {"chunkymonkey"}


def test_match_profile_prefers_repo_local_profile(tmp_path) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    profile_path = default_profile_path(repo)
    payload = build_profile_scaffold(
        repo,
        name="sample-repo",
        evidence_paths={"goal": "goal.md"},
        notes="local",
    )
    write_profile_scaffold(profile_path, payload, force=True)

    profile = match_profile(repo)
    assert profile is not None
    assert profile.name == "sample-repo"
    assert profile.repo_path == repo.resolve()
    assert profile.kind == "profile"
    assert profile.evidence_paths["goal"] == repo.resolve() / "goal.md"


def test_repo_local_profile_can_use_portable_relative_repo_path(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "portable-repo"
    profile_dir = repo / ".moth"
    profile_dir.mkdir(parents=True)
    (profile_dir / "profile.yaml").write_text(
        "\n".join(
            [
                "kind: profile",
                "name: portable-repo",
                "repo_path: ..",
                "codegraph_root: .",
                "evidence_paths:",
                "  plan: docs/plan.md",
            ]
        ),
        encoding="utf-8",
    )
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    profile = match_profile(repo)

    assert profile is not None
    assert profile.repo_path == repo.resolve()
    assert profile.codegraph_root == repo.resolve()
    assert profile.evidence_paths["plan"] == repo.resolve() / "docs" / "plan.md"


def test_discover_profiles_finds_repo_local_profiles(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    repo = workspace / "alpha"
    repo.mkdir(parents=True)
    profile_path = default_profile_path(repo)
    payload = build_profile_scaffold(
        repo,
        name="alpha",
        evidence_paths={"goal": "goal.md"},
        notes="local",
    )
    write_profile_scaffold(profile_path, payload, force=True)

    profiles = discover_profiles(workspace)
    assert len(profiles) == 1
    assert profiles[0].name == "alpha"
    assert profiles[0].repo_path == repo.resolve()


def test_default_profile_allows_read_only_inspection_without_scaffolding(
    tmp_path,
) -> None:
    repo = tmp_path / "unconfigured"
    repo.mkdir()

    profile = build_default_profile(repo)

    assert profile.kind == "ephemeral_profile"
    assert profile.name == "unconfigured"
    assert profile.repo_path == repo.resolve()
    assert profile.codegraph_root == repo.resolve()
    assert profile.instruction_sources == {"sources": []}
    assert not (repo / ".moth").exists()


def test_load_profile_resolves_bounded_omen_config(tmp_path) -> None:
    repo = tmp_path / "repo"
    profile_dir = repo / ".moth"
    profile_dir.mkdir(parents=True)
    (profile_dir / "omen.toml").write_text("", encoding="utf-8")
    profile_path = profile_dir / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: repo",
                "repo_path: ..",
                "codegraph_root: .",
                "tools:",
                "  omen:",
                "    enabled: true",
                "    required: false",
                "    config_path: .moth/omen.toml",
                "    top: 20",
                "    timeout_seconds: 30",
            ]
        ),
        encoding="utf-8",
    )

    profile = load_profile(profile_path)

    assert profile.tools == {
        "omen": {
            "enabled": True,
            "required": False,
            "config_path": repo / ".moth" / "omen.toml",
            "top": 20,
            "timeout_seconds": 30,
        }
    }


def test_repo_local_profile_cannot_redirect_repo_or_select_executable(tmp_path) -> None:
    repo = tmp_path / "repo"
    profile_dir = repo / ".moth"
    profile_dir.mkdir(parents=True)
    profile_path = profile_dir / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: escaped",
                "repo_path: ../..",
                "codegraph_root: .",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="owning repository"):
        load_profile(profile_path)

    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: executable",
                "repo_path: ..",
                "codegraph_root: .",
                "tools:",
                "  omen:",
                "    enabled: true",
                "    binary: /tmp/untrusted",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="trusted user installation registry"):
        load_profile(profile_path)


def _write_repo_local_profile_with_path(
    repo: Path,
    path_lines: list[str],
) -> Path:
    profile_dir = repo / ".moth"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profile_dir / "profile.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "kind: profile",
                "name: bounded",
                "repo_path: ..",
                "codegraph_root: .",
                *path_lines,
            ]
        ),
        encoding="utf-8",
    )
    return profile_path


@pytest.mark.parametrize(
    ("field_name", "path_lines"),
    [
        ("codegraph_root", ["codegraph_root: ../outside"]),
        (
            "complexity_baseline_path",
            ["complexity_baseline_path: ../outside/baseline.json"],
        ),
        ("evidence_paths.goal", ["evidence_paths:", "  goal: ../outside/goal.md"]),
        ("assertion_packs[0]", ["assertion_packs:", "  - ../outside/pack.yaml"]),
        (
            "tools.omen.config_path",
            ["tools:", "  omen:", "    config_path: ../outside/omen.toml"],
        ),
        (
            "import_cycles.scan_paths[0]",
            ["import_cycles:", "  scan_paths:", "    - ../outside"],
        ),
        (
            "import_cycles.allowlist_path",
            [
                "import_cycles:",
                "  scan_paths: [src]",
                "  allowlist_path: ../outside/allow.json",
            ],
        ),
    ],
)
def test_repo_local_profile_rejects_parent_path_escapes(
    tmp_path,
    field_name,
    path_lines,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    profile_path = _write_repo_local_profile_with_path(repo, path_lines)

    with pytest.raises(
        ValueError,
        match=rf"{re.escape(field_name)} escapes the profile repository",
    ):
        load_profile(profile_path)


def test_repo_local_profile_rejects_absolute_path_escape(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside" / "goal.md"
    profile_path = _write_repo_local_profile_with_path(
        repo,
        ["evidence_paths:", f"  goal: {outside}"],
    )

    with pytest.raises(
        ValueError,
        match=r"evidence_paths\.goal escapes the profile repository",
    ):
        load_profile(profile_path)


def test_repo_local_profile_rejects_symlink_path_escape(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "linked-outside").symlink_to(outside, target_is_directory=True)
    profile_path = _write_repo_local_profile_with_path(
        repo,
        [
            "tools:",
            "  omen:",
            "    config_path: linked-outside/omen.toml",
        ],
    )

    with pytest.raises(
        ValueError,
        match=r"tools\.omen\.config_path escapes the profile repository",
    ):
        load_profile(profile_path)


def test_repo_local_profile_rejects_import_cycle_symlink_escape(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "linked-outside").symlink_to(outside, target_is_directory=True)
    profile_path = _write_repo_local_profile_with_path(
        repo,
        [
            "import_cycles:",
            "  scan_paths:",
            "    - linked-outside",
        ],
    )

    with pytest.raises(
        ValueError,
        match=r"import_cycles\.scan_paths\[0\] escapes the profile repository",
    ):
        load_profile(profile_path)
