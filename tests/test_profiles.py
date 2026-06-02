from pathlib import Path

from moth.profiles.loader import load_profile, match_profile


def test_load_chunkymonkey_profile() -> None:
    profile = load_profile("chunkymonkey")
    assert profile.name == "chunkymonkey"
    assert profile.repo_path == Path("/Users/dp/Documents/M/stock/chunkymonkey")
    assert profile.goal_path.name == "goal.md"


def test_match_profile_by_repo_path() -> None:
    profile = match_profile("/Users/dp/Documents/M/stock/chunkymonkey")
    assert profile is not None
    assert profile.name == "chunkymonkey"
