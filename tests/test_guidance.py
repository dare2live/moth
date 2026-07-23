import os
from pathlib import Path

import pytest

from moth.guidance import resolve_guidance_sources, sanitize_instruction_sources


def _mio_source() -> dict[str, str]:
    return {
        "id": "mio",
        "kind": "collaboration_lens",
        "provider": "codex_skill",
        "ref": "skill:mio",
        "activation": "substantive_judgment",
        "requirement": "required_when_active",
        "scope": "user",
        "owner": "user",
        "sensitivity": "personal",
        "egress_policy": "metadata_only",
    }


def _write_skill(codex_home: Path, *, name: str = "mio", body: str = "# Mio\n") -> Path:
    skill_dir = codex_home / "skills" / "mio"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        f"---\nname: {name}\ndescription: Personal collaboration lens.\n---\n{body}",
        encoding="utf-8",
    )
    return skill_path


def test_resolve_guidance_sources_discovers_skill_without_exporting_private_content(
    tmp_path: Path,
) -> None:
    codex_home = tmp_path / "codex-home"
    skill_dir = codex_home / "skills" / "mio"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: mio\n"
        "description: Personal collaboration lens.\n"
        "---\n"
        "# Private Mio body\n",
        encoding="utf-8",
    )

    report = resolve_guidance_sources(
        {
            "sources": [
                {
                    "id": "mio",
                    "kind": "collaboration_lens",
                    "provider": "codex_skill",
                    "ref": "skill:mio",
                    "activation": "substantive_judgment",
                    "requirement": "required_when_active",
                    "scope": "user",
                    "owner": "user",
                    "sensitivity": "personal",
                    "egress_policy": "metadata_only",
                }
            ]
        },
        codex_home=codex_home,
    )

    assert report["verdict"] == "PASS"
    assert report["issues"] == []
    assert report["warnings"] == []
    assert report["sources"] == [
        {
            "id": "mio",
            "kind": "collaboration_lens",
            "provider": "codex_skill",
            "ref": "skill:mio",
            "activation": "substantive_judgment",
            "requirement": "required_when_active",
            "scope": "user",
            "owner": "user",
            "sensitivity": "personal",
            "egress_policy": "metadata_only",
            "state": "DISCOVERED",
            "source_digest": report["sources"][0]["source_digest"],
            "source_mtime": report["sources"][0]["source_mtime"],
            "body_exported": False,
            "issues": [],
        }
    ]
    assert report["sources"][0]["source_digest"].startswith("sha256:")
    serialized = repr(report)
    assert str(tmp_path) not in serialized
    assert "Private Mio body" not in serialized


def test_resolve_guidance_sources_rejects_incomplete_typed_source(tmp_path: Path) -> None:
    report = resolve_guidance_sources(
        {
            "sources": [
                {
                    "id": "mio",
                    "provider": "codex_skill",
                    "ref": "skill:mio",
                }
            ]
        },
        codex_home=tmp_path,
    )

    assert report["verdict"] == "FAIL"
    assert report["sources"][0]["state"] == "INVALID"
    assert "missing required fields" in report["issues"][0]


def test_resolve_guidance_sources_rejects_unknown_activation(tmp_path: Path) -> None:
    report = resolve_guidance_sources(
        {
            "sources": [
                {
                    "id": "mio",
                    "kind": "collaboration_lens",
                    "provider": "codex_skill",
                    "ref": "skill:mio",
                    "activation": "whenever_the_model_feels_like_it",
                    "requirement": "required_when_active",
                    "scope": "user",
                    "owner": "user",
                    "sensitivity": "personal",
                    "egress_policy": "metadata_only",
                }
            ]
        },
        codex_home=tmp_path,
    )

    assert report["verdict"] == "FAIL"
    assert report["sources"][0]["state"] == "INVALID"
    assert "invalid activation" in report["issues"][0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "personality_engine"),
        ("requirement", "silently_optional"),
        ("scope", "everyone_on_the_internet"),
        ("sensitivity", "publish_everything"),
        ("egress_policy", "send_body_by_default"),
    ],
)
def test_resolve_guidance_sources_rejects_unknown_typed_values(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    source = {
        "id": "mio",
        "kind": "collaboration_lens",
        "provider": "codex_skill",
        "ref": "skill:mio",
        "activation": "substantive_judgment",
        "requirement": "required_when_active",
        "scope": "user",
        "owner": "user",
        "sensitivity": "personal",
        "egress_policy": "metadata_only",
    }
    source[field] = value

    report = resolve_guidance_sources({"sources": [source]}, codex_home=tmp_path)

    assert report["verdict"] == "FAIL"
    assert report["sources"][0]["state"] == "INVALID"
    assert f"invalid {field}" in report["issues"][0]


def test_resolve_guidance_sources_rejects_duplicate_ids(tmp_path: Path) -> None:
    source = _mio_source()

    report = resolve_guidance_sources(
        {"sources": [source, dict(source)]},
        codex_home=tmp_path,
    )

    assert report["verdict"] == "FAIL"
    assert "duplicate guidance source id: mio" in report["issues"]


def test_resolve_guidance_sources_rejects_frontmatter_identity_mismatch(tmp_path: Path) -> None:
    _write_skill(tmp_path, name="not-mio")

    report = resolve_guidance_sources({"sources": [_mio_source()]}, codex_home=tmp_path)

    assert report["verdict"] == "FAIL"
    assert report["sources"][0]["state"] == "INVALID"
    assert "frontmatter name does not match" in report["issues"][0]


def test_source_digest_tracks_content_not_mtime(tmp_path: Path) -> None:
    skill_path = _write_skill(tmp_path, body="# Version one\n")
    initial = resolve_guidance_sources({"sources": [_mio_source()]}, codex_home=tmp_path)
    initial_digest = initial["sources"][0]["source_digest"]
    original_times = (skill_path.stat().st_atime, skill_path.stat().st_mtime)

    os.utime(skill_path, (original_times[0] + 10, original_times[1] + 10))
    touched = resolve_guidance_sources({"sources": [_mio_source()]}, codex_home=tmp_path)
    assert touched["sources"][0]["source_digest"] == initial_digest

    skill_path.write_text(
        "---\nname: mio\ndescription: Personal collaboration lens.\n---\n# Version two\n",
        encoding="utf-8",
    )
    os.utime(skill_path, original_times)
    changed = resolve_guidance_sources({"sources": [_mio_source()]}, codex_home=tmp_path)
    assert changed["sources"][0]["source_digest"] != initial_digest


def test_resolver_uses_codex_home_without_exporting_relocated_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_home = tmp_path / "first-home"
    second_home = tmp_path / "second-home"
    first_path = _write_skill(first_home)
    second_path = _write_skill(second_home)
    second_path.write_bytes(first_path.read_bytes())

    monkeypatch.setenv("CODEX_HOME", str(first_home))
    first = resolve_guidance_sources({"sources": [_mio_source()]})
    monkeypatch.setenv("CODEX_HOME", str(second_home))
    second = resolve_guidance_sources({"sources": [_mio_source()]})

    assert first["sources"][0]["source_digest"] == second["sources"][0]["source_digest"]
    assert str(first_home) not in repr(first)
    assert str(second_home) not in repr(second)


def test_sanitizer_preserves_known_legacy_contract_but_drops_private_extensions() -> None:
    public = sanitize_instruction_sources(
        {
            "active": ["AGENTS.md"],
            "ignored_by_default": ["CLAUDE.md"],
            "legacy_exception": "historical comparison only",
            "body": "private Mio body",
            "resolved_path_local_only": "/Users/private/.codex/skills/mio/SKILL.md",
            "sources": [{**_mio_source(), "state": "APPLIED_WITH_EVIDENCE", "receipt": {"fake": True}}],
        }
    )

    assert public == {
        "active": ["AGENTS.md"],
        "ignored_by_default": ["CLAUDE.md"],
        "legacy_exception": "historical comparison only",
        "sources": [_mio_source()],
    }


def test_invalid_logical_metadata_is_redacted_from_public_outputs(tmp_path: Path) -> None:
    private_value = "/Users/private/amend-trail"
    source = {
        **_mio_source(),
        "id": private_value,
        "kind": private_value,
        "provider": private_value,
        "ref": private_value,
        "activation": private_value,
        "owner": private_value,
    }
    source.pop("egress_policy")

    report = resolve_guidance_sources({"sources": [source]}, codex_home=tmp_path)
    public = sanitize_instruction_sources({"sources": [source]})

    assert report["verdict"] == "FAIL"
    assert private_value not in repr(report)
    assert private_value not in repr(public)
    assert report["sources"][0]["id"] == "<invalid>"
    assert public["sources"][0]["owner"] == "<invalid>"


def test_skill_read_failure_does_not_export_private_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_home = tmp_path / "private-codex-home"
    _write_skill(private_home)

    def deny_open(path: Path, *_args, **_kwargs):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(Path, "open", deny_open)
    report = resolve_guidance_sources({"sources": [_mio_source()]}, codex_home=private_home)

    assert report["verdict"] == "FAIL"
    assert report["sources"][0]["state"] == "INVALID"
    assert "skill read failed" in report["issues"][0]
    assert str(private_home) not in repr(report)
