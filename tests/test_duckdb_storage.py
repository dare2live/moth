from __future__ import annotations

from pathlib import Path

import pytest

from moth.checks.duckdb_storage import discover_duckdb_files, scan_duckdb_storage


def test_discover_skips_compact_bak(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "live.duckdb").write_bytes(b"x")
    (data / "live_precompact_bak.duckdb").write_bytes(b"x")
    (data / "other.duckdb").write_bytes(b"x")
    found = {p.name for p in discover_duckdb_files(tmp_path)}
    assert found == {"live.duckdb", "other.duckdb"}


def test_scan_empty_repo_is_quiet(tmp_path: Path) -> None:
    out = scan_duckdb_storage(tmp_path)
    assert out["databases"] == []
    assert out["warnings"] == []


def test_scan_warns_when_free_pct_over_band(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "market.duckdb").write_bytes(b"x")
    monkeypatch.setattr(
        "moth.checks.duckdb_storage._pragma_row",
        lambda _p: {
            "block_size": 262144,
            "total_blocks": 3014,
            "used_blocks": 2265,
            "free_blocks": 749,
            "wasted_bytes": 749 * 262144,
            "free_pct": 24.85,
        },
    )
    out = scan_duckdb_storage(tmp_path, warn_free_pct=10.0)
    assert out["databases"][0]["path"] == "data/market.duckdb"
    assert any("24.85" in item and "free_blocks" in item for item in out["warnings"])


def test_scan_skips_tiny_file_twitch(tmp_path: Path, monkeypatch) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "reference.duckdb").write_bytes(b"x")
    monkeypatch.setattr(
        "moth.checks.duckdb_storage._pragma_row",
        lambda _p: {
            "block_size": 262144,
            "total_blocks": 29,
            "used_blocks": 26,
            "free_blocks": 3,
            "wasted_bytes": 3 * 262144,
            "free_pct": 10.34,
        },
    )
    out = scan_duckdb_storage(tmp_path, warn_free_pct=10.0)
    assert out["warnings"] == []


def test_scan_reads_numeric_pragma(tmp_path: Path) -> None:
    duckdb = pytest.importorskip("duckdb")
    data = tmp_path / "data"
    data.mkdir()
    db = data / "toy.duckdb"
    conn = duckdb.connect(str(db))
    try:
        conn.execute("CREATE TABLE t AS SELECT i FROM range(100) t(i)")
        conn.execute("CHECKPOINT")
    finally:
        conn.close()
    out = scan_duckdb_storage(tmp_path)
    assert len(out["databases"]) == 1
    rec = out["databases"][0]
    assert rec["path"] == "data/toy.duckdb"
    assert rec["free_pct"] is not None
    assert rec["total_blocks"] >= 1
