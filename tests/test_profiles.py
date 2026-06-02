from pathlib import Path

from moth.profiles.loader import list_profiles, load_profile, match_profile
from moth.profiles.scaffold import build_profile_scaffold
from moth.profiles.scaffold import default_profile_path
from moth.profiles.scaffold import write_profile_scaffold


def test_load_chunkymonkey_profile() -> None:
    profile = load_profile("chunkymonkey")
    assert profile.name == "chunkymonkey"
    assert profile.repo_path == Path("/Users/dp/Documents/M/stock/chunkymonkey")
    assert profile.evidence_paths["goal"].name == "goal.md"
    assert profile.codegraph_root == Path("/Users/dp/Documents/M/stock/chunkymonkey")


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
