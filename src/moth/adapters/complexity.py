from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


def analyze_command(repo_path: str | Path, script_path: str | Path, *, format: str = "markdown") -> list[str]:
    return ["python", str(Path(script_path)), str(Path(repo_path)), "--format", format]


def _force_json_format(command: Sequence[str]) -> list[str]:
    result = [str(part) for part in command]
    if "--format" in result:
        index = result.index("--format")
        if index + 1 < len(result):
            result[index + 1] = "json"
        else:
            result.append("json")
        return result
    if "-f" in result:
        index = result.index("-f")
        if index + 1 < len(result):
            result[index + 1] = "json"
        else:
            result.append("json")
        return result
    result.extend(["--format", "json"])
    return result


def _parse_findings(stdout: str) -> list[dict[str, Any]]:
    payload = json.loads(stdout or "[]")
    if not isinstance(payload, list):
        raise ValueError("complexity analyzer must emit a JSON list")
    return [item for item in payload if isinstance(item, dict)]


def _counts(findings: list[dict[str, Any]], field: str) -> dict[str, int]:
    counter = Counter(str(finding.get(field, "")).strip() for finding in findings if finding.get(field))
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def run_analysis(root: str | Path, command: Sequence[str]) -> dict[str, Any]:
    normalized_command = _force_json_format(command)
    try:
        completed = subprocess.run(
            normalized_command,
            check=False,
            capture_output=True,
            text=True,
            cwd=str(Path(root)),
        )
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except Exception as exc:  # pragma: no cover - defensive guard
        return {
            "command": normalized_command,
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
            "verdict": "FAIL",
            "issues": [f"complexity analyzer failed: {exc}"],
            "findings": [],
            "summary": {
                "finding_count": 0,
                "severity_counts": {},
                "kind_counts": {},
                "high_count": 0,
                "medium_count": 0,
                "info_count": 0,
            },
        }
    issues: list[str] = []
    findings: list[dict[str, Any]] = []
    if returncode != 0:
        verdict = "FAIL"
        issues.append(f"complexity analyzer exited {returncode}")
    else:
        try:
            findings = _parse_findings(stdout)
        except Exception as exc:
            verdict = "FAIL"
            issues.append(f"failed to parse complexity output: {exc}")
        else:
            verdict = "PASS"

    severity_counts = _counts(findings, "severity")
    kind_counts = _counts(findings, "kind")
    return {
        "command": normalized_command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "verdict": verdict,
        "issues": issues,
        "findings": findings,
        "summary": {
            "finding_count": len(findings),
            "severity_counts": severity_counts,
            "kind_counts": kind_counts,
            "high_count": severity_counts.get("high", 0),
            "medium_count": severity_counts.get("medium", 0),
            "info_count": severity_counts.get("info", 0),
        },
    }
