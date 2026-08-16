import json
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

import moth.detectors.data_ai as data_ai_module
import moth.detectors.web as web_module
from moth.detectors.common import bounded_manifest_paths, load_platform_rules
from moth.detectors.python_project import detect_python_project
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


def test_python_api_and_static_frontend_are_detected_without_node_manifest(
    tmp_path,
) -> None:
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    backend.mkdir()
    frontend.mkdir()
    (backend / "requirements.txt").write_text(
        "fastapi==0.116.0\nuvicorn>=0.35\n",
        encoding="utf-8",
    )
    (backend / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (frontend / "index.html").write_text(
        "<!doctype html><title>Frontend</title>",
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {item["id"] for item in model["applications"]} == {
        "python-web:backend",
        "static-web:frontend",
    }
    assert {item["id"] for item in model["runtimes"]} == {"browser", "python"}
    assert {item["id"] for item in model["modules"]} >= {
        "framework:fastapi",
        "platform:api",
        "platform:web",
    }
    assert {item["id"] for item in model["relations"]} == {
        "uses-runtime:python-web:backend:python",
        "uses-runtime:static-web:frontend:browser",
    }


def test_desktop_static_frontend_is_detected(tmp_path) -> None:
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    (desktop / "index.html").write_text(
        "<!doctype html><title>Desktop</title>",
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert {
        "id": "static-web:desktop",
        "name": "desktop",
        "kind": "application",
        "subtype": "static_web_application",
        "entrypoint": "desktop/index.html",
        "runtime_id": "browser",
        "evidence_ids": ["manifest:desktop/index.html"],
    } in model["applications"]
    assert any(runtime["id"] == "browser" for runtime in model["runtimes"])


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


def test_unrelated_bulk_files_preserve_matches_but_report_partial_scan(
    monkeypatch,
    tmp_path,
) -> None:
    rules = deepcopy(load_platform_rules())
    rules["limits"]["max_entries"] = 8
    rules["web"]["package_globs"] = ["*/package.json"]
    monkeypatch.setattr(web_module, "load_platform_rules", lambda: rules)
    bulk = tmp_path / "a-bulk"
    app = tmp_path / "z-app"
    bulk.mkdir()
    app.mkdir()
    for index in range(50):
        (bulk / f"data-{index}.json").write_text("{}", encoding="utf-8")
    (app / "package.json").write_text(
        '{"name":"nested-ui","dependencies":{"react-dom":"^19"}}',
        encoding="utf-8",
    )

    model = build_project_model(tmp_path)

    assert any(item["id"] == "web:nested-ui" for item in model["applications"])
    assert any(
        "web project coverage partial" in warning
        for warning in model["coverage"]["warnings"]
    )


def test_recursive_manifest_scan_counts_every_enumerated_entry(tmp_path) -> None:
    for index in range(20):
        (tmp_path / f"data-{index}.json").write_text("{}", encoding="utf-8")

    paths, incomplete = bounded_manifest_paths(
        tmp_path,
        ["**/package.json"],
        limits={
            "max_depth": 4,
            "max_entries": 5,
            "excluded_directories": [],
        },
    )

    assert paths == []
    assert incomplete is True


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


def test_python_project_detected_from_requirements_without_pyproject(tmp_path) -> None:
    """次级清单足以证明"是 Python 项目", 但**不足以证明它叫什么**。

    2026-08-14 扩此路径的实测依据: 5 个注册项目里 4 个是实打实的 Python 代码库
    (lifehack 10808 / chunkymonkey 507 / gaozhong 325 / gaokao 87 个 .py), 却因为
    检测器只认 pyproject.toml 而全部 NOT_DETECTED —— 那不是证据不足, 是检测面没覆盖到。
    """
    (tmp_path / "requirements.txt").write_text(
        "# comment\n\nfastapi==0.116.0\n-r other.txt\n--index-url https://x\nuvicorn>=0.35\n-e .\n",
        encoding="utf-8",
    )
    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "DETECTED"
    # 注释 / 空行 / pip 选项 / 递归引用 / 可编辑安装全部剔除, 只留真依赖
    assert result["runtimes"][0]["dependencies"] == ["fastapi==0.116.0", "uvicorn>=0.35"]
    # **身份必须留空** —— 拿目录名冒充项目名就是发明证据, 违背 truth-source-first
    assert result["project"] is None
    assert any("project identity" in w for w in result["warnings"])
    assert any("requires-python" in w for w in result["warnings"])


def test_python_project_detected_from_suffixed_requirements_file(tmp_path) -> None:
    """`requirements-ci.txt` 这类带后缀的写法是本仓生态实际用法, 只认裸名会漏掉。

    (chunkymonkey 根目录就只有 requirements-ci.txt, 没有 requirements.txt。)
    """
    (tmp_path / "requirements-ci.txt").write_text("duckdb>=1.0\n", encoding="utf-8")
    result = detect_python_project(tmp_path)

    assert result["detector"]["state"] == "DETECTED"
    assert result["runtimes"][0]["dependencies"] == ["duckdb>=1.0"]


def test_python_project_without_any_manifest_stays_not_detected(tmp_path) -> None:
    """没有任何清单就必须 NOT_DETECTED —— 光有 .py 文件不构成清单证据。

    反向锁: 若哪天为了让验收矩阵好看而"看见 .py 就算数", 这条必红。
    (lifehack 有 10808 个 .py 且根目录无清单, 它的 NOT_DETECTED 是**正确**的。)
    """
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    assert detect_python_project(tmp_path)["detector"]["state"] == "NOT_DETECTED"


def test_pyproject_still_wins_over_fallback_manifests(tmp_path) -> None:
    """两级证据同时存在时, 完整清单优先 —— 身份必须来自 pyproject。"""
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "real-name"\nrequires-python = ">=3.11"\ndependencies = ["duckdb"]\n',
        encoding="utf-8",
    )
    result = detect_python_project(tmp_path)

    assert result["project"]["name"] == "real-name"
    assert result["runtimes"][0]["dependencies"] == ["duckdb"]
    assert result["warnings"] == []


def test_unparseable_discovered_notebook_is_coverage_warning_not_project_issue(
    tmp_path,
) -> None:
    """扫到的候选 notebook 解析不了 = 关于扫描的事实, 不是项目缺陷。

    2026-08-14 实测: gaokao 的 23 条 issue **全部**来自 data/external/ 下五个 vendored
    第三方数据集, 整个项目模型因此被别人的畸形 notebook 判成 verdict=FAIL。
    同一个 data_ai 检测器对 python manifest 走的是"信不过就跳过"(warning), 对 notebook
    却走 issue —— 同类事件两种严重级, 是不一致而非设计。
    「畸形 notebook 算不算项目缺陷」是目标仓的业务规则, 按 Moth AGENTS.md 第一条不属于 Moth。
    """
    vendored = tmp_path / "data" / "external" / "third-party"
    vendored.mkdir(parents=True)
    (vendored / "broken.ipynb").write_text("{not json at all", encoding="utf-8")
    (vendored / "no-structure.ipynb").write_text('{"foo": 1}', encoding="utf-8")

    model = build_project_model(tmp_path)
    coverage = model["coverage"]

    assert coverage["issues"] == [], "第三方畸形 notebook 不得把项目模型判红"
    assert model["verdict"] != "FAIL"
    assert any("notebook coverage partial" in w for w in coverage["warnings"]), (
        "降级不等于静默 —— 覆盖不全仍必须被看见"
    )


def test_repo_root_python_app_is_named_and_not_duplicated(tmp_path) -> None:
    """仓根与子目录扫到同一 entrypoint 时只产一个应用, 且不得叫 "."。

    2026-08-14 Web Console 实测发现: chunkymonkey 的「应用入口」里有两条都指向
    backend/main.py, 其中一条标题就是一个句点 —— 因为 `Path(".").as_posix()` 返回 "."
    而非空串, 是**真值**, 原来 `root.as_posix() or <repo dir name>` 的兜底永远不触发。
    """
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (tmp_path / "backend" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
    )

    apps = build_project_model(tmp_path)["applications"]
    entrypoints = [a.get("entrypoint") for a in apps]

    assert len(entrypoints) == len(set(entrypoints)), f"同一 entrypoint 不得产出多个应用: {entrypoints}"
    assert "." not in [a.get("name") for a in apps], "仓根应用必须有可读名字, 不能是一个句点"


def test_monorepo_services_survive_entrypoint_dedup(tmp_path) -> None:
    """去重不得吃掉真实子服务, 且丢弃必须发声。

    2026-08-15 独立审查实测复现: 仓根清单的 entrypoint 候选是全仓所有 main.py,
    min() 挑中 svc_a/main.py; 仓根先建应用后, svc_a 撞去重被静默丢掉 —— 清单里
    svc_a 消失, 换成一个以仓名命名、入口却指向 svc_a 的应用, 且零告警。
    """
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    for svc, dep in (("svc_a", "fastapi"), ("svc_b", "flask")):
        d = tmp_path / svc
        d.mkdir()
        (d / "requirements.txt").write_text(f"{dep}\n", encoding="utf-8")
        (d / "main.py").write_text("app = object()\n", encoding="utf-8")

    model = build_project_model(tmp_path)
    names = {a["name"] for a in model["applications"]}
    entries = [a.get("entrypoint") for a in model["applications"]]

    assert {"svc_a", "svc_b"} <= names, f"子服务不得被去重吃掉: {names}"
    assert len(entries) == len(set(entries)), "同一 entrypoint 仍不得出两个应用"
    assert any(
        "shares entrypoint" in w for w in (model["coverage"]["warnings"] or [])
    ), "丢弃祖先清单时必须发声, 不能静默"


def test_double_star_truncation_marks_scan_incomplete(tmp_path) -> None:
    """`**` 触顶必须置 incomplete —— 与字面目录分支同一处置。

    2026-08-16 实测(max_depth=3): `**/*.ipynb` 漏掉 a/b/c/d/deep.ipynb 却报
    incomplete=False, 而 `a/b/c/d/*.ipynb` 同样扫不到时报 True。同一函数对"扫不完"
    两种处置, 结果是少扫一半且**没有任何 coverage partial 警告**。
    生产 max_depth=6, 而 vendored 数据集正是深路径 —— 这道缺口专挑它们漏。
    """
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (tmp_path / "top.ipynb").write_text("{}", encoding="utf-8")
    (deep / "deep.ipynb").write_text("{}", encoding="utf-8")
    limits = {
        "max_depth": 3, "max_entries": 10000,
        "max_manifest_bytes": 1048576, "excluded_directories": [],
    }

    paths, incomplete = bounded_manifest_paths(tmp_path, ["**/*.ipynb"], limits=limits)

    assert incomplete is True, "扫不完必须说出来"
    assert len(paths) == 1, "前提: 深层文件确实没被扫到"

    # 反向一: 深度够用时不得误报 incomplete
    deep_limits = dict(limits, max_depth=9)
    paths2, incomplete2 = bounded_manifest_paths(tmp_path, ["**/*.ipynb"], limits=deep_limits)
    assert incomplete2 is False
    assert len(paths2) == 2


def test_double_star_at_depth_limit_with_nothing_below_is_not_incomplete(tmp_path) -> None:
    """触顶但**下面没有子目录** = 扫完了, 不得报 incomplete。

    第一版修复照抄了字面分支的无条件置位, 结果 moth 自己(仓里没有任何超 6 层目录)
    立刻从 PASS 变 WARN —— "到达深度上限"不等于"下面还有东西没扫", `**` 递归到上限
    是它正常穷举的终点。修过头就成了永远喊狼来了, 与静默漏报同样有害。
    """
    shallow = tmp_path / "a" / "b"
    shallow.mkdir(parents=True)
    (shallow / "x.ipynb").write_text("{}", encoding="utf-8")
    limits = {
        "max_depth": 2, "max_entries": 10000,
        "max_manifest_bytes": 1048576, "excluded_directories": [],
    }

    paths, incomplete = bounded_manifest_paths(tmp_path, ["**/*.ipynb"], limits=limits)

    assert incomplete is False, "触顶处下面没有子目录, 就是扫完了"
    assert [p.as_posix() for p in paths] == ["a/b/x.ipynb"]

