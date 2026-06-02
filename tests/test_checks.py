from moth.profiles.loader import load_profile
from moth.checks.startup import check_profile


def test_profile_checks_find_missing_placeholder_only_when_expected() -> None:
    profile = load_profile("chunkymonkey")
    issues = check_profile(profile)
    assert issues == []
