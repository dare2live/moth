"""Scan DuckDB files for unreclaimed free blocks.

Moth owns the engine, never project thresholds. File-size bands are a ratchet:
they rise with legitimate growth and cannot see ``DROP``/``DELETE``/``UPDATE``
that leave dead blocks. ``CHECKPOINT`` does not shrink the file. The honest
observation is ``pragma_database_size().free_blocks / total_blocks``.

Default glob is ``data/*.duckdb`` (skip compact bak). Warnings fire at
``DEFAULT_WARN_FREE_PCT``; blocking numbers stay in the target repo's
assertion packs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_GLOBS = ("data/*.duckdb",)
DEFAULT_WARN_FREE_PCT = 10.0
_SKIP_NAME_PARTS = ("_precompact", "_bak", "-wal", "-shm")


def discover_duckdb_files(
    repo_path: str | Path,
    globs: tuple[str, ...] = DEFAULT_GLOBS,
) -> list[Path]:
    repo = Path(repo_path)
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in globs:
        for path in sorted(repo.glob(pattern)):
            if not path.is_file():
                continue
            name = path.name
            if any(part in name for part in _SKIP_NAME_PARTS):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(path)
    return found


def _free_pct(free_blocks: Any, total_blocks: Any) -> float | None:
    try:
        total = float(total_blocks or 0)
        free = float(free_blocks or 0)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return 100.0 * free / total


def _pragma_row(path: Path) -> dict[str, Any]:
    import duckdb

    conn = duckdb.connect(str(path), read_only=True)
    try:
        # database_size / wal_size are human strings ('753.5 MiB'); do not int() them.
        row = conn.execute(
            "SELECT block_size, total_blocks, used_blocks, free_blocks "
            "FROM pragma_database_size()"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise RuntimeError("pragma_database_size returned no row")
    block_size, total_blocks, used_blocks, free_blocks = row
    pct = _free_pct(free_blocks, total_blocks)
    block_size_i = int(block_size or 0)
    free_i = int(free_blocks or 0)
    return {
        "block_size": block_size_i,
        "total_blocks": int(total_blocks or 0),
        "used_blocks": int(used_blocks or 0),
        "free_blocks": free_i,
        "wasted_bytes": free_i * block_size_i,
        "free_pct": None if pct is None else round(pct, 2),
    }


def scan_duckdb_storage(
    repo_path: str | Path,
    *,
    warn_free_pct: float = DEFAULT_WARN_FREE_PCT,
    globs: tuple[str, ...] = DEFAULT_GLOBS,
) -> dict[str, Any]:
    repo = Path(repo_path)
    files = discover_duckdb_files(repo, globs)
    payload: dict[str, Any] = {
        "warn_free_pct": warn_free_pct,
        "globs": list(globs),
        "databases": [],
        "warnings": [],
    }
    if not files:
        return payload
    try:
        import duckdb  # noqa: F401
    except ImportError:
        payload["warnings"].append(
            "duckdb storage: files present but duckdb is not importable "
            "(install moth[assertions]); size-band ratchets cannot see free blocks"
        )
        return payload

    for path in files:
        rel = str(path.relative_to(repo)) if path.is_relative_to(repo) else str(path)
        try:
            info = _pragma_row(path)
        except Exception as exc:  # noqa: BLE001
            payload["warnings"].append(
                f"duckdb storage: {rel} unreadable ({type(exc).__name__}: {exc})"
            )
            payload["databases"].append({"path": rel, "error": type(exc).__name__})
            continue
        rec = {"path": rel, **info}
        payload["databases"].append(rec)
        pct = rec.get("free_pct")
        wasted = int(rec.get("wasted_bytes") or 0)
        total = int(rec.get("total_blocks") or 0)
        # Tiny files twitch at 10% (3/29 blocks). Warn when the hole is real:
        # enough wasted bytes, or a file large enough that 10% is a silent leak.
        notable = wasted >= 16 * 1024 * 1024 or total >= 64
        if pct is not None and notable and pct + 1e-9 >= warn_free_pct:
            payload["warnings"].append(
                f"duckdb storage: {rel} free_blocks {pct:.2f}% "
                f"({rec['free_blocks']}/{rec['total_blocks']}, "
                f"wasted={wasted}B) ≥ {warn_free_pct:g}% "
                "— file_size ratchets miss this; compact needed"
            )
    return payload
