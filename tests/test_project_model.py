import json
import hashlib
from pathlib import Path

from jsonschema import Draft202012Validator

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
    # 这里此前断言 CONFORMANT, 而那个 CONFORMANT 是假的: drift 拿 desired 跟 current 比,
    # 而 current 里的关系正是同一份 .moth/architecture.yaml 合并进来的 —— 声明在跟自己比,
    # 结论恒为"一致"。接上 AST import 图之后, 经不起核对的声明被诚实地标了出来:
    #   relation:web-launcher-server —— 端点是 start.command(shell), import 图管不到
    # 所以整体从"一致"变成"无法证实"。这不是回归, 这正是被修掉的那个假象。
    #
    # 2026-09-08: .moth/architecture.yaml 曾还声明过 relation:inspection-guidance-
    # application (同样 UNVERIFIABLE, 因为真正的调用方是 decision_context.py 而非
    # inspection.py) —— 该关系随 guidance-application 证据层一起退役并从声明里删除,
    # 而不是被"修好", 详见 docs/migration-next.md。
    drift = model["architecture"]["drift"]
    assert drift["state"] == "UNVERIFIABLE"
    assert drift["unverifiable_ids"] == [
        "relation:relation:web-launcher-server",
    ]
    assert drift["violation_ids"] == []
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


def test_published_schemas_match_the_ones_the_code_validates_against() -> None:
    """仓根 schemas/ 与 src/moth/schemas/ 里的同名文件必须逐字相同。

    这两处是同一份契约的两个拷贝: 代码用 src/ 那份校验, 对外发布的是仓根那份。
    没有门的时候它们会悄悄漂 —— 2026-08-17 就漂过一次(给状态机加 name 时只改了 src/ 那份,
    仓根那份没跟上), 症状是只有一个碰巧引用了公开 schema 的测试报红, 别的全绿。

    只比对**两边都有**的文件: 仓根还发布了 snapshot / decision-context 等 src/ 不带的契约。
    """
    internal = REPO_ROOT / "src" / "moth" / "schemas"
    published = REPO_ROOT / "schemas"
    shared = sorted(
        p.name for p in published.glob("*.schema.json") if (internal / p.name).is_file()
    )
    assert shared, "两个目录没有任何同名 schema —— 这个用例就白跑了"

    drifted = [
        name
        for name in shared
        if (internal / name).read_bytes() != (published / name).read_bytes()
    ]
    assert drifted == [], (
        f"这些 schema 在 src/moth/schemas/ 与 schemas/ 之间漂了: {drifted}。"
        "改契约时两份都要改。"
    )


def test_build_project_model_carries_import_graph_when_supplied(tmp_path) -> None:
    """Phase 2 第二步: 图只是"挂"进模型, 原样传递, 不做提升/合并 (那是下一步)。"""

    import_graph = {
        "state": "OK",
        "roots": ["src"],
        "modules": ["acme.alpha", "acme.beta"],
        "edges": [
            {
                "source": "acme.alpha",
                "target": "acme.beta",
                "locations": [{"path": "src/acme/alpha.py", "line": 1}],
            }
        ],
        "omitted": {"files": 0, "edges": 0},
        "notes": [],
        "issues": [],
    }

    model = build_project_model(tmp_path, import_graph=import_graph)

    assert model["import_graph"] == import_graph


def test_build_project_model_import_graph_defaults_to_none(tmp_path) -> None:
    model = build_project_model(tmp_path)

    assert model["import_graph"] is None


def test_project_model_with_import_graph_remains_valid_against_public_schema(
    tmp_path,
) -> None:
    import_graph = {
        "state": "NOT_CONFIGURED",
        "roots": [],
        "modules": [],
        "edges": [],
        "omitted": {"files": 0, "edges": 0},
        "notes": ["import_graph not effective: no roots configured"],
        "issues": [],
    }

    model = build_project_model(tmp_path, import_graph=import_graph)
    schema = json.loads(
        (REPO_ROOT / "schemas" / "moth.project-model.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert list(Draft202012Validator(schema).iter_errors(model)) == []

    model_without_graph = build_project_model(tmp_path)
    assert list(Draft202012Validator(schema).iter_errors(model_without_graph)) == []
