import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

import moth.detectors.data_ai as data_ai_module
import moth.detectors.web as web_module
from moth.detectors.common import load_platform_rules
from moth.project_model import build_project_model


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_xcode_sdk_setting_detects_ios_without_exposing_repository_path(tmp_path) -> None:
    project = tmp_path / "Sample.xcodeproj"
    project.mkdir()
    (project / "project.pbxproj").write_text(
        "SDKROOT = iphoneos;\nSWIFT_VERSION = 6.0;\n",
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert model["verdict"] == "PASS"
    assert model["coverage"]["warnings"] == []
    assert {
        "id": "platform:ios",
        "kind": "platform",
        "name": "iOS",
        "subtype": "apple",
        "evidence_ids": ["manifest:Sample.xcodeproj/project.pbxproj"],
    } in model["modules"]
    assert {
        "id": "apple-xcode:Sample",
        "name": "Sample",
        "kind": "application",
        "subtype": "apple_xcode_project",
        "entrypoint": "Sample.xcodeproj",
        "runtime_id": "xcode",
        "evidence_ids": ["manifest:Sample.xcodeproj/project.pbxproj"],
    } in model["applications"]
    assert str(tmp_path) not in repr(model)


def test_package_manifest_dependency_detects_web_framework_from_source_evidence(
    tmp_path,
) -> None:
    (tmp_path / "package.json").write_text(
        """
        {
          "name": "console",
          "engines": {"node": ">=22"},
          "dependencies": {"next": "^15.0.0", "react": "^19.0.0"}
        }
        """,
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {
        "id": "platform:web",
        "kind": "platform",
        "name": "Web",
        "subtype": "web",
        "evidence_ids": ["manifest:package.json"],
    } in model["modules"]
    assert {
        "id": "framework:nextjs",
        "kind": "framework",
        "name": "Next.js",
        "subtype": "web",
        "evidence_ids": ["manifest:package.json"],
    } in model["modules"]
    assert model["applications"] == [
        {
            "id": "web:console",
            "name": "console",
            "kind": "application",
            "subtype": "web_application",
            "entrypoint": "package.json",
            "runtime_id": "nodejs",
            "evidence_ids": ["manifest:package.json"],
        }
    ]


def test_declared_python_dependencies_detect_data_and_ai_capabilities(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "pipeline"
        requires-python = ">=3.12"
        dependencies = ["duckdb>=1.2", "openai>=2"]
        """,
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {
        module["id"] for module in model["modules"] if module["kind"] == "platform"
    } == {"platform:ai", "platform:data"}
    assert {
        (module["id"], module["name"])
        for module in model["modules"]
        if module["kind"] == "technology"
    } == {("technology:duckdb", "DuckDB"), ("technology:openai", "OpenAI")}
    assert str(tmp_path) not in repr(model)


def test_paired_wechat_manifests_detect_miniprogram_and_declared_pages(tmp_path) -> None:
    (tmp_path / "project.config.json").write_text(
        '{"projectname": "shop-client", "compileType": "miniprogram"}',
        encoding="utf-8",
    )
    (tmp_path / "app.json").write_text(
        '{"pages": ["pages/index/index", "pages/cart/cart"]}',
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {
        "id": "platform:wechat-miniprogram",
        "kind": "platform",
        "name": "WeChat Mini Program",
        "subtype": "mini_program",
        "evidence_ids": [
            "manifest:app.json",
            "manifest:project.config.json",
        ],
    } in model["modules"]
    pages = [module for module in model["modules"] if module["kind"] == "page"]
    assert [page["name"] for page in pages] == [
        "pages/cart/cart",
        "pages/index/index",
    ]
    assert model["applications"] == [
        {
            "id": "mini-program:wechat:shop-client",
            "name": "shop-client",
            "kind": "application",
            "subtype": "mini_program_application",
            "entrypoint": "app.json",
            "runtime_id": "wechat-miniprogram",
            "evidence_ids": [
                "manifest:app.json",
                "manifest:project.config.json",
            ],
        }
    ]


def test_mixed_project_merges_detectors_and_deduplicates_shared_evidence(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "service"
        requires-python = ">=3.12"
        dependencies = ["duckdb>=1.2"]
        """,
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"name": "admin", "dependencies": {"next": "^15"}}',
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert model["verdict"] == "PASS"
    assert {
        module["id"] for module in model["modules"] if module["kind"] == "platform"
    } == {"platform:data", "platform:web"}
    assert {
        "id": "composition:mixed",
        "kind": "composition",
        "name": "Mixed project",
        "subtype": "multi_platform",
        "evidence_ids": ["manifest:package.json", "manifest:pyproject.toml"],
    } in model["modules"]
    evidence_ids = [item["id"] for item in model["evidence"]]
    assert len(evidence_ids) == len(set(evidence_ids))


def test_data_and_ai_capabilities_do_not_alone_claim_multi_platform(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "modeling"
        requires-python = ">=3.12"
        dependencies = ["duckdb>=1.2", "torch>=2"]
        """,
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {
        module["id"] for module in model["modules"] if module["kind"] == "platform"
    } == {"platform:data", "platform:ai"}
    assert not any(
        module["id"] == "composition:mixed" for module in model["modules"]
    )


def test_gitmodules_detects_multi_repository_composition_without_exposing_urls(
    tmp_path,
) -> None:
    private_url = "git@example.invalid:private/service.git"
    (tmp_path / ".gitmodules").write_text(
        f"""
        [submodule "backend"]
          path = services/backend
          url = {private_url}
        [submodule "client"]
          path = clients/mobile
          url = ../mobile.git
        """,
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {
        "id": "composition:multi-repo",
        "kind": "composition",
        "name": "Multi-repository project",
        "subtype": "git_submodules",
        "evidence_ids": ["manifest:.gitmodules"],
    } in model["modules"]
    repositories = [
        module for module in model["modules"] if module["kind"] == "repository"
    ]
    assert [(item["name"], item["locator"]) for item in repositories] == [
        ("backend", "services/backend"),
        ("client", "clients/mobile"),
    ]
    assert private_url not in repr(model)
    assert str(tmp_path) not in repr(model)


def test_valid_notebook_is_data_evidence_without_dependency_guessing(tmp_path) -> None:
    notebook = tmp_path / "analysis" / "quality.ipynb"
    notebook.parent.mkdir()
    notebook.write_text(
        '{"nbformat": 4, "nbformat_minor": 5, "cells": [], "metadata": {}}',
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {
        "id": "platform:data",
        "kind": "platform",
        "name": "Data",
        "subtype": "data_ai",
        "evidence_ids": ["manifest:analysis/quality.ipynb"],
    } in model["modules"]
    assert {
        "id": "artifact:notebook:analysis/quality.ipynb",
        "kind": "artifact",
        "name": "quality.ipynb",
        "subtype": "notebook",
        "locator": "analysis/quality.ipynb",
        "evidence_ids": ["manifest:analysis/quality.ipynb"],
    } in model["modules"]


def test_swift_package_platform_declaration_is_apple_source_evidence(tmp_path) -> None:
    (tmp_path / "Package.swift").write_text(
        """
        // swift-tools-version: 6.0
        import PackageDescription
        let package = Package(
          name: "SharedKit",
          platforms: [.macOS(.v15)]
        )
        """,
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {
        "id": "platform:macos",
        "kind": "platform",
        "name": "macOS",
        "subtype": "apple",
        "evidence_ids": ["manifest:Package.swift"],
    } in model["modules"]
    assert {
        "id": "apple-swift-package:SharedKit",
        "name": "SharedKit",
        "kind": "application",
        "subtype": "apple_swift_package",
        "entrypoint": "Package.swift",
        "runtime_id": "swift",
        "evidence_ids": ["manifest:Package.swift"],
    } in model["applications"]


def test_platform_model_remains_valid_against_public_schema(tmp_path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
        [project]
        name = "pipeline"
        requires-python = ">=3.12"
        dependencies = ["openai>=2"]
        """,
        encoding="utf-8",
    )
    model = build_project_model(tmp_path)
    schema = json.loads(
        (REPO_ROOT / "schemas" / "moth.project-model.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert list(Draft202012Validator(schema).iter_errors(model)) == []


def test_package_name_and_react_alone_do_not_guess_a_web_platform(tmp_path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name": "native-client", "dependencies": {"react": "^19"}}',
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert not any(
        module["id"] == "platform:web" for module in model["modules"]
    )
    assert model["applications"] == []
    assert model["runtimes"][0]["id"] == "nodejs"


def test_incompatible_duplicate_application_identity_fails_closed(tmp_path) -> None:
    for directory in ("first", "second"):
        package_dir = tmp_path / directory
        package_dir.mkdir()
        (package_dir / "package.json").write_text(
            '{"name": "console", "dependencies": {"next": "^15"}}',
            encoding="utf-8",
        )

    model = build_project_model(tmp_path)

    assert model["verdict"] == "FAIL"
    assert model["coverage"]["issues"] == [
        "project model conflict: application id has incompatible facts"
    ]


def test_other_miniprogram_manifest_pair_uses_configured_platform_adapter(
    tmp_path,
) -> None:
    (tmp_path / "mini.project.json").write_text(
        '{"miniprogramRoot": "./"}',
        encoding="utf-8",
    )
    (tmp_path / "app.json").write_text(
        '{"pages": []}',
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert any(
        module["id"] == "platform:alipay-miniprogram"
        and module["name"] == "Alipay Mini Program"
        for module in model["modules"]
    )
    assert any(runtime["id"] == "alipay-miniprogram" for runtime in model["runtimes"])


def test_web_capability_identity_is_fully_configured(monkeypatch, tmp_path) -> None:
    rules = deepcopy(load_platform_rules())
    rules["web"]["capabilities"]["edge"] = {
        "name": "Edge Runtime",
        "subtype": "edge_runtime",
    }
    rules["web"]["framework_dependencies"]["edge-kit"] = {
        "id": "edge-kit",
        "name": "Edge Kit",
        "capability": "edge",
    }
    monkeypatch.setattr(web_module, "load_platform_rules", lambda: rules)
    (tmp_path / "package.json").write_text(
        '{"name":"edge-app","dependencies":{"edge-kit":"^1"}}',
        encoding="utf-8",
    )

    result = web_module.detect_web_project(tmp_path)

    assert any(
        module["id"] == "platform:edge"
        and module["name"] == "Edge Runtime"
        and module["subtype"] == "edge_runtime"
        for module in result["modules"]
    )


def test_data_capability_identity_is_fully_configured(monkeypatch, tmp_path) -> None:
    rules = deepcopy(load_platform_rules())
    rules["data_ai"]["capabilities"]["vector"] = {
        "name": "Vector Search",
        "subtype": "retrieval",
    }
    rules["data_ai"]["dependency_capabilities"]["vector-db"] = {
        "name": "Vector DB",
        "capability": "vector",
    }
    monkeypatch.setattr(data_ai_module, "load_platform_rules", lambda: rules)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="search"\ndependencies=["vector-db>=1"]\n',
        encoding="utf-8",
    )

    result = data_ai_module.detect_data_ai_project(tmp_path)

    assert any(
        module["id"] == "platform:vector"
        and module["name"] == "Vector Search"
        and module["subtype"] == "retrieval"
        for module in result["modules"]
    )
