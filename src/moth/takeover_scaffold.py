"""takeover 脚手架 — 在目标 repo 创建 takeover 清单模板 + gates 目录 (并入自 sherpa init).

moth 侧默认写 .moth/ (moth init 顺带调用); 旧 sherpa 仓的 .sherpa/ 约定继续被
moth takeover / moth gates 兼容读取, 不需要迁移。
"""

from __future__ import annotations

from pathlib import Path

TAKEOVER_TEMPLATE = """\
kind: takeover_checklist
name: {name}
# 新 session 第一条命令: moth takeover --repo <本仓路径>
# 每节 = 一条只读命令 + 可选判定; 判定规则:
#   fail_regex: 输出匹配 -> FAIL | warn_regex: 匹配 -> WARN
#   ok_requires_regex: 输出必须匹配, 否则 FAIL (探活节必配 — 沉默不是成功)
# 命令非零退出/超时 = FAIL (fail-closed)。按本仓实情增删节。
sections:
  - id: git-status
    title: "脏 worktree (有未 commit = 上个 session 没收尾)"
    command: ["git", "status", "--short"]
    warn_regex: "."
  - id: alert-flags
    title: "告警 flag (按本仓约定改路径; 无告警机制可删本节)"
    command: ["bash", "-c", "ls /tmp/{name}_ALERT_*.flag 2>/dev/null | grep . && echo FLAGS_PRESENT || echo NO_FLAGS"]
    fail_regex: "FLAGS_PRESENT"
    ok_requires_regex: "NO_FLAGS|FLAGS_PRESENT"
  # - id: tests
  #   title: "测试基线 (重则另开节跑子集)"
  #   command: ["python", "-m", "pytest", "-q", "--collect-only", "-q"]
  #   timeout_s: 120
  #   ok_requires_regex: "test"
"""


def init_takeover(repo: str | Path, name: str | None = None, dirname: str = ".moth") -> list[str]:
    """创建 <repo>/<dirname>/takeover.yaml + gates/ (幂等: 已存在的不覆盖)。返回创建清单."""
    repo_path = Path(repo)
    repo_name = name or repo_path.resolve().name
    created: list[str] = []
    base_dir = repo_path / dirname
    gates_dir = base_dir / "gates"
    gates_dir.mkdir(parents=True, exist_ok=True)
    checklist = base_dir / "takeover.yaml"
    if checklist.exists():
        return created  # 不覆盖已有清单 (幂等)
    checklist.write_text(TAKEOVER_TEMPLATE.format(name=repo_name), encoding="utf-8")
    created.append(str(checklist))
    keep = gates_dir / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
        created.append(str(keep))
    return created
