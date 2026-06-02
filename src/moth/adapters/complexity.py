from __future__ import annotations

from pathlib import Path


def analyze_command(repo_path: str | Path, script_path: str | Path, *, format: str = "markdown") -> list[str]:
    return ["python", str(Path(script_path)), str(Path(repo_path)), "--format", format]
