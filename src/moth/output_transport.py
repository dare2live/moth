"""Shared CLI output-target semantics."""

from __future__ import annotations

from pathlib import Path


STDOUT_TARGET = "-"
OUTPUT_TARGET_HELP = (
    "Optional file path for a secondary copy; use '-' for stdout without a file"
)


def persist_optional_output(output_target: str | None, rendered: str) -> None:
    """Persist a secondary file copy unless the target denotes stdout.

    Moth commands always emit their rendered result on stdout. ``--output`` is
    an optional additional file sink, while the conventional ``-`` target
    explicitly selects stdout and must never be interpreted as a filename.
    """

    if not output_target or output_target == STDOUT_TARGET:
        return
    path = Path(output_target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")
