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
