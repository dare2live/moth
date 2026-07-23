from __future__ import annotations

import subprocess
from pathlib import Path


def git_status(
    repo_path: str | Path,
    *,
    isolate_repo_extensions: bool = False,
) -> list[str]:
    command = ["git"]
    if isolate_repo_extensions:
        command.extend(
            [
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.untrackedCache=false",
            ]
        )
    command.extend(["-C", str(Path(repo_path)), "status", "--short"])
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]
