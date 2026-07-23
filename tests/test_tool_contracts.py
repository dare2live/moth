import pytest

from moth.tool_contracts import load_tool_contract


def test_omen_contract_externalizes_changeable_vocabulary_and_bounds() -> None:
    contract = load_tool_contract("omen")

    assert contract["kind"] == "moth_tool_contract"
    assert contract["id"] == "omen"
    assert contract["compatibility"]["strategy"] == "runtime_contract_probe"
    assert "moderate" in contract["vocabulary"]["hotspot_severities"]
    assert contract["bounds"] == {
        "max_findings": 100,
        "default_timeout_seconds": 60,
        "max_timeout_seconds": 300,
    }
    assert contract["process"]["environment_allowlist"] == [
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
    ]
    assert contract["process"]["shadow_config_paths"] == [
        "omen.toml",
        ".omen/omen.toml",
    ]


def test_unknown_or_invalid_tool_contract_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown tool contract"):
        load_tool_contract("not-registered")
