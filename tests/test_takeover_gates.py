"""takeover + gates 测试 (迁移自 sherpa/tests/test_sherpa.py, 2026-07-02 并入 moth)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from moth.cli import main
from moth.gates import list_gates, run_gate
from moth.takeover import find_checklist, load_checklist, run_takeover
from moth.takeover_scaffold import init_takeover


def _checklist(tmp_path: Path, sections: list[dict]) -> dict:
    p = tmp_path / "takeover.yaml"
    p.write_text(yaml.safe_dump({"kind": "takeover_checklist", "name": "demo", "sections": sections}))
    return load_checklist(p)


def _gate_pack_payload() -> dict:
    return {
        "kind": "assertion_pack",
        "name": "demo_exp",
        "assertions": [
            {"id": "g1", "claim": "ok", "type": "shell", "command": ["echo", "7"],
             "expect": {"op": "==", "value": 7}},
            {"id": "g2", "claim": "red", "type": "shell", "command": ["echo", "0"],
             "expect": {"op": ">", "value": 5}},
        ],
    }


def test_takeover_ok_warn_fail_and_overall(tmp_path: Path) -> None:
    checklist = _checklist(tmp_path, [
        {"id": "ok", "command": ["echo", "all good"]},
        {"id": "warn", "command": ["echo", "3 WARN items"], "warn_regex": "WARN"},
        {"id": "red", "command": ["echo", "ALERT flag present"], "fail_regex": "ALERT"},
        {"id": "probe", "command": ["echo", "silence"], "ok_requires_regex": "READY"},
        {"id": "crash", "command": ["false"]},
    ])
    report = run_takeover(checklist, tmp_path)
    by_id = {s["id"]: s for s in report["sections"]}
    # red→green 实证: 三种失败路径全部物理可红 (fail_regex / 缺必需 pattern / 非零退出)
    assert by_id["ok"]["status"] == "OK"
    assert by_id["warn"]["status"] == "WARN"
    assert by_id["red"]["status"] == "FAIL"
    assert by_id["probe"]["status"] == "FAIL"  # 沉默不是成功 (探活型)
    assert by_id["crash"]["status"] == "FAIL" and by_id["crash"]["detail"] == "exit 1"
    assert report["overall"] == "FAIL"
    assert report["counts"] == {"OK": 1, "WARN": 1, "FAIL": 3}


def test_takeover_all_green(tmp_path: Path) -> None:
    checklist = _checklist(tmp_path, [{"id": "a", "command": ["echo", "x"]}])
    assert run_takeover(checklist, tmp_path)["overall"] == "OK"


def test_checklist_validation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("kind: nope\n")
    with pytest.raises(ValueError):
        load_checklist(bad)
    with pytest.raises(ValueError, match="argv list"):
        _checklist(tmp_path, [{"id": "a", "command": "echo x"}])


def test_find_checklist_prefers_sherpa_dir_then_moth(tmp_path: Path) -> None:
    # 兼容: 旧 .sherpa/ 约定优先, 其次 .moth/, 都无 = None。
    assert find_checklist(tmp_path) is None

    moth_dir = tmp_path / ".moth"
    moth_dir.mkdir()
    (moth_dir / "takeover.yaml").write_text(
        yaml.safe_dump({"kind": "takeover_checklist", "name": "moth-side",
                        "sections": [{"id": "a", "command": ["echo", "x"]}]})
    )
    assert find_checklist(tmp_path) == moth_dir / "takeover.yaml"

    sherpa_dir = tmp_path / ".sherpa"
    sherpa_dir.mkdir()
    (sherpa_dir / "takeover.yaml").write_text(
        yaml.safe_dump({"kind": "takeover_checklist", "name": "sherpa-side",
                        "sections": [{"id": "a", "command": ["echo", "x"]}]})
    )
    assert find_checklist(tmp_path) == sherpa_dir / "takeover.yaml"


def test_gates_round_trip_sherpa_dir(tmp_path: Path) -> None:
    gate_dir = tmp_path / ".sherpa" / "gates"
    gate_dir.mkdir(parents=True)
    (gate_dir / "demo_exp.yaml").write_text(yaml.safe_dump(_gate_pack_payload()))
    assert list_gates(tmp_path) == ["demo_exp"]
    result = run_gate(tmp_path, "demo_exp")
    assert result["go"] is False and result["pass"] == 1 and result["fail"] == 1
    with pytest.raises(FileNotFoundError):
        run_gate(tmp_path, "nope")


def test_gates_round_trip_moth_dir(tmp_path: Path) -> None:
    gate_dir = tmp_path / ".moth" / "gates"
    gate_dir.mkdir(parents=True)
    (gate_dir / "demo_exp.yaml").write_text(yaml.safe_dump(_gate_pack_payload()))
    assert list_gates(tmp_path) == ["demo_exp"]
    result = run_gate(tmp_path, "demo_exp")
    assert result["go"] is False and result["pass"] == 1 and result["fail"] == 1


def test_gates_list_unions_both_dirs(tmp_path: Path) -> None:
    sherpa_gates = tmp_path / ".sherpa" / "gates"
    moth_gates = tmp_path / ".moth" / "gates"
    sherpa_gates.mkdir(parents=True)
    moth_gates.mkdir(parents=True)
    (sherpa_gates / "old_exp.yaml").write_text(yaml.safe_dump(_gate_pack_payload()))
    (moth_gates / "new_exp.yaml").write_text(yaml.safe_dump(_gate_pack_payload()))
    assert list_gates(tmp_path) == ["new_exp", "old_exp"]


def test_init_takeover_scaffold_and_idempotent(tmp_path: Path) -> None:
    created = init_takeover(tmp_path, name="demo")
    assert any(p.endswith("takeover.yaml") for p in created)
    # 模板本身必须可被 load_checklist 解析 (模板腐烂防线); moth 侧默认写 .moth/。
    checklist = load_checklist(tmp_path / ".moth" / "takeover.yaml")
    assert checklist["name"] == "demo" and len(checklist["sections"]) >= 2
    # 幂等: 二次 init 不覆盖
    assert init_takeover(tmp_path) == []


def test_cli_takeover_missing_checklist_actionable(tmp_path: Path, capsys) -> None:
    rc = main(["takeover", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 2
    assert "moth init" in out  # 可行动指引, 不是裸 traceback


def test_cli_takeover_reads_sherpa_and_moth_locations(tmp_path: Path, capsys) -> None:
    # .moth/ 侧
    repo_a = tmp_path / "repo-a"
    (repo_a / ".moth").mkdir(parents=True)
    (repo_a / ".moth" / "takeover.yaml").write_text(
        yaml.safe_dump({"kind": "takeover_checklist", "name": "repo-a",
                        "sections": [{"id": "a", "command": ["echo", "x"]}]})
    )
    rc = main(["takeover", "--repo", str(repo_a), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload["overall"] == "OK" and payload["name"] == "repo-a"

    # .sherpa/ 兼容侧 (FAIL 路径顺带验 exit 1)
    repo_b = tmp_path / "repo-b"
    (repo_b / ".sherpa").mkdir(parents=True)
    (repo_b / ".sherpa" / "takeover.yaml").write_text(
        yaml.safe_dump({"kind": "takeover_checklist", "name": "repo-b",
                        "sections": [{"id": "red", "command": ["echo", "ALERT"], "fail_regex": "ALERT"}]})
    )
    rc = main(["takeover", "--repo", str(repo_b), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1 and payload["overall"] == "FAIL" and payload["name"] == "repo-b"


def test_cli_gates_runs_and_lists(tmp_path: Path, capsys) -> None:
    gate_dir = tmp_path / ".moth" / "gates"
    gate_dir.mkdir(parents=True)
    (gate_dir / "demo_exp.yaml").write_text(yaml.safe_dump(_gate_pack_payload()))

    rc = main(["gates", "--repo", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "demo_exp" in out

    rc = main(["gates", "--repo", str(tmp_path), "demo_exp", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1 and payload["go"] is False  # NO-GO = exit 1

    rc = main(["gates", "--repo", str(tmp_path), "nope"])
    out = capsys.readouterr().out
    assert rc == 2 and "gate 包不存在" in out


def test_moth_init_creates_takeover_template(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    rc = main(["init", "--repo", str(repo), "--name", "sample-repo", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert any(p.endswith("takeover.yaml") for p in payload["takeover_scaffold"])
    assert (repo / ".moth" / "takeover.yaml").exists()
    # 生成的模板可直接被引擎消费
    checklist = load_checklist(repo / ".moth" / "takeover.yaml")
    assert checklist["name"] == "sample-repo"
