import json
from pathlib import Path

from moth.project_model import build_project_model


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_build_project_model_derives_moth_identity_and_python_runtime() -> None:
    model = build_project_model(REPO_ROOT)

    assert model["schema_version"] == "moth.project-model.v1"
    assert model["verdict"] == "PASS"
    assert model["project"] == {
        "id": "python:moth",
        "name": "moth",
        "version": "0.3.0",
        "description": "Cross-repo audit atlas for architecture, governance, and startup readiness",
        "evidence_ids": ["manifest:pyproject.toml"],
    }
    assert model["applications"] == [
        {
            "id": "python-console:moth",
            "name": "moth",
            "kind": "application",
            "subtype": "python_console_script",
            "entrypoint": "moth.cli:main",
            "runtime_id": "python",
            "evidence_ids": ["manifest:pyproject.toml"],
        }
    ]
    assert model["runtimes"] == [
        {
            "id": "python",
            "kind": "runtime",
            "constraint": ">=3.11",
            "dependencies": ["PyYAML>=6.0.1", "jsonschema>=4.20"],
            "evidence_ids": ["manifest:pyproject.toml"],
        }
    ]
    assert model["modules"] == []
    assert model["coverage"] == {
        "detectors": [{"id": "python-project", "state": "DETECTED"}],
        "issues": [],
        "warnings": [],
    }

    evidence = model["evidence"]
    assert len(evidence) == 1
    assert evidence[0]["id"] == "manifest:pyproject.toml"
    assert evidence[0]["kind"] == "manifest"
    assert evidence[0]["locator"] == "pyproject.toml"
    assert evidence[0]["sha256"].startswith("sha256:")
    assert len(evidence[0]["sha256"]) == len("sha256:") + 64
    assert str(REPO_ROOT) not in repr(model)


def test_project_model_is_canonical_across_repository_locations(tmp_path) -> None:
    manifest = (
        "[project]\n"
        "name = 'sample'\n"
        "version = '1.2.3'\n"
        "requires-python = '>=3.12'\n"
        "dependencies = ['zeta>=2', 'alpha>=1']\n"
        "[project.scripts]\n"
        "zeta = 'sample:zeta'\n"
        "alpha = 'sample:alpha'\n"
    )
    repos = [tmp_path / "first", tmp_path / "second"]
    for repo in repos:
        repo.mkdir()
        (repo / "pyproject.toml").write_text(manifest, encoding="utf-8")

    first = build_project_model(repos[0])
    second = build_project_model(repos[1])

    assert first == second
    assert [item["name"] for item in first["applications"]] == ["alpha", "zeta"]
    assert first["runtimes"][0]["dependencies"] == ["alpha>=1", "zeta>=2"]
    assert str(tmp_path) not in repr(first)


def test_unknown_repository_returns_warned_empty_model(tmp_path) -> None:
    model = build_project_model(tmp_path)

    assert model["verdict"] == "WARN"
    assert model["project"] is None
    assert model["applications"] == []
    assert model["runtimes"] == []
    assert model["modules"] == []
    assert model["evidence"] == []
    assert model["coverage"] == {
        "detectors": [{"id": "python-project", "state": "NOT_DETECTED"}],
        "issues": [],
        "warnings": ["python project coverage unavailable: pyproject.toml not found"],
    }


def test_project_model_schema_declares_stage_one_contract() -> None:
    schema = json.loads(
        (REPO_ROOT / "schemas" / "moth.project-model.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert schema["properties"]["schema_version"]["const"] == "moth.project-model.v1"
    assert set(schema["required"]) == {
        "schema_version",
        "verdict",
        "project",
        "applications",
        "runtimes",
        "modules",
        "evidence",
        "coverage",
    }
    assert schema["properties"]["evidence"]["items"]["properties"]["locator"][
        "pattern"
    ] == r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$)).+$"
