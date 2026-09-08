"""Import-cycle check — Tarjan SCC over the shared AST import graph (泛化自 lifehack
backend_import_cycle_audit 的机制, 不 import lifehack 代码).

Why: import 环运行时能跑 (Python 事后补 module), 但重构时脆、拖慢冷启动、
说明两模块过耦合。早抓比晚拆便宜。

用法 (profile YAML):

    import_cycles:
      scan_paths: [backend/services, backend/api]
      package_prefix: backend
      allowlist_path: config/architecture_known_cycles.json   # 可选

allowlist JSON 格式 (兼容 lifehack config/architecture_known_cycles.json):

    {"cycles": [{"name": "...", "members": ["backend.a", "backend.b"]}]}

判定: 检出环的 members 集合 ⊆ 某 allowlist 条目 members 集合 → known, 否则 new;
new_count > 0 → FAIL。scan_paths 为空/全部不存在 → PASS + note (可选功能, 未配置不惩罚)。
fail-closed: allowlist 配置了但缺失/坏 JSON → FAIL (配置错误不静默)。

Phase 2 重构 (2026-09-07): AST 解析/图构建不再自己走一遍, 改为消费
``moth.checks.import_graph.build_import_graph`` 产出的共享图 (单一计算点)。
本模块只负责: 把 (scan_paths, package_prefix) 机械换算成 import_graph 的
``roots``, 调共享图, 再按 scan_paths (来源) / package_prefix (去向) 过滤出
旧接口约定的 ``dict[module, set[module]]`` 形状喂给 Tarjan —— Tarjan 逻辑与
对外返回结构不变。这也带来一个精度修复: `from pkg import sub` 且 `pkg.sub`
真是一个已知模块时, 边指向 `pkg.sub` 而不再粗地并到 `pkg` (旧实现只看
`node.module` 字符串, 完全忽略被 import 的名字)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from moth.checks.import_graph import build_import_graph
from moth.checks.import_graph import resolve_root_and_prefix


def _matches_prefix(target: str, package_prefix: str) -> bool:
    return target == package_prefix or target.startswith(package_prefix + ".")


def _build_module_graph(
    base: Path, scan_paths: list[str], package_prefix: str
) -> tuple[dict[str, set[str]], list[str]]:
    """旧接口的适配层: 从共享 import_graph 里按 scan_paths/package_prefix 过滤出
    `dict[module, set[module]]`，保持这次重构前的对外形状 (module_count/edge_count
    的计算方式、cycle 检出逻辑都不变)。"""

    base = Path(base).resolve()
    existing = [entry for entry in scan_paths if (base / entry).is_dir()]
    missing = [entry for entry in scan_paths if not (base / entry).is_dir()]
    if not existing:
        return {}, missing

    root_prefix_pairs = [resolve_root_and_prefix(entry, package_prefix) for entry in existing]
    roots: list[str] = []
    for root, _prefix in root_prefix_pairs:
        if root not in roots:
            roots.append(root)
    scan_prefixes = [prefix for _root, prefix in root_prefix_pairs]

    full_graph = build_import_graph(base, roots=roots, excludes=[])

    edges_by_source: dict[str, set[str]] = {}
    for edge in full_graph["edges"]:
        edges_by_source.setdefault(edge["source"], set()).add(edge["target"])

    graph: dict[str, set[str]] = {}
    for module in full_graph["modules"]:
        if not any(_matches_prefix(module, prefix) for prefix in scan_prefixes):
            continue
        targets = {
            target
            for target in edges_by_source.get(module, set())
            if _matches_prefix(target, package_prefix)
        }
        graph[module] = targets
    return graph, missing


def _pop_scc_component(stack: list[str], on_stack: dict[str, bool], current: str) -> list[str]:
    component: list[str] = []
    while True:
        member = stack.pop()
        on_stack[member] = False
        component.append(member)
        if member == current:
            break
    return component


def _tarjan_scc(graph: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Tarjan to avoid recursion-limit on a deep graph."""
    index_counter = [0]
    stack: list[str] = []
    lowlink: dict[str, int] = {}
    index: dict[str, int] = {}
    on_stack: dict[str, bool] = {}
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        work_stack: list[tuple[str, int]] = [(node, 0)]
        call_stack: list[str] = [node]
        index[node] = index_counter[0]
        lowlink[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack[node] = True
        while work_stack:
            current, i = work_stack[-1]
            successors = sorted(graph.get(current, ()))
            if i < len(successors):
                work_stack[-1] = (current, i + 1)
                successor = successors[i]
                if successor not in index:
                    index[successor] = index_counter[0]
                    lowlink[successor] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(successor)
                    on_stack[successor] = True
                    work_stack.append((successor, 0))
                    call_stack.append(successor)
                elif on_stack.get(successor):
                    lowlink[current] = min(lowlink[current], index[successor])
            else:
                if lowlink[current] == index[current]:
                    sccs.append(_pop_scc_component(stack, on_stack, current))
                work_stack.pop()
                call_stack.pop()
                if call_stack:
                    parent = call_stack[-1]
                    lowlink[parent] = min(lowlink[parent], lowlink[current])

    for node in sorted(graph.keys()):
        if node not in index:
            strongconnect(node)
    return sccs


def _load_allowlist(path: Path) -> tuple[list[set[str]], str | None]:
    """返回 (allowlist member 集合列表, 错误描述|None)。fail-closed: 配置了就必须可读可解析。"""
    if not path.exists():
        return [], f"allowlist not found: {path}"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"allowlist unreadable/invalid JSON: {path} ({exc})"
    if not isinstance(data, dict) or not isinstance(data.get("cycles"), list):
        return [], f"allowlist must be a mapping with a 'cycles' list: {path}"
    return [set(entry.get("members") or []) for entry in data["cycles"] if isinstance(entry, dict)], None


def _classify_cycle(detected: set[str], allowlist: list[set[str]]) -> str:
    """环的 members ⊆ 某 allowlist 条目 members → known, 否则 new。"""
    for allowed in allowlist:
        if allowed and detected <= allowed:
            return "known"
    return "new"


def audit_import_cycles(
    repo_path: Path,
    scan_paths: list[str],
    package_prefix: str,
    allowlist_path: str | None = None,
) -> dict[str, Any]:
    base = Path(repo_path).resolve()
    result: dict[str, Any] = {
        "verdict": "PASS",
        "module_count": 0,
        "edge_count": 0,
        "cycles": [],
        "known_count": 0,
        "new_count": 0,
        "new_cycles": [],
        "issues": [],
        "note": None,
    }

    scan_paths = [str(entry) for entry in (scan_paths or [])]
    existing = [entry for entry in scan_paths if (base / entry).is_dir()]
    if not scan_paths or not existing:
        result["note"] = (
            "import_cycles not effective: no scan_paths configured"
            if not scan_paths
            else f"import_cycles not effective: scan_paths do not exist under {base}: {scan_paths}"
        )
        return result

    if not package_prefix:
        result["verdict"] = "FAIL"
        result["issues"].append("import_cycles.package_prefix is required when scan_paths are set")
        return result

    allowlist: list[set[str]] = []
    if allowlist_path:
        allow_file = Path(allowlist_path)
        if not allow_file.is_absolute():
            allow_file = base / allow_file
        allowlist, allow_error = _load_allowlist(allow_file)
        if allow_error:
            # fail-closed: allowlist 配置了但不可用 = 配置错误, 不静默当空。
            result["verdict"] = "FAIL"
            result["issues"].append(allow_error)
            return result

    graph, missing = _build_module_graph(base, scan_paths, package_prefix)
    if missing:
        result["note"] = f"scan_paths missing (skipped): {missing}"

    sccs = _tarjan_scc(graph)
    cycles = [sorted(component) for component in sccs if len(component) > 1]
    classified = [
        {"members": cycle, "status": _classify_cycle(set(cycle), allowlist)}
        for cycle in sorted(cycles)
    ]
    new_cycles = [{"members": item["members"]} for item in classified if item["status"] == "new"]
    known_count = sum(1 for item in classified if item["status"] == "known")

    result.update(
        {
            "module_count": len(graph),
            "edge_count": sum(len(deps) for deps in graph.values()),
            "cycles": classified,
            "known_count": known_count,
            "new_count": len(new_cycles),
            "new_cycles": new_cycles,
        }
    )
    if new_cycles:
        result["verdict"] = "FAIL"
        for cycle in new_cycles:
            members = cycle["members"]
            result["issues"].append("new import cycle: " + " -> ".join(members + [members[0]]))
    return result


def audit_import_cycles_for_profile(profile: Any) -> dict[str, Any]:
    """从 RepoProfile.import_cycles dict 取配置跑 audit (report.py / cli 共用)。"""
    config = profile.import_cycles or {}
    raw_scan_paths = config.get("scan_paths") or []
    allowlist_path = config.get("allowlist_path")
    return audit_import_cycles(
        profile.repo_path,
        [str(entry) for entry in raw_scan_paths],
        str(config.get("package_prefix") or ""),
        allowlist_path=str(allowlist_path) if allowlist_path else None,
    )


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Moth import cycles",
        "",
        f"- Verdict: `{result.get('verdict', 'UNKNOWN')}`",
        f"- Modules: `{result.get('module_count', 0)}`",
        f"- Edges: `{result.get('edge_count', 0)}`",
        f"- Cycles: `{len(result.get('cycles') or [])}`"
        f" (known {result.get('known_count', 0)} / new {result.get('new_count', 0)})",
    ]
    if result.get("note"):
        lines.append(f"- Note: {result['note']}")
    for issue in result.get("issues") or []:
        lines.append(f"- Issue: {issue}")
    for cycle in result.get("cycles") or []:
        members = cycle.get("members") or []
        lines.append(f"- [{cycle.get('status', '?').upper()}] " + " -> ".join(members + members[:1]))
    return "\n".join(lines) + "\n"
