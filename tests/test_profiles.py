from pathlib import Path

from moth.profiles.loader import list_profiles, load_profile, match_profile
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


def test_relative_profile_path_resolves_against_cwd(tmp_path, monkeypatch) -> None:
    # 回归 (lifehack 2026-06-14): `moth profile .moth/profile.yaml` 相对路径须相对 cwd 解析,
    # 不是 moth 仓 ROOT (否则在别项目下读成 moth 自己的文件; 之前要用绝对路径才正常)。
    repo = tmp_path / "other-project"
    (repo / ".moth").mkdir(parents=True)
    profile_path = default_profile_path(repo)
    payload = build_profile_scaffold(
        repo, name="other-project", complexity_command=["python", "-m", "moth"],
        evidence_paths={"goal": "goal.md"}, notes="local",
    )
    write_profile_scaffold(profile_path, payload, force=True)

    monkeypatch.chdir(repo)
    profile = load_profile(".moth/profile.yaml")  # 相对路径
    assert profile.name == "other-project"
    assert profile.repo_path == repo.resolve()


def test_match_profile_by_repo_path() -> None:
    profile = match_profile("/Users/dp/Documents/M/stock/chunkymonkey")
    assert profile is not None
    assert profile.name == "chunkymonkey"


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
        complexity_command=["python", "-m", "moth"],
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


def test_discover_profiles_finds_repo_local_profiles(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    repo = workspace / "alpha"
    repo.mkdir(parents=True)
    profile_path = default_profile_path(repo)
    payload = build_profile_scaffold(
        repo,
        name="alpha",
        complexity_command=["python", "-m", "moth"],
        evidence_paths={"goal": "goal.md"},
        notes="local",
    )
    write_profile_scaffold(profile_path, payload, force=True)

    profiles = discover_profiles(workspace)
    assert len(profiles) == 1
    assert profiles[0].name == "alpha"
    assert profiles[0].repo_path == repo.resolve()
