"""Explicit detector registry: imports are code-owned, classification is config-owned."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from moth.detectors.apple import detect_apple_project
from moth.detectors.data_ai import detect_data_ai_project
from moth.detectors.mini_program import detect_mini_program
from moth.detectors.multi_repository import detect_multi_repository
from moth.detectors.python_project import detect_python_project
from moth.detectors.web import detect_web_project


Detector = Callable[[str | Path], dict[str, Any]]


DETECTORS: tuple[Detector, ...] = (
    detect_python_project,
    detect_apple_project,
    detect_web_project,
    detect_mini_program,
    detect_data_ai_project,
    detect_multi_repository,
)


def run_detectors(repo_path: str | Path) -> list[dict[str, Any]]:
    return [detector(repo_path) for detector in DETECTORS]
