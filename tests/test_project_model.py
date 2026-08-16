import json
import hashlib
from pathlib import Path

from moth.project_model import build_project_model


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_build_project_model_derives_moth_identity_and_python_runtime() -> None:
    model = build_project_model(REPO_ROOT)

    assert model["schema_version"] == "moth.project-model.v2"
    assert model["verdict"] == "PASS"
    assert model["project"] == {
        "id": "python:moth",
        "name": "moth",
        "version": "1.0.0",
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
    entity_ids = {item["id"] for item in model["entities"]}
    assert {
        "python",
        "python-console:moth",
        "python:moth",
        "service:inspection",
        "service:architecture-model",
        "service:change-safety",
    } <= entity_ids
    assert "uses-runtime:python-console:moth:python" in {
        item["id"] for item in model["relations"]
    }
    assert [item["id"] for item in model["flows"]] == [
        "flow:change-safety",
        "flow:inspect",
        "flow:web-console",
    ]
    assert [item["id"] for item in model["state_machines"]] == [
        "state-machine:inspection"
    ]
    assert model["architecture"]["declaration_state"] == "DECLARED"
    assert model["architecture"]["drift"]["state"] == "CONFORMANT"
    assert model["coverage"]["detectors"] == [
        {"id": "python-project", "state": "DETECTED"},
        {"id": "apple-project", "state": "NOT_DETECTED"},
        {"id": "web-project", "state": "NOT_DETECTED"},
        {"id": "mini-program-project", "state": "NOT_DETECTED"},
        {"id": "data-ai-project", "state": "NOT_DETECTED"},
        {"id": "multi-repository-project", "state": "NOT_DETECTED"},
    ]
    assert model["coverage"]["issues"] == []
    assert model["coverage"]["warnings"] == []

    evidence = model["evidence"]
    manifest = next(
        item for item in evidence if item["id"] == "manifest:pyproject.toml"
    )
    assert manifest["kind"] == "manifest"
    assert manifest["locator"] == "pyproject.toml"
    assert manifest["sha256"].startswith("sha256:")
    assert len(manifest["sha256"]) == len("sha256:") + 64
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


def test_repository_without_manifest_has_no_project_identity(tmp_path) -> None:
    """没有清单就**没有身份** —— 不许拿目录名兜底。

    2026-08-15 独立审查抓到: 原实现在这里用仓目录名填 project, 并为它伪造一条 evidence
    (sha256 算的是合成字符串 `repository-directory-name:<name>`, locator 却写 "."),
    与同一刀 commit message 声称的 "inventing identity would defeat the
    truth-source-first premise" 直接矛盾 —— detector 层守住了, model 层却做了。
    本例锁住模型层同样不发明身份; 目录名是文件系统的偶然, 不是项目对自己的声明。
    """
    model = build_project_model(tmp_path)

    assert model["verdict"] == "WARN"
    assert model["project"] is None
    assert model["applications"] == []
    assert model["runtimes"] == []
    # 伪证据必须一并消失: 不得有任何 evidence 的 sha256 是对合成字符串算的
    assert all(item.get("id") != "repository:root" for item in model["evidence"])

def test_project_model_includes_bounded_repo_local_profile_evidence(tmp_path) -> None:
    overview = tmp_path / "docs" / "overview.md"
    overview.parent.mkdir()
    overview.write_text("# Project overview\n", encoding="utf-8")

    model = build_project_model(
        tmp_path,
        evidence_paths={"project_overview": overview},
    )

    assert {
        "id": "profile:project_overview",
        "kind": "project_document",
        "locator": "docs/overview.md",
        "sha256": "sha256:" + hashlib.sha256(overview.read_bytes()).hexdigest(),
    } in model["evidence"]


def test_project_model_schema_declares_stage_one_contract() -> None:
    schema = json.loads(
        (REPO_ROOT / "schemas" / "moth.project-model.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert schema["properties"]["schema_version"]["const"] == "moth.project-model.v2"
    assert set(schema["required"]) == {
        "schema_version",
        "verdict",
        "project",
        "applications",
        "runtimes",
        "modules",
        "entities",
        "relations",
        "flows",
        "state_machines",
        "architecture",
        "evidence",
        "coverage",
    }
    assert schema["$defs"]["relativePath"]["pattern"] == (
        r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$)).+$"
    )
