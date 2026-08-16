"""升级账本自身的校验 —— 它是项目完成度的**唯一权威**, 却一直零校验。

2026-08-16 独立审查发现: `THIRD_PARTY_NOTICES.md` 被列为 stage_8 的 evidence,
而该文件**从未存在**(真实文件是 NOTICE.md), 且 stage_8 是 COMPLETE + residual 为空。
全仓没有任何测试或 gate 校验 ledger 的 evidence 路径是否存在 ——
典型的"验证器自己没被验证"。
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "docs" / "major-upgrade-ledger.yaml"


def _ledger() -> dict:
    return yaml.safe_load(LEDGER.read_text(encoding="utf-8"))


def test_ledger_is_parseable() -> None:
    """先证明它能被解析 —— 手改 YAML 时最常见的破坏是纯文本里的冒号。"""
    data = _ledger()
    assert data["kind"] == "moth_major_upgrade_ledger"
    assert data["stages"], "stages 不得为空"


def test_every_evidence_path_exists() -> None:
    """evidence 指不到的东西 = 账本在拿不存在的文件当完成证据。"""
    missing: list[str] = []
    for stage in _ledger()["stages"]:
        for item in stage.get("evidence") or []:
            if not (REPO_ROOT / item).exists():
                missing.append(f"{stage['id']}: {item}")
    assert not missing, "账本 evidence 路径悬空: " + "; ".join(missing)


def test_stage_states_are_from_the_declared_vocabulary() -> None:
    """状态必须取自 completion_rule 自己声明的词汇表, 不能凭空造词。"""
    data = _ledger()
    allowed = set(data["completion_rule"]["allowed_stage_states"])
    for stage in data["stages"]:
        assert stage["state"] in allowed, f"{stage['id']} 状态 {stage['state']} 不在词汇表"


def test_complete_stages_do_not_hide_open_work_in_residual() -> None:
    """COMPLETE 的 stage 其 residual 只许是**说明**, 不许含未完成措辞。

    1aecd32 把四个 stage 的 `residual: []` 换成了叙述性文字, 从此"有遗留"与"有备注"
    在结构上不可区分 —— 而 completion_rule 里恰恰有一条
    `moth_self_inspection_has_no_required_residual`。本例至少挡住把待办藏进备注。
    """
    open_markers = ("still requires", "not yet", "remains incomplete", "must be accepted")
    offenders: list[str] = []
    for stage in _ledger()["stages"]:
        if stage["state"] != "COMPLETE":
            continue
        for line in stage.get("residual") or []:
            low = str(line).lower()
            if any(m in low for m in open_markers):
                offenders.append(f"{stage['id']}: {str(line)[:70]}")
    assert not offenders, "COMPLETE 的 stage 在 residual 里藏了未完成项: " + "; ".join(offenders)
