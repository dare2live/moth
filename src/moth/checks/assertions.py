"""Generic assertion-pack runner: claims-vs-reality reconciliation.

An assertion = a read-only observation + an expectation. Packs are YAML files
owned by the *target repo* (moth owns the engine, never the thresholds — see
AGENTS.md). Motivation: the recurring audit failure mode across repos is not
code shape (codegraph/complexity already cover that) but drift between what
docs/commits *claim* and what the data/files actually *are* — stale sizes,
schema regressions, silent truncation, calendar clamps. Each such incident
becomes one machine-checkable assertion here.

Design rules:
- Fail-closed: execution errors are failures, not skips.
- Read-only: duckdb connections always use ``read_only=True``; shell commands
  run without a shell and with a hard timeout. The engine never mutates the
  target repo.
- Scalar observations: each assertion observes exactly one value and compares
  it against one expectation; complex audits belong in the target repo's own
  tooling and can be surfaced here via the ``shell`` type.

Pack schema (YAML)::

    kind: assertion_pack
    name: my-claims
    assertions:
      - id: unique-stable-id
        claim: "human-readable statement being verified"
        type: duckdb_sql | shell | file_size | file_exists
        # duckdb_sql:
        database: relative/path.duckdb
        query: "SELECT count(*) FROM t"
        # shell:
        command: ["stat", "-f%z", "data/file"]
        # file_size / file_exists:
        path: relative/path
        expect:
          op: "==" | "!=" | ">=" | "<=" | ">" | "<" | between | regex
          value: 42          # comparison ops
          low: 1             # between
          high: 9            # between
          pattern: "^ok$"    # regex
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

SHELL_TIMEOUT_S = 60  # hard ceiling so a wedged probe cannot hang the audit

_REQUIRED_KEYS = ("id", "type", "expect")
_KNOWN_TYPES = ("duckdb_sql", "shell", "file_size", "file_exists")
_KNOWN_OPS = ("==", "!=", ">=", "<=", ">", "<", "between", "regex")


def load_pack(path: str | Path) -> dict[str, Any]:
    """Parse and validate one assertion pack. Raises ValueError on malformed input."""
    pack_path = Path(path)
    raw = yaml.safe_load(pack_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or raw.get("kind") != "assertion_pack":
        raise ValueError(f"{pack_path}: not an assertion_pack (kind missing/mismatch)")
    assertions = raw.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        raise ValueError(f"{pack_path}: assertions must be a non-empty list")
    seen_ids: set[str] = set()
    for idx, entry in enumerate(assertions):
        if not isinstance(entry, dict):
            raise ValueError(f"{pack_path}: assertion #{idx} is not a mapping")
        for key in _REQUIRED_KEYS:
            if key not in entry:
                raise ValueError(f"{pack_path}: assertion #{idx} missing '{key}'")
        if entry["type"] not in _KNOWN_TYPES:
            raise ValueError(f"{pack_path}: assertion '{entry['id']}' unknown type {entry['type']!r}")
        expect = entry["expect"]
        if not isinstance(expect, dict) or expect.get("op") not in _KNOWN_OPS:
            raise ValueError(f"{pack_path}: assertion '{entry['id']}' bad expect/op")
        if entry["id"] in seen_ids:
            raise ValueError(f"{pack_path}: duplicate assertion id '{entry['id']}'")
        seen_ids.add(str(entry["id"]))
    return {
        "name": str(raw.get("name", pack_path.stem)),
        "path": str(pack_path),
        "assertions": assertions,
    }


def _coerce_number(value: Any) -> Any:
    if isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return value
    return value


def _observe(assertion: dict[str, Any], repo_path: Path) -> Any:
    kind = assertion["type"]
    if kind == "duckdb_sql":
        try:
            import duckdb
        except ImportError as exc:  # fail-closed with an actionable message
            raise RuntimeError(
                "duckdb not importable in moth environment; "
                "install duckdb or rewrite the assertion as type=shell"
            ) from exc
        db_path = repo_path / str(assertion["database"])
        conn = duckdb.connect(str(db_path), read_only=True)
        try:
            row = conn.execute(str(assertion["query"])).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    if kind == "shell":
        command = assertion.get("command")
        if not isinstance(command, list) or not command:
            raise ValueError("shell assertion requires a non-empty argv list")
        result = subprocess.run(
            [str(part) for part in command],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=SHELL_TIMEOUT_S,
            check=False,
        )
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip()[-300:]
            raise RuntimeError(f"command exited {result.returncode}: {tail}")
        return _coerce_number(result.stdout.strip())
    if kind == "file_size":
        return (repo_path / str(assertion["path"])).stat().st_size
    if kind == "file_exists":
        return (repo_path / str(assertion["path"])).exists()
    raise ValueError(f"unknown assertion type: {kind}")


def _check(expect: dict[str, Any], observed: Any) -> bool:
    op = expect["op"]
    if op == "regex":
        return re.search(str(expect["pattern"]), str(observed)) is not None
    if op == "between":
        low, high = _coerce_number(expect["low"]), _coerce_number(expect["high"])
        value = _coerce_number(observed)
        return low <= value <= high
    value = _coerce_number(expect["value"])
    obs = _coerce_number(observed)
    if op == "==":
        return obs == value
    if op == "!=":
        return obs != value
    if op == ">=":
        return obs >= value
    if op == "<=":
        return obs <= value
    if op == ">":
        return obs > value
    if op == "<":
        return obs < value
    raise ValueError(f"unknown op: {op}")


def run_pack(pack: dict[str, Any], repo_path: str | Path) -> dict[str, Any]:
    repo = Path(repo_path)
    results: list[dict[str, Any]] = []
    for assertion in pack["assertions"]:
        record: dict[str, Any] = {
            "id": str(assertion["id"]),
            "claim": str(assertion.get("claim", "")),
            "expected": assertion["expect"],
            "observed": None,
            "status": "error",
            "detail": "",
        }
        try:
            observed = _observe(assertion, repo)
            record["observed"] = observed
            record["status"] = "pass" if _check(assertion["expect"], observed) else "fail"
        except Exception as exc:  # noqa: BLE001 — fail-closed: any error is a verdict, never a skip
            record["detail"] = str(exc)[:300]
        results.append(record)
    counts = {status: sum(1 for r in results if r["status"] == status) for status in ("pass", "fail", "error")}
    return {
        "name": pack["name"],
        "path": pack["path"],
        **counts,
        "results": results,
    }


def run_assertion_packs(paths: list[Path], repo_path: str | Path) -> dict[str, Any]:
    """Run every configured pack. Load failures are issues, not silent skips."""
    packs: list[dict[str, Any]] = []
    issues: list[str] = []
    for path in paths:
        try:
            pack = load_pack(path)
        except Exception as exc:  # noqa: BLE001 — malformed pack must surface, never skip
            issues.append(f"assertion pack load failed: {path}: {exc}")
            continue
        packs.append(run_pack(pack, repo_path))
    totals = {
        "pass": sum(p["pass"] for p in packs),
        "fail": sum(p["fail"] for p in packs),
        "error": sum(p["error"] for p in packs),
    }
    verdict = "PASS"
    if issues or totals["fail"] or totals["error"]:
        verdict = "FAIL"
    elif not packs:
        verdict = "NONE"
    return {"verdict": verdict, "totals": totals, "issues": issues, "packs": packs}
