"""moth gates — 实验 go/no-go 跑批器 (并入自 sherpa, 2026-07-02).

gate 包 = moth assertion_pack 同 schema 的 YAML (直接用内部断言引擎, 不重复造判定原语):
<repo>/.sherpa/gates/<experiment>.yaml (兼容旧 sherpa 约定, 优先) 或
<repo>/.moth/gates/<experiment>.yaml, kind: assertion_pack。
跑前一条命令出 PASS/FAIL 表; 任一 fail/error = NO-GO (exit 1)。

设计动机: 预注册纪律 "gate 用实测不引用文档" + 防 "门柱挪动/带病开跑" —
gate 写成断言后, 改门柱 = 改 YAML = git diff 可见, 模型口头放宽无效。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moth.checks.assertions import load_pack, run_pack

# 兼容顺序: .sherpa/gates (旧 sherpa 仓约定) → .moth/gates。
GATES_DIRS = (".sherpa/gates", ".moth/gates")


def list_gates(repo: str | Path) -> list[str]:
    repo_path = Path(repo)
    names: set[str] = set()
    for rel in GATES_DIRS:
        gate_dir = repo_path / rel
        if gate_dir.exists():
            names.update(p.stem for p in gate_dir.glob("*.yaml"))
    return sorted(names)


def find_gate(repo: str | Path, experiment: str) -> Path | None:
    """按兼容顺序找 gate 包; 都没有返回 None。"""
    repo_path = Path(repo)
    for rel in GATES_DIRS:
        candidate = repo_path / rel / f"{experiment}.yaml"
        if candidate.exists():
            return candidate
    return None


def run_gate(repo: str | Path, experiment: str) -> dict[str, Any]:
    repo_path = Path(repo)
    pack_path = find_gate(repo_path, experiment)
    if pack_path is None:
        searched = ", ".join(str(repo_path / rel / f"{experiment}.yaml") for rel in GATES_DIRS)
        raise FileNotFoundError(
            f"gate 包不存在: {searched} (可用: {list_gates(repo_path) or '无'})"
        )
    pack = load_pack(pack_path)
    result = run_pack(pack, repo_path)
    result["go"] = result["fail"] == 0 and result["error"] == 0
    return result


def render_markdown(result: dict[str, Any]) -> str:
    verdict = "GO" if result["go"] else "NO-GO"
    lines = [
        f"# moth gate — {result['name']}",
        "",
        f"- Verdict: `{verdict}`"
        f" (pass {result['pass']} / fail {result['fail']} / error {result['error']})",
        "",
    ]
    for r in result["results"]:
        mark = "PASS" if r["status"] == "pass" else r["status"].upper()
        lines.append(f"- [{mark}] `{r['id']}`: {r['claim']}")
        if r["status"] != "pass":
            lines.append(f"  - observed={r['observed']!r} expected={r['expected']}")
            if r["detail"]:
                lines.append(f"  - {r['detail']}")
    return "\n".join(lines) + "\n"
