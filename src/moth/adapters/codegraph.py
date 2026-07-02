from __future__ import annotations

import re
import json
import subprocess
from pathlib import Path
from typing import Any

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_INDEX_FIELDS = {"files", "nodes", "edges"}
_INDEX_SECTION = "index"
_NODES_SECTION = "nodes"
_LANGUAGE_SECTION = "language"
_STATUS_UP_TO_DATE = "Index is up to date"
_STATUS_NOT_INITIALIZED = "Not initialized"


def status_command(root: str | Path) -> list[str]:
    return ["codegraph", "status", str(Path(root)), "--json"]


def sync_command(root: str | Path) -> list[str]:
    return ["codegraph", "sync", str(Path(root))]


def context_command(root: str | Path, query: str) -> list[str]:
    return explore_command(root, query)


def explore_command(root: str | Path, query: str, *, max_files: int | None = None) -> list[str]:
    command = ["codegraph", "explore", query, "--path", str(Path(root))]
    if max_files is not None:
        command.extend(["--max-files", str(max_files)])
    return command


def query_command(root: str | Path, query: str) -> list[str]:
    return ["codegraph", "query", query, "--path", str(Path(root))]


def version_command() -> list[str]:
    return ["codegraph", "version"]


def affected_command(
    root: str | Path,
    files: list[str | Path],
    *,
    depth: int = 5,
    test_filter: str | None = None,
) -> list[str]:
    command = [
        "codegraph",
        "affected",
        "--path",
        str(Path(root)),
        "--depth",
        str(depth),
        "--json",
    ]
    if test_filter:
        command.extend(["--filter", test_filter])
    command.extend(str(file) for file in files)
    return command


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _parse_int(value: str) -> int:
    return int(value.replace(",", "").strip())


def _parse_status_output(stdout: str) -> dict[str, Any]:
    text = _strip_ansi(stdout)
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, dict):
        return _parse_status_json(loaded, text)

    index_up_to_date = _STATUS_UP_TO_DATE in text
    state = "UNKNOWN"
    issues: list[str] = []
    index_statistics: dict[str, Any] = {}
    nodes_by_kind: dict[str, int] = {}
    files_by_language: dict[str, int] = {}
    section: str | None = None

    if _STATUS_NOT_INITIALIZED in text:
        state = "NOT_INITIALIZED"
        issues.append("codegraph not initialized")
    elif index_up_to_date:
        state = "UP_TO_DATE"
    elif text.strip():
        state = "STALE"
        issues.append("codegraph index is not up to date")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "Index Statistics:":
            section = _INDEX_SECTION
            continue
        if line == "Nodes by Kind:":
            section = _NODES_SECTION
            continue
        if line == "Files by Language:":
            section = _LANGUAGE_SECTION
            continue
        if line.startswith(("✓", "ℹ")):
            continue
        if section == _INDEX_SECTION:
            match = re.match(r"^(Files|Nodes|Edges|DB Size):\s+(.+)$", line)
            if not match:
                continue
            key, value = match.groups()
            key = key.lower().replace(" ", "_")
            if key == "files" or key == "nodes" or key == "edges":
                index_statistics[key] = _parse_int(value)
            else:
                index_statistics[key] = value
            continue
        if section == _NODES_SECTION:
            match = re.match(r"^([A-Za-z][A-Za-z0-9 _/-]*?)\s+([0-9][0-9,]*)$", line)
            if not match:
                continue
            key, value = match.groups()
            nodes_by_kind[key.strip()] = _parse_int(value)
            continue
        if section == _LANGUAGE_SECTION:
            match = re.match(r"^([A-Za-z][A-Za-z0-9 _./-]*?)\s+([0-9][0-9,]*)$", line)
            if not match:
                continue
            key, value = match.groups()
            files_by_language[key.strip()] = _parse_int(value)

    return {
        "index_up_to_date": index_up_to_date,
        "state": state,
        "issues": issues,
        "index_statistics": index_statistics,
        "nodes_by_kind": nodes_by_kind,
        "files_by_language": files_by_language,
        "rendered_stdout": text,
    }


def _int_from_json(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _parse_status_json(payload: dict[str, Any], rendered_stdout: str) -> dict[str, Any]:
    initialized = bool(payload.get("initialized"))
    pending = payload.get("pendingChanges") if isinstance(payload.get("pendingChanges"), dict) else {}
    pending_added = _int_from_json(pending.get("added"))
    pending_modified = _int_from_json(pending.get("modified"))
    pending_removed = _int_from_json(pending.get("removed"))
    pending_total = pending_added + pending_modified + pending_removed
    index_meta = payload.get("index") if isinstance(payload.get("index"), dict) else {}
    reindex_recommended = bool(index_meta.get("reindexRecommended"))
    worktree_mismatch = payload.get("worktreeMismatch")

    issues: list[str] = []
    if not initialized:
        state = "NOT_INITIALIZED"
        issues.append("codegraph not initialized")
    elif worktree_mismatch:
        state = "STALE"
        issues.append(f"codegraph worktree mismatch: {worktree_mismatch}")
    elif reindex_recommended:
        state = "STALE"
        issues.append("codegraph reindex recommended")
    elif pending_total:
        state = "STALE"
        issues.append(
            "codegraph pending changes: "
            f"added={pending_added}, modified={pending_modified}, removed={pending_removed}"
        )
    else:
        state = "UP_TO_DATE"

    nodes_by_kind = payload.get("nodesByKind") if isinstance(payload.get("nodesByKind"), dict) else {}
    languages = payload.get("languages") if isinstance(payload.get("languages"), list) else []
    index_statistics = {
        "files": _int_from_json(payload.get("fileCount")),
        "nodes": _int_from_json(payload.get("nodeCount")),
        "edges": _int_from_json(payload.get("edgeCount")),
        "db_size_bytes": _int_from_json(payload.get("dbSizeBytes")),
        "backend": payload.get("backend"),
        "journal": payload.get("journalMode"),
    }

    return {
        "index_up_to_date": state == "UP_TO_DATE",
        "state": state,
        "issues": issues,
        "version": payload.get("version"),
        "project_path": payload.get("projectPath"),
        "index_path": payload.get("indexPath"),
        "last_indexed": payload.get("lastIndexed"),
        "pending_changes": {
            "added": pending_added,
            "modified": pending_modified,
            "removed": pending_removed,
        },
        "worktree_mismatch": worktree_mismatch,
        "index": index_meta,
        "index_statistics": index_statistics,
        "nodes_by_kind": {str(key): _int_from_json(value) for key, value in nodes_by_kind.items()},
        "files_by_language": {},
        "languages": [str(item) for item in languages],
        "rendered_stdout": rendered_stdout,
    }


def run_status(root: str | Path) -> dict[str, Any]:
    command = status_command(root)
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except Exception as exc:  # pragma: no cover - defensive guard
        return {
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
            "verdict": "FAIL",
            "state": "UNKNOWN",
            "index_up_to_date": False,
            "issues": [f"codegraph status failed: {exc}"],
            "index_statistics": {},
            "nodes_by_kind": {},
            "files_by_language": {},
        }
    parsed = _parse_status_output(stdout)
    if returncode != 0:
        verdict = "FAIL"
        if not parsed["issues"]:
            parsed["issues"] = [f"codegraph status exited {returncode}"]
    elif parsed["index_up_to_date"]:
        verdict = "PASS"
    else:
        verdict = "WARN"
        if not parsed["issues"]:
            parsed["issues"] = [f"codegraph status returned {parsed['state'].lower()}"]
    return {
        "command": command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "verdict": verdict,
        **parsed,
    }


def run_sync(root: str | Path) -> dict[str, Any]:
    command = sync_command(root)
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except Exception as exc:  # pragma: no cover - defensive guard
        return {
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
            "verdict": "FAIL",
            "issues": [f"codegraph sync failed: {exc}"],
        }

    issues: list[str] = []
    if returncode != 0:
        verdict = "FAIL"
        issues.append(f"codegraph sync exited {returncode}")
    else:
        verdict = "PASS"

    return {
        "command": command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "verdict": verdict,
        "issues": issues,
    }


def run_affected(
    root: str | Path,
    files: list[str | Path],
    *,
    depth: int = 5,
    test_filter: str | None = None,
) -> dict[str, Any]:
    command = affected_command(root, files, depth=depth, test_filter=test_filter)
    if not files:
        return {
            "command": command,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "verdict": "PASS",
            "issues": [],
            "changedFiles": [],
            "affectedTests": [],
            "totalDependentsTraversed": 0,
        }
    try:
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except Exception as exc:  # pragma: no cover - defensive guard
        return {
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
            "verdict": "FAIL",
            "issues": [f"codegraph affected failed: {exc}"],
            "changedFiles": [str(file) for file in files],
            "affectedTests": [],
            "totalDependentsTraversed": 0,
        }

    issues: list[str] = []
    parsed: dict[str, Any] = {}
    if returncode != 0:
        verdict = "FAIL"
        issues.append(f"codegraph affected exited {returncode}")
    else:
        try:
            loaded = json.loads(stdout or "{}")
            if not isinstance(loaded, dict):
                raise ValueError("codegraph affected must emit a JSON object")
            parsed = loaded
        except Exception as exc:
            verdict = "FAIL"
            issues.append(f"failed to parse codegraph affected output: {exc}")
        else:
            verdict = "PASS"

    return {
        "command": command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "verdict": verdict,
        "issues": issues,
        "changedFiles": parsed.get("changedFiles", [str(file) for file in files]),
        "affectedTests": parsed.get("affectedTests", []),
        "totalDependentsTraversed": parsed.get("totalDependentsTraversed", 0),
    }
