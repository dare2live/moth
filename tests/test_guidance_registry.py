from pathlib import Path

from moth.guidance_registry import load_guidance_registry


def _source(source_id: str, *, kind: str, activation: str) -> dict:
    return {
        "id": source_id,
        "kind": kind,
        "provider": "codex_skill",
        "ref": f"skill:{source_id}",
        "activation": activation,
        "requirement": "required_when_active",
        "scope": "user",
        "owner": "user",
        "sensitivity": "personal" if source_id == "mio" else "internal",
        "egress_policy": "metadata_only",
    }


def test_user_registry_adds_mio_and_architect_to_project_guidance(tmp_path: Path) -> None:
    registry_dir = tmp_path / "moth"
    registry_dir.mkdir()
    (registry_dir / "guidance.yaml").write_text(
        """
kind: moth_guidance_registry
sources:
  - id: mio
    kind: collaboration_lens
    provider: codex_skill
    ref: skill:mio
    activation: substantive_judgment
    requirement: required_when_active
    scope: user
    owner: user
    sensitivity: personal
    egress_policy: metadata_only
  - id: architect-controller
    kind: controller_protocol
    provider: codex_skill
    ref: skill:architect-controller
    activation: architecture_orchestration
    requirement: required_when_active
    scope: user
    owner: user
    sensitivity: internal
    egress_policy: metadata_only
    load_after: [mio]
""".strip(),
        encoding="utf-8",
    )
    project_source = _source(
        "project-controller",
        kind="controller_protocol",
        activation="architecture_orchestration",
    )

    registry = load_guidance_registry(
        {"sources": [project_source]},
        codex_home=tmp_path,
    )

    assert registry["verdict"] == "PASS"
    assert [source["id"] for source in registry["sources"]] == [
        "mio",
        "architect-controller",
        "project-controller",
    ]
    assert registry["origins"] == {
        "mio": "user_registry",
        "architect-controller": "user_registry",
        "project-controller": "profile",
    }
    assert str(tmp_path) not in repr(registry)


def test_identical_profile_source_is_deduplicated_against_user_registry(tmp_path: Path) -> None:
    registry_dir = tmp_path / "moth"
    registry_dir.mkdir()
    source = _source("mio", kind="collaboration_lens", activation="substantive_judgment")
    (registry_dir / "guidance.yaml").write_text(
        "kind: moth_guidance_registry\n"
        "sources:\n"
        "  - id: mio\n"
        "    kind: collaboration_lens\n"
        "    provider: codex_skill\n"
        "    ref: skill:mio\n"
        "    activation: substantive_judgment\n"
        "    requirement: required_when_active\n"
        "    scope: user\n"
        "    owner: user\n"
        "    sensitivity: personal\n"
        "    egress_policy: metadata_only\n",
        encoding="utf-8",
    )

    registry = load_guidance_registry({"sources": [source]}, codex_home=tmp_path)

    assert registry["verdict"] == "PASS"
    assert registry["sources"] == [source]
    assert registry["origins"] == {"mio": "user_registry"}


def test_registry_rejects_non_list_or_non_mapping_sources(tmp_path: Path) -> None:
    malformed_profile = load_guidance_registry(
        {"sources": "mio"},
        codex_home=tmp_path,
    )
    assert malformed_profile["verdict"] == "FAIL"
    assert "profile guidance sources must be a list" in malformed_profile["issues"]

    registry_dir = tmp_path / "moth"
    registry_dir.mkdir()
    (registry_dir / "guidance.yaml").write_text(
        "kind: moth_guidance_registry\nsources:\n  - mio\n",
        encoding="utf-8",
    )
    malformed_registry = load_guidance_registry(
        {"sources": []},
        codex_home=tmp_path,
    )
    assert malformed_registry["verdict"] == "FAIL"
    assert (
        "user guidance registry sources must contain mappings"
        in malformed_registry["issues"]
    )
