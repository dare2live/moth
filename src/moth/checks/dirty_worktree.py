from __future__ import annotations

import subprocess
from pathlib import Path


def git_status(repo_path: str | Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(Path(repo_path)), "status", "--short"],
        check=False,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]
