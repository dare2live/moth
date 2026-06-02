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


def _normalize_finding(raw: dict[str, Any]) -> dict[str, Any]:
    message = raw.get("message") if raw.get("message") is not None else raw.get("finding")
    return {
        "severity": str(raw.get("severity") or "").strip().lower(),
        "kind": str(raw.get("kind") or "").strip(),
        "path": str(raw.get("path") or "").strip(),
        "line": int(raw.get("line") or 0),
        "message": str(message or "").strip(),
        "suggestion": str(raw.get("suggestion") or "").strip(),
    }


def load_complexity_baseline(path: Path | None) -> tuple[list[dict[str, Any]], str]:
    if not path:
        return [], "not_configured"
    if not path.exists():
        return [], "missing"
    loaded = json.loads(path.read_text(encoding="utf-8"))
    raw_findings = loaded.get("findings") if isinstance(loaded, dict) else loaded
    if isinstance(loaded, dict) and raw_findings is None:
        raw_findings = loaded.get("complexity", {}).get("findings", [])
    if not isinstance(raw_findings, list):
        raise ValueError(f"{path} does not contain a findings list")
    normalized: list[dict[str, Any]] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            raise ValueError(f"{path} contains a non-mapping finding entry")
        normalized.append(_normalize_finding(item))
    return normalized, "loaded"


def _finding_identity(finding: dict[str, Any], mode: str) -> tuple[Any, ...]:
    if mode == "path_kind_message":
        return (
            finding.get("severity"),
            finding.get("kind"),
            finding.get("path"),
            finding.get("message"),
        )
    return (
        finding.get("severity"),
        finding.get("kind"),
        finding.get("path"),
        finding.get("line"),
        finding.get("message"),
    )


def _finding_sort_key(finding: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(finding.get("path") or ""),
        int(finding.get("line") or 0),
        str(finding.get("severity") or ""),
        str(finding.get("kind") or ""),
    )


def build_complexity_diff_report(
    current_findings: list[dict[str, Any]],
    baseline_findings: list[dict[str, Any]],
    *,
    baseline_status: str,
    identity_mode: str = "path_kind_message",
) -> dict[str, Any]:
    current = [_normalize_finding(item) for item in current_findings if isinstance(item, dict)]
    baseline = [_normalize_finding(item) for item in baseline_findings if isinstance(item, dict)]
    if baseline_status != "loaded":
        return {
            "status": "baseline_unavailable",
            "baseline_status": baseline_status,
            "baseline_count": len(baseline),
            "current_count": len(current),
            "new_count": 0,
            "resolved_count": 0,
            "unchanged_count": 0,
            "new_high_count": 0,
            "new_findings": [],
            "resolved_findings": [],
            "unchanged_findings": [],
            "unclassified_count": len(current),
            "unclassified_high_count": sum(1 for finding in current if finding.get("severity") == "high"),
            "note": "Baseline is not loaded; current findings are unclassified, not new regressions.",
        }

    current_by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    baseline_by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for finding in current:
        current_by_key.setdefault(_finding_identity(finding, identity_mode), []).append(finding)
    for finding in baseline:
        baseline_by_key.setdefault(_finding_identity(finding, identity_mode), []).append(finding)

    new_findings: list[dict[str, Any]] = []
    resolved_findings: list[dict[str, Any]] = []
    unchanged_findings: list[dict[str, Any]] = []
    for key in set(current_by_key) | set(baseline_by_key):
        current_items = current_by_key.get(key, [])
        baseline_items = baseline_by_key.get(key, [])
        unchanged_count = min(len(current_items), len(baseline_items))
        unchanged_findings.extend(current_items[:unchanged_count])
        new_findings.extend(current_items[unchanged_count:])
        resolved_findings.extend(baseline_items[unchanged_count:])

    new_findings.sort(key=_finding_sort_key)
    resolved_findings.sort(key=_finding_sort_key)
    unchanged_findings.sort(key=_finding_sort_key)
    return {
        "status": "compared",
        "baseline_status": baseline_status,
        "baseline_count": len(baseline),
        "current_count": len(current),
        "new_count": len(new_findings),
        "resolved_count": len(resolved_findings),
        "unchanged_count": len(unchanged_findings),
        "new_high_count": sum(1 for finding in new_findings if finding.get("severity") == "high"),
        "new_findings": new_findings,
        "resolved_findings": resolved_findings,
        "unchanged_findings": unchanged_findings,
        "unclassified_count": 0,
        "unclassified_high_count": 0,
    }


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
