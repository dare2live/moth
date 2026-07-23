import pytest

from moth.tool_installations import load_tool_installations


def test_user_installation_registry_owns_executable_and_latest_update_strategy(
    tmp_path,
) -> None:
    registry = tmp_path / "tools.yaml"
    registry.write_text(
        "\n".join(
            [
                "kind: moth_tool_installations",
                "schema_version: 1",
                "tools:",
                "  omen:",
                "    executable: omen",
                "    update_strategy: latest_stable",
            ]
        ),
        encoding="utf-8",
    )

    assert load_tool_installations(registry) == {
        "omen": {
            "executable": "omen",
            "update_strategy": "latest_stable",
        }
    }


def test_relative_executable_path_and_version_pin_are_rejected(tmp_path) -> None:
    registry = tmp_path / "tools.yaml"
    registry.write_text(
        "\n".join(
            [
                "kind: moth_tool_installations",
                "schema_version: 1",
                "tools:",
                "  omen:",
                "    executable: ./untrusted",
                "    update_strategy: pinned_4_25",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_tool_installations(registry)
