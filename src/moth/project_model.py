"""Canonical project model composed from bounded detectors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moth.detectors.python_project import detect_python_project


def build_project_model(repo_path: str | Path) -> dict[str, Any]:
    detected = detect_python_project(repo_path)
    if detected["issues"]:
        verdict = "FAIL"
    elif detected["warnings"]:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return {
        "schema_version": "moth.project-model.v1",
        "verdict": verdict,
        "project": detected["project"],
        "applications": detected["applications"],
        "runtimes": detected["runtimes"],
        "modules": detected["modules"],
        "evidence": detected["evidence"],
        "coverage": {
            "detectors": [detected["detector"]],
            "issues": detected["issues"],
            "warnings": detected["warnings"],
        },
    }
