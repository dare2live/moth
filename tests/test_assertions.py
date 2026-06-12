from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from moth.checks.assertions import load_pack, run_assertion_packs, run_pack


def _write_pack(tmp_path: Path, assertions: list[dict], name: str = "demo") -> Path:
    path = tmp_path / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump({"kind": "assertion_pack", "name": name, "assertions": assertions}),
        encoding="utf-8",
    )
    return path


def test_load_pack_rejects_malformed(tmp_path: Path) -> None:
    bad_kind = tmp_path / "bad.yaml"
    bad_kind.write_text("kind: nope\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_pack(bad_kind)

    with pytest.raises(ValueError, match="duplicate"):
        load_pack(
            _write_pack(
                tmp_path,
                [
                    {"id": "a", "type": "file_exists", "path": "x", "expect": {"op": "==", "value": True}},
                    {"id": "a", "type": "file_exists", "path": "y", "expect": {"op": "==", "value": True}},
                ],
                name="dup",
            )
        )

    with pytest.raises(ValueError, match="bad expect"):
        load_pack(
            _write_pack(
                tmp_path,
                [{"id": "a", "type": "shell", "command": ["true"], "expect": {"op": "~="}}],
                name="badop",
            )
        )


def test_shell_assertion_pass_fail_and_error(tmp_path: Path) -> None:
    pack = load_pack(
        _write_pack(
            tmp_path,
            [
                {"id": "ok", "type": "shell", "command": ["echo", "42"], "expect": {"op": "==", "value": 42}},
                {"id": "red", "type": "shell", "command": ["echo", "41"], "expect": {"op": "==", "value": 42}},
                {"id": "boom", "type": "shell", "command": ["false"], "expect": {"op": "==", "value": 0}},
            ],
        )
    )
    result = run_pack(pack, tmp_path)
    by_id = {r["id"]: r for r in result["results"]}
    # red→green 实证: 引擎必须物理上能红 (print-not-fail 反模式防线)
    assert by_id["ok"]["status"] == "pass"
    assert by_id["red"]["status"] == "fail" and by_id["red"]["observed"] == 41
    assert by_id["boom"]["status"] == "error" and "exited 1" in by_id["boom"]["detail"]
    assert (result["pass"], result["fail"], result["error"]) == (1, 1, 1)


def test_between_regex_and_file_ops(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"x" * 100)
    pack = load_pack(
        _write_pack(
            tmp_path,
            [
                {"id": "size", "type": "file_size", "path": "payload.bin", "expect": {"op": "between", "low": 50, "high": 150}},
                {"id": "exists", "type": "file_exists", "path": "payload.bin", "expect": {"op": "==", "value": True}},
                {"id": "rx", "type": "shell", "command": ["echo", "status: PASS"], "expect": {"op": "regex", "pattern": "PASS$"}},
                {"id": "missing", "type": "file_size", "path": "nope.bin", "expect": {"op": ">", "value": 0}},
            ],
        )
    )
    result = run_pack(pack, tmp_path)
    by_id = {r["id"]: r for r in result["results"]}
    assert by_id["size"]["status"] == "pass"
    assert by_id["exists"]["status"] == "pass"
    assert by_id["rx"]["status"] == "pass"
    # 文件缺失是 error (fail-closed), 不是 skip
    assert by_id["missing"]["status"] == "error"


def test_duckdb_assertion_round_trip(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "mini.duckdb"
    conn = duckdb.connect(str(db))
    conn.execute("CREATE TABLE t (x INTEGER); INSERT INTO t VALUES (1), (2), (3)")
    conn.close()
    pack = load_pack(
        _write_pack(
            tmp_path,
            [
                {"id": "rows", "type": "duckdb_sql", "database": "mini.duckdb", "query": "SELECT count(*) FROM t", "expect": {"op": "==", "value": 3}},
                {"id": "drift", "type": "duckdb_sql", "database": "mini.duckdb", "query": "SELECT max(x) FROM t", "expect": {"op": ">=", "value": 10}},
            ],
        )
    )
    result = run_pack(pack, tmp_path)
    by_id = {r["id"]: r for r in result["results"]}
    assert by_id["rows"]["status"] == "pass"
    assert by_id["drift"]["status"] == "fail" and by_id["drift"]["observed"] == 3


def test_run_assertion_packs_fail_closed_on_load(tmp_path: Path) -> None:
    broken = tmp_path / "broken.yaml"
    broken.write_text("kind: assertion_pack\nassertions: []\n", encoding="utf-8")
    good = _write_pack(
        tmp_path,
        [{"id": "ok", "type": "shell", "command": ["echo", "1"], "expect": {"op": "==", "value": 1}}],
        name="good",
    )
    outcome = run_assertion_packs([broken, good], tmp_path)
    assert outcome["verdict"] == "FAIL"  # 坏弹仓必须把整体打红, 不许静默跳过
    assert any("load failed" in issue for issue in outcome["issues"])
    assert outcome["totals"]["pass"] == 1

    empty = run_assertion_packs([], tmp_path)
    assert empty["verdict"] == "NONE"
