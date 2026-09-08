from __future__ import annotations

from pathlib import Path

from moth.checks.import_graph import build_import_graph
from moth.checks.import_graph import derive_roots_from_import_cycles
from moth.checks.import_graph import infer_import_roots
from moth.checks.import_graph import load_import_graph_policy
from moth.checks.import_graph import resolve_root_and_prefix


def _edge(graph: dict, source: str, target: str) -> dict | None:
    for edge in graph["edges"]:
        if edge["source"] == source and edge["target"] == target:
            return edge
    return None


def test_load_import_graph_policy_shape() -> None:
    policy = load_import_graph_policy()
    assert policy["kind"] == "moth_import_graph_policy"
    assert policy["budget"]["max_files"] > 0
    assert policy["budget"]["max_edges"] > 0
    assert ".venv" in policy["default_excludes"]
    assert "importlib" in policy["dynamic_import_markers"]


def test_src_layout_produces_edges(tmp_path: Path) -> None:
    """src-layout (roots=["src"], 模块名带包前缀) -> 边数 > 0。"""
    pkg = tmp_path / "src" / "acme"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "alpha.py").write_text("from acme.beta import helper\n", encoding="utf-8")
    (pkg / "beta.py").write_text("def helper() -> None:\n    return None\n", encoding="utf-8")

    graph = build_import_graph(tmp_path, roots=["src"], excludes=[])

    assert graph["state"] == "OK"
    assert graph["roots"] == ["src"]
    assert "acme.alpha" in graph["modules"]
    assert "src.acme.alpha" not in graph["modules"]
    assert len(graph["edges"]) > 0
    edge = _edge(graph, "acme.alpha", "acme.beta")
    assert edge is not None
    assert edge["locations"] == [{"path": "src/acme/alpha.py", "line": 1}]


def test_directory_as_sys_path_root_without_init_produces_edges(tmp_path: Path) -> None:
    """模拟 chunkymonkey 的布局: `backend/` 本身就是 sys.path 根, 没有
    `backend/__init__.py`, 源码里写的是 `from services.x import y` 而不是
    `backend.services.x`。这个场景在旧的 package_prefix 模型下会得到空图
    (整个前缀过滤把图清空) —— 是这次配置模型从 scan_paths+package_prefix
    换成 roots 的核心理由。"""
    backend = tmp_path / "backend"
    services = backend / "services"
    services.mkdir(parents=True)
    # 刻意不写 backend/__init__.py —— backend 不是一个 package, 只是 sys.path 根。
    (services / "__init__.py").write_text("", encoding="utf-8")
    (services / "db.py").write_text("def connect() -> None:\n    return None\n", encoding="utf-8")
    (backend / "main.py").write_text("from services.db import connect\n", encoding="utf-8")

    graph = build_import_graph(tmp_path, roots=["backend"], excludes=[])

    assert graph["state"] == "OK"
    assert "services.db" in graph["modules"]
    assert "main" in graph["modules"]
    assert len(graph["edges"]) > 0
    edge = _edge(graph, "main", "services.db")
    assert edge is not None


def test_from_pkg_import_submodule_precision(tmp_path: Path) -> None:
    """`from pkg import sub` 且 `pkg/sub.py` 真的存在时, 边必须指向 `pkg.sub`,
    不能被粗地并到 `pkg`。"""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub.py").write_text("VALUE = 1\n", encoding="utf-8")
    caller = tmp_path / "caller.py"
    caller.write_text("from pkg import sub\n", encoding="utf-8")

    graph = build_import_graph(tmp_path, roots=["."], excludes=[])

    assert graph["state"] == "OK"
    edge = _edge(graph, "caller", "pkg.sub")
    assert edge is not None, graph["edges"]
    assert _edge(graph, "caller", "pkg") is None


def test_unconfigured_repo_state(tmp_path: Path) -> None:
    """无 .moth/、无 pyproject 的临时仓 -> state == NOT_CONFIGURED, 不抛异常。"""
    repo = tmp_path / "bare-repo"
    repo.mkdir()
    (repo / "loose.py").write_text("import os\n", encoding="utf-8")

    inferred = infer_import_roots(repo, import_cycles_config=None)
    assert inferred["state"] == "NOT_CONFIGURED"
    assert inferred["roots"] == []

    # build_import_graph 本身在没被给 roots 时同样是 NOT_CONFIGURED, 不抛异常。
    graph = build_import_graph(repo, roots=[], excludes=[])
    assert graph["state"] == "NOT_CONFIGURED"
    assert graph["modules"] == []
    assert graph["edges"] == []


def test_build_import_graph_is_deterministic(tmp_path: Path) -> None:
    """同一仓库跑两次, modules 与 edges 完全相等。"""
    pkg = tmp_path / "src" / "acme"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "alpha.py").write_text("from acme.beta import helper\nimport acme.gamma\n", encoding="utf-8")
    (pkg / "beta.py").write_text("from . import gamma\n", encoding="utf-8")
    (pkg / "gamma.py").write_text("def helper() -> None:\n    return None\n", encoding="utf-8")

    first = build_import_graph(tmp_path, roots=["src"], excludes=[])
    second = build_import_graph(tmp_path, roots=["src"], excludes=[])

    assert first["modules"] == second["modules"]
    assert first["edges"] == second["edges"]


def test_invalid_roots_state(tmp_path: Path) -> None:
    """给了 roots 但一个都不存在 -> INVALID (区分于压根没给 roots 的 NOT_CONFIGURED)。"""
    repo = tmp_path / "repo"
    repo.mkdir()

    graph = build_import_graph(repo, roots=["does/not/exist"], excludes=[])

    assert graph["state"] == "INVALID"
    assert any("not found" in issue for issue in graph["issues"])


def test_omitted_budget_is_reported_not_silently_dropped(tmp_path: Path, monkeypatch) -> None:
    """预算截断必须写进 omitted, 不能静默丢。"""
    import moth.checks.import_graph as import_graph_module

    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for i in range(5):
        (pkg / f"m{i}.py").write_text("x = 1\n", encoding="utf-8")

    tight_policy = {
        "kind": "moth_import_graph_policy",
        "schema_version": 1,
        "budget": {"max_files": 3, "max_edges": 20000},
        "default_excludes": [".venv"],
        "dynamic_import_markers": ["importlib"],
    }
    monkeypatch.setattr(import_graph_module, "load_import_graph_policy", lambda: tight_policy)

    graph = build_import_graph(tmp_path, roots=["pkg"], excludes=[])
    assert graph["omitted"]["files"] == 3  # 6 files (incl. __init__.py) - budget 3
    assert any("max_files" in note for note in graph["notes"])


def test_syntax_error_file_reported_in_issues_not_fatal(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (pkg / "ok.py").write_text("import json\n", encoding="utf-8")

    graph = build_import_graph(tmp_path, roots=["pkg"], excludes=[])

    # roots=["pkg"] 意味着 pkg/ 目录本身就是 sys.path 根 (同 chunkymonkey 的 backend/
    # 场景), 所以模块名不带 "pkg." 前缀 —— 这正是这次配置模型要表达的东西。
    assert graph["state"] == "OK"
    assert "broken" in graph["modules"]
    assert "ok" in graph["modules"]
    assert any("broken.py" in issue for issue in graph["issues"])


def test_excludes_drop_matching_paths(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    (pkg / "tests").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "tests" / "test_thing.py").write_text("import json\n", encoding="utf-8")

    graph = build_import_graph(tmp_path, roots=["pkg"], excludes=["tests"])

    assert all("tests" not in m.split(".") for m in graph["modules"])


def test_resolve_root_and_prefix_matches_moth_self_profile() -> None:
    # moth 自己的 .moth/profile.yaml: scan_paths: [src/moth], package_prefix: moth
    assert resolve_root_and_prefix("src/moth", "moth") == ("src", "moth")


def test_resolve_root_and_prefix_when_scan_path_is_subpackage() -> None:
    assert resolve_root_and_prefix("pkg/services", "pkg") == (".", "pkg.services")


def test_derive_roots_from_import_cycles_moth_example() -> None:
    config = {"scan_paths": ["src/moth"], "package_prefix": "moth"}
    assert derive_roots_from_import_cycles(config) == ["src"]


def test_derive_roots_from_import_cycles_empty_when_unconfigured() -> None:
    assert derive_roots_from_import_cycles(None) == []
    assert derive_roots_from_import_cycles({}) == []


def test_infer_import_roots_from_pyproject(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "pyproject.toml").write_text(
        "\n".join(
            [
                "[tool.setuptools]",
                'package-dir = {"" = "src"}',
                "",
                "[tool.pytest.ini_options]",
                'pythonpath = ["src"]',
            ]
        ),
        encoding="utf-8",
    )

    inferred = infer_import_roots(tmp_path, import_cycles_config=None)
    assert inferred["state"] == "OK"
    assert inferred["roots"] == ["src"]
    assert inferred["source"] == "pyproject"


def test_infer_import_roots_prefers_import_cycles_over_pyproject(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "nested" / "other").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\npythonpath = [\"src\"]\n", encoding="utf-8"
    )

    inferred = infer_import_roots(
        tmp_path,
        import_cycles_config={"scan_paths": ["nested/other"], "package_prefix": "other"},
    )
    assert inferred["state"] == "OK"
    assert inferred["roots"] == ["nested"]
    assert inferred["source"] == "import_cycles"
