from __future__ import annotations

from pathlib import Path


def status_command(root: str | Path) -> list[str]:
    return ["codegraph", "status", str(Path(root))]


def sync_command(root: str | Path) -> list[str]:
    return ["codegraph", "sync", str(Path(root))]


def context_command(root: str | Path, query: str) -> list[str]:
    return ["codegraph", "context", query, "--root", str(Path(root))]


def query_command(root: str | Path, query: str) -> list[str]:
    return ["codegraph", "query", query, "--root", str(Path(root))]
