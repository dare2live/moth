from moth.profiles.loader import RepoProfile
from moth.checks.startup import check_profile


def test_profile_checks_find_missing_placeholder_only_when_expected(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    baseline = repo / "complexity_baseline.json"
    baseline.write_text("[]", encoding="utf-8")
    agents = repo / "AGENTS.md"
    agents.write_text("# rules\n", encoding="utf-8")
    profile = RepoProfile(
        kind="profile",
        name="sample",
        repo_path=repo,
        codegraph_root=repo,
        complexity_command=["python", "scanner.py"],
        complexity_baseline_path=baseline,
        evidence_paths={"agents": agents},
        notes="test",
    )
    issues = check_profile(profile)
    assert issues == []


def test_profile_without_complexity_command_is_not_an_issue(tmp_path) -> None:
    # 缺省 = moth 内建分析器, 不再报 "missing complexity command"。
    repo = tmp_path / "repo"
    repo.mkdir()
    profile = RepoProfile(
        kind="profile",
        name="builtin-sample",
        repo_path=repo,
        codegraph_root=repo,
    )
    assert check_profile(profile) == []


def test_profile_checks_required_omen_config_exists(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    missing_config = repo / ".moth" / "omen.toml"
    profile = RepoProfile(
        kind="profile",
        name="omen-sample",
        repo_path=repo,
        codegraph_root=repo,
        tools={
            "omen": {
                "enabled": True,
                "required": True,
                "config_path": missing_config,
            }
        },
    )

    assert check_profile(profile) == [
        f"missing omen config: {missing_config}"
    ]
