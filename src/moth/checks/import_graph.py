"""共享 AST import 图 —— Phase 2 第一步: 把 import_cycles.py 里已经存在但被
Tarjan 用完就扔的 module graph 提升为一等公民, 让后续步骤 (架构漂移/耦合分析等)
可以复用同一张图, 而不是各自重新走一遍 AST。

实测规模 (2026-09-07, 见 profiles/moth.yaml / chunkymonkey 实测):
  moth 自身 (roots=["src"]):            63 模块 / 94 条边
  chunkymonkey backend/ (roots=["backend"]): 374 模块 / 900+ 条边

用法::

    from moth.checks.import_graph import build_import_graph
    graph = build_import_graph(repo_path, roots=["src"], excludes=["tests"])
    graph["state"]   # "OK" / "NOT_CONFIGURED" / "INVALID"
    graph["modules"] # 排序后的模块名列表
    graph["edges"]   # [{"source":..., "target":..., "locations":[{"path":..., "line":...}]}]

**已实测的配置模型缺陷** (促成这次改动的直接原因): `import_cycles` 原本用
`scan_paths` + `package_prefix` 描述一个包, 无法表达"某个目录本身就是
sys.path 根、内部没有顶层 `__init__.py`"这种布局。chunkymonkey 的
`backend/main.py` 用 `sys.path.insert(0, backend目录)`, 源码里写
`from services.db import ...` 而不是 `backend.services.db`; 用
`package_prefix="backend"` 去扫会让整张图被前缀过滤成空。`roots` 直接对应
sys.path 条目, 不再需要包名前缀去猜。

**精度修复**: `from pkg import name` 时, 若 `pkg.name` 本身是一个已知模块
(即 `pkg/name.py` 真实存在), 边指向 `pkg.name` 而不是笼统的 `pkg`。判定用
"最长已知模块前缀"。旧的 import_cycles 实现只看 `node.module` 字符串, 完全
忽略被 import 的名字, 在 chunkymonkey 上实测有 80 处这种情况被错并到父包。
"""
from __future__ import annotations

import ast
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# K2: 预算/默认值策略 (import_graph_policy.yaml)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_import_graph_policy() -> dict[str, Any]:
    """带校验的 policy 加载, 风格仿 moth.visual_policy.load_visual_policy。"""

    resource = files("moth").joinpath("import_graph_policy.yaml")
    payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("kind") != "moth_import_graph_policy":
        raise ValueError("import graph policy must be a moth_import_graph_policy mapping")

    budget = payload.get("budget")
    if not isinstance(budget, dict):
        raise ValueError("import graph policy budget must be a mapping")
    for key in ("max_files", "max_edges"):
        value = budget.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"import graph policy budget.{key} must be a positive int")

    default_excludes = payload.get("default_excludes")
    if not isinstance(default_excludes, list) or not default_excludes or not all(
        isinstance(item, str) and item for item in default_excludes
    ):
        raise ValueError("import graph policy default_excludes must be a non-empty list of strings")

    dynamic_import_markers = payload.get("dynamic_import_markers")
    if not isinstance(dynamic_import_markers, list) or not dynamic_import_markers or not all(
        isinstance(item, str) and item for item in dynamic_import_markers
    ):
        raise ValueError(
            "import graph policy dynamic_import_markers must be a non-empty list of strings"
        )

    return payload


# ---------------------------------------------------------------------------
# 相对 import 解析 (从 import_cycles.py 迁移过来的唯一实现, 不重复维护两份)
# ---------------------------------------------------------------------------


def _resolve_relative(base_module: str, level: int, name: str | None) -> str | None:
    """把 `from .x import y` / `from ..pkg import y` 的 `.x`/`..pkg` 部分解析成
    绝对模块名。`name` 是 `from` 关键字后面那段 (即 ast.ImportFrom.module), 不是被
    import 的符号名。"""

    parts = base_module.split(".")
    if level > len(parts):
        return None
    base = parts[: len(parts) - level] if level else parts
    if name:
        base = base + name.split(".")
    return ".".join(base) if base else None


def _longest_known_prefix(dotted: str, known: set[str]) -> str | None:
    """"最长已知模块前缀"判定 —— 精度修复与常规解析共用同一条规则。"""

    if not dotted:
        return None
    parts = dotted.split(".")
    for end in range(len(parts), 0, -1):
        candidate = ".".join(parts[:end])
        if candidate in known:
            return candidate
    return None


def _targets_for_import(node: ast.Import, known: set[str]) -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    for alias in node.names:
        target = _longest_known_prefix(alias.name, known)
        if target:
            results.append((target, node.lineno))
    return results


def _targets_for_import_from(
    node: ast.ImportFrom, module_name: str, known: set[str]
) -> list[tuple[str, int]]:
    if node.level:
        base = _resolve_relative(module_name, node.level, node.module)
    else:
        base = node.module
    if not base:
        return []

    results: list[tuple[str, int]] = []
    for alias in node.names:
        name = alias.name
        if name == "*":
            target = _longest_known_prefix(base, known)
            if target:
                results.append((target, node.lineno))
            continue
        # 精度修复: `from pkg import name` 且 `pkg.name` 本身是已知模块时,
        # 边应指向 `pkg.name`, 而不是笼统的 `pkg`。
        candidate_full = f"{base}.{name}"
        if candidate_full in known:
            results.append((candidate_full, node.lineno))
            continue
        target = _longest_known_prefix(base, known)
        if target:
            results.append((target, node.lineno))
    return results


# ---------------------------------------------------------------------------
# 文件收集 / 模块命名 / exclude 匹配
# ---------------------------------------------------------------------------


def _is_excluded(rel_repo_posix: str, excludes: list[str]) -> bool:
    parts = rel_repo_posix.split("/")
    for token in excludes:
        if not token:
            continue
        if "/" in token:
            if token in rel_repo_posix:
                return True
        elif token in parts:
            return True
    return False


def _module_name_for_root(path: Path, root_dir: Path) -> str:
    rel = path.relative_to(root_dir).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _normalize_root(root: str) -> str:
    stripped = str(root).strip("/")
    return stripped or "."


@dataclass(slots=True)
class _ResolvedRoot:
    label: str
    dir_path: Path


def _resolve_roots(base: Path, roots: list[str]) -> tuple[list[_ResolvedRoot], list[str]]:
    """把请求的 roots 解析成真实存在、且被包含在 repo 内的目录。

    返回 (可用的 root, 不可用 root 的问题描述列表)。"""

    resolved: list[_ResolvedRoot] = []
    problems: list[str] = []
    seen_labels: set[str] = set()
    for raw in roots:
        label = _normalize_root(raw)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        candidate = base if label == "." else (base / label)
        try:
            real = candidate.resolve()
            real.relative_to(base)
        except ValueError:
            problems.append(f"root escapes repository: {raw}")
            continue
        if not real.is_dir():
            problems.append(f"root not found: {raw}")
            continue
        resolved.append(_ResolvedRoot(label=label, dir_path=real))
    return resolved, problems


def _collect_files(
    base: Path,
    resolved_roots: list[_ResolvedRoot],
    excludes: list[str],
) -> list[tuple[_ResolvedRoot, Path]]:
    seen_abs: set[Path] = set()
    collected: list[tuple[_ResolvedRoot, Path]] = []
    for root in resolved_roots:
        for path in sorted(root.dir_path.rglob("*.py")):
            if path in seen_abs:
                continue
            rel_repo = path.relative_to(base).as_posix()
            if _is_excluded(rel_repo, excludes):
                continue
            seen_abs.add(path)
            collected.append((root, path))
    return collected


# ---------------------------------------------------------------------------
# K1: build_import_graph
# ---------------------------------------------------------------------------


def build_import_graph(
    repo_path: str | Path,
    *,
    roots: list[str] | None,
    excludes: list[str] | None = None,
) -> dict[str, Any]:
    """在 `repo_path` 下, 沿着 `roots` (sys.path 意义上的 import 根) 扫描 *.py
    构建一张仓库内部的 AST import 图。

    返回 mapping:
      state    "OK" / "NOT_CONFIGURED" (未给 roots) / "INVALID" (给了 roots 但一个都不存在)
      roots    实际使用的 import 根 (相对仓库的 posix 路径, 排序)
      modules  模块名列表 (排序, 确定性)
      edges    [{"source", "target", "locations":[{"path","line"}, ...]}, ...] (排序, 确定性)
      omitted  {"files": int, "edges": int} —— 预算截断掉的数量, 不静默丢
      notes    说明性信息 (list[str])
      issues   问题信息, 如语法错误 / root 缺失 (list[str])
    """

    base = Path(repo_path).resolve()
    policy = load_import_graph_policy()
    max_files = int(policy["budget"]["max_files"])
    max_edges = int(policy["budget"]["max_edges"])
    default_excludes = list(policy["default_excludes"])

    result: dict[str, Any] = {
        "state": "NOT_CONFIGURED",
        "roots": [],
        "modules": [],
        "edges": [],
        "omitted": {"files": 0, "edges": 0},
        "notes": [],
        "issues": [],
    }

    requested = [str(r) for r in (roots or []) if str(r).strip()]
    if not requested:
        result["notes"].append("import_graph not effective: no roots configured")
        return result

    resolved_roots, root_problems = _resolve_roots(base, requested)
    result["issues"].extend(root_problems)
    if not resolved_roots:
        result["state"] = "INVALID"
        result["issues"].append(f"none of the configured roots exist under {base}: {requested}")
        return result

    excludes_all = default_excludes + [str(item) for item in (excludes or [])]

    all_files = _collect_files(base, resolved_roots, excludes_all)
    omitted_files = 0
    if len(all_files) > max_files:
        omitted_files = len(all_files) - max_files
        all_files = all_files[:max_files]
        result["notes"].append(
            f"import_graph truncated: {omitted_files} file(s) beyond max_files={max_files} omitted"
        )

    known: dict[str, Path] = {}
    issues: list[str] = []
    for root, path in all_files:
        module_name = _module_name_for_root(path, root.dir_path)
        if not module_name:
            continue
        if module_name in known and known[module_name] != path:
            issues.append(
                f"duplicate module name {module_name!r} from {path} and {known[module_name]} "
                "(kept the first one seen)"
            )
            continue
        known[module_name] = path

    known_set = set(known)
    edges_map: dict[tuple[str, str], list[dict[str, Any]]] = {}
    omitted_edges = 0

    for module_name, path in known.items():
        rel_repo = path.relative_to(base).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        except (SyntaxError, ValueError) as exc:
            issues.append(f"unparsable file skipped: {rel_repo} ({exc})")
            continue

        for node in ast.walk(tree):
            targets: list[tuple[str, int]] = []
            if isinstance(node, ast.Import):
                targets = _targets_for_import(node, known_set)
            elif isinstance(node, ast.ImportFrom):
                targets = _targets_for_import_from(node, module_name, known_set)
            else:
                continue
            for target, lineno in targets:
                if target == module_name:
                    continue
                key = (module_name, target)
                if key not in edges_map:
                    if len(edges_map) >= max_edges:
                        omitted_edges += 1
                        continue
                    edges_map[key] = []
                edges_map[key].append({"path": rel_repo, "line": lineno})

    if omitted_edges:
        result["notes"].append(
            f"import_graph truncated: {omitted_edges} edge(s) beyond max_edges={max_edges} omitted"
        )

    edges: list[dict[str, Any]] = []
    for (source, target), locations in edges_map.items():
        dedup_locations = sorted({(loc["path"], loc["line"]) for loc in locations})
        edges.append(
            {
                "source": source,
                "target": target,
                "locations": [{"path": p, "line": ln} for p, ln in dedup_locations],
            }
        )
    edges.sort(key=lambda item: (item["source"], item["target"]))

    result.update(
        {
            "state": "OK",
            "roots": sorted({root.label for root in resolved_roots}),
            "modules": sorted(known_set),
            "edges": edges,
            "omitted": {"files": omitted_files, "edges": omitted_edges},
            "issues": result["issues"] + issues,
        }
    )
    return result


# ---------------------------------------------------------------------------
# K3 支持: 从 import_cycles 配置 / pyproject.toml 推导 roots (供 profiles/loader.py 用)
# ---------------------------------------------------------------------------


def resolve_root_and_prefix(scan_path: str, package_prefix: str) -> tuple[str, str]:
    """给定单个 import_cycles.scan_path + package_prefix, 机械推导出:
      root   —— build_import_graph 意义上的 import 根 (sys.path 条目)
      prefix —— scan_path 下的模块名会以这个前缀开头

    规则: 在 scan_path 的路径分段里找 package_prefix (按 "." 拆出的分段序列)
    第一次作为连续子序列出现的位置, root = 该位置之前的部分, prefix = 该位置
    开始到 scan_path 结尾的部分 (点号拼接)。

    例: scan_path="src/moth", package_prefix="moth" -> root="src", prefix="moth"
        scan_path="pkg/services", package_prefix="pkg" -> root=".", prefix="pkg.services"

    找不到时退回旧 `_module_name_for` 的 flat 回退: root="."、prefix=scan_path 原样点号拼接。
    """

    parts = tuple(PurePosixPath(str(scan_path)).parts)
    prefix_parts = tuple(package_prefix.split(".")) if package_prefix else ()
    idx: int | None = None
    if prefix_parts:
        n = len(prefix_parts)
        for i in range(len(parts) - n + 1):
            if parts[i : i + n] == prefix_parts:
                idx = i
                break
    if idx is None:
        return ".", ".".join(parts)
    root_parts = parts[:idx]
    root = "/".join(root_parts) if root_parts else "."
    prefix = ".".join(parts[idx:])
    return root, prefix


def derive_roots_from_import_cycles(config: dict[str, Any] | None) -> list[str]:
    """K3 推导顺序第 2 步: `import_cycles.scan_paths` + `package_prefix` 机械推导
    `import_graph.roots`。推不出 (无 scan_paths / 无 package_prefix) 时返回 []。"""

    if not config:
        return []
    scan_paths = config.get("scan_paths") or []
    package_prefix = str(config.get("package_prefix") or "")
    if not scan_paths or not package_prefix:
        return []
    roots: list[str] = []
    for raw in scan_paths:
        root, _prefix = resolve_root_and_prefix(str(raw), package_prefix)
        if root not in roots:
            roots.append(root)
    return roots


def _derive_roots_from_pyproject(base: Path) -> list[str]:
    """K3 推导顺序第 3 步: `pyproject.toml` 的
    `tool.setuptools.package-dir` / `tool.setuptools.packages.find.where` /
    `tool.pytest.ini_options.pythonpath` 一手推导 (moth 自己的 pyproject 三处都指向 src)。"""

    pyproject_path = base / "pyproject.toml"
    if not pyproject_path.is_file():
        return []
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []

    tool = data.get("tool")
    if not isinstance(tool, dict):
        return []

    candidates: list[str] = []

    setuptools_cfg = tool.get("setuptools")
    if isinstance(setuptools_cfg, dict):
        package_dir = setuptools_cfg.get("package-dir")
        if isinstance(package_dir, dict):
            root_dir = package_dir.get("")
            if isinstance(root_dir, str) and root_dir:
                candidates.append(root_dir)
        packages = setuptools_cfg.get("packages")
        if isinstance(packages, dict):
            find_cfg = packages.get("find")
            if isinstance(find_cfg, dict):
                where = find_cfg.get("where")
                if isinstance(where, list):
                    candidates.extend(str(item) for item in where if isinstance(item, str) and item)

    pytest_cfg = tool.get("pytest")
    if isinstance(pytest_cfg, dict):
        ini_options = pytest_cfg.get("ini_options")
        if isinstance(ini_options, dict):
            pythonpath = ini_options.get("pythonpath")
            if isinstance(pythonpath, list):
                candidates.extend(str(item) for item in pythonpath if isinstance(item, str) and item)

    roots: list[str] = []
    for candidate in candidates:
        if candidate not in roots and (base / candidate).is_dir():
            roots.append(candidate)
    return roots


def infer_import_roots(
    repo_path: str | Path,
    *,
    import_cycles_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """K3 推导顺序第 2/3/4 步 (第 1 步"profile 显式写了 import_graph.roots"由调用方
    profiles/loader.py 先处理, 命中就不会调用这里)。

    返回 {"state": "OK"|"NOT_CONFIGURED", "roots": [...], "source": "import_cycles"|"pyproject"|None}
    都推不出时 state 为 NOT_CONFIGURED —— 不猜, 不默认成仓库根。"""

    base = Path(repo_path).resolve()

    roots = derive_roots_from_import_cycles(import_cycles_config)
    if roots:
        return {"state": "OK", "roots": roots, "source": "import_cycles"}

    roots = _derive_roots_from_pyproject(base)
    if roots:
        return {"state": "OK", "roots": roots, "source": "pyproject"}

    return {"state": "NOT_CONFIGURED", "roots": [], "source": None}
