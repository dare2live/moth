"""moth takeover — 接手对账器: 新 session 第一条命令 (并入自 sherpa, 2026-07-02).

把"接手一个项目要查什么"从模型记忆外置成 repo-owned YAML 清单:
每个 section = 一条只读命令 + 可选判定规则, 输出单页 markdown verdict。
设计对象 = 降级期模型 (Opus): 它不需要记得查什么, 只需要跑 `moth takeover` 并读 FAIL。

清单位置: <repo>/.sherpa/takeover.yaml (兼容旧 sherpa 约定, 优先) 或 <repo>/.moth/takeover.yaml。

清单 schema:

    kind: takeover_checklist
    name: my-repo
    sections:
      - id: alert-flags
        title: "定时任务告警 flag"
        command: ["bash", "-c", "ls /tmp/myproj_ALERT_*.flag 2>/dev/null || true"]
        timeout_s: 30          # 可选, 默认 60
        # 判定 (全部可选, 不写 = 仅信息展示, 永远 OK):
        fail_regex: "ALERT"     # 输出匹配 → FAIL
        warn_regex: "WARN"      # 输出匹配 → WARN (fail 优先)
        ok_requires_regex: "OK" # 输出必须匹配, 否则 FAIL (探活型: 沉默不是成功)
        max_lines: 20           # 报告里保留的输出行数 (默认 15)

fail-closed: 命令非零退出/超时 = 该 section FAIL, 不许静默跳过。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TIMEOUT_S = 60
DEFAULT_MAX_LINES = 15

# 兼容顺序: .sherpa/ (旧 sherpa 仓约定, 已存在的 repo 不用迁移) → .moth/。
CHECKLIST_LOCATIONS = (".sherpa/takeover.yaml", ".moth/takeover.yaml")


def find_checklist(repo: str | Path) -> Path | None:
    """按兼容顺序找 takeover 清单; 都没有返回 None。"""
    repo_path = Path(repo)
    for rel in CHECKLIST_LOCATIONS:
        candidate = repo_path / rel
        if candidate.exists():
            return candidate
    return None


def load_checklist(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or raw.get("kind") != "takeover_checklist":
        raise ValueError(f"{p}: not a takeover_checklist")
    sections = raw.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError(f"{p}: sections must be a non-empty list")
    for idx, sec in enumerate(sections):
        if not isinstance(sec, dict) or "id" not in sec or "command" not in sec:
            raise ValueError(f"{p}: section #{idx} missing id/command")
        if not isinstance(sec["command"], list) or not sec["command"]:
            raise ValueError(f"{p}: section '{sec.get('id')}' command must be argv list")
    return {"name": str(raw.get("name", p.stem)), "path": str(p), "sections": sections}


def _run_section(section: dict[str, Any], repo: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(section["id"]),
        "title": str(section.get("title", section["id"])),
        "status": "FAIL",
        "lines": [],
        "detail": "",
    }
    timeout = int(section.get("timeout_s", DEFAULT_TIMEOUT_S))
    try:
        result = subprocess.run(
            [str(part) for part in section["command"]],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        out["detail"] = f"timeout after {timeout}s"
        return out
    text = (result.stdout or "") + (("\n" + result.stderr) if result.stderr.strip() else "")
    text = text.strip()
    max_lines = int(section.get("max_lines", DEFAULT_MAX_LINES))
    out["lines"] = text.splitlines()[-max_lines:] if text else []
    if result.returncode != 0:
        out["detail"] = f"exit {result.returncode}"
        return out

    status = "OK"
    if section.get("ok_requires_regex") and not re.search(str(section["ok_requires_regex"]), text):
        status, out["detail"] = "FAIL", f"missing required pattern: {section['ok_requires_regex']}"
    if section.get("warn_regex") and re.search(str(section["warn_regex"]), text) and status == "OK":
        status = "WARN"
    if section.get("fail_regex") and re.search(str(section["fail_regex"]), text):
        status, out["detail"] = "FAIL", f"matched fail pattern: {section['fail_regex']}"
    out["status"] = status
    return out


def run_takeover(checklist: dict[str, Any], repo: str | Path) -> dict[str, Any]:
    repo_path = Path(repo)
    sections = [_run_section(sec, repo_path) for sec in checklist["sections"]]
    counts = {s: sum(1 for x in sections if x["status"] == s) for s in ("OK", "WARN", "FAIL")}
    overall = "FAIL" if counts["FAIL"] else ("WARN" if counts["WARN"] else "OK")
    return {
        "name": checklist["name"],
        "overall": overall,
        "counts": counts,
        "sections": sections,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# moth takeover — {report['name']}",
        "",
        f"- Overall: `{report['overall']}`"
        f" (OK {report['counts']['OK']} / WARN {report['counts']['WARN']} / FAIL {report['counts']['FAIL']})",
        "",
    ]
    for sec in report["sections"]:
        lines.append(f"## [{sec['status']}] {sec['title']}")
        if sec["detail"]:
            lines.append(f"- {sec['detail']}")
        if sec["lines"]:
            lines.append("```")
            lines.extend(sec["lines"])
            lines.append("```")
        lines.append("")
    return "\n".join(lines)
