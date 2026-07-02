from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

# 防御层: agent worktree 副本/依赖目录不算复杂度回归 (lifehack 实战: .claude/worktrees/
# 里的 agent 副本被扫出 80 个假 new_high 拦 push)。run_analysis 不动 —— 外部
# analyze_complexity.py 自有 --exclude; 本层保证即使外部扫了, diff 也不误报。
DEFAULT_IGNORED_PATH_PARTS = (".claude/worktrees/", "node_modules/", ".venv", ".git/")


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


def _normalize_path(raw_path: Any, repo_root: str | Path | None = None) -> str:
    text = str(raw_path or "").strip().replace("\\", "/")
    if not text:
        return ""
    if repo_root:
        try:
            path = Path(text)
            if path.is_absolute():
                return path.resolve().relative_to(Path(repo_root).resolve()).as_posix()
        except (OSError, ValueError):
            pass
    while text.startswith("./"):
        text = text[2:]
    return text


def _normalize_finding(raw: dict[str, Any], *, repo_root: str | Path | None = None) -> dict[str, Any]:
    message = raw.get("message") if raw.get("message") is not None else raw.get("finding")
    return {
        "severity": str(raw.get("severity") or "").strip().lower(),
        "kind": str(raw.get("kind") or "").strip(),
        "path": _normalize_path(raw.get("path"), repo_root),
        "line": int(raw.get("line") or 0),
        "message": str(message or "").strip(),
        "suggestion": str(raw.get("suggestion") or "").strip(),
        "confidence": str(raw.get("confidence") or "").strip().lower(),
    }


def _summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counts = _counts(findings, "severity")
    kind_counts = _counts(findings, "kind")
    confidence_counts = _counts(findings, "confidence")
    return {
        "finding_count": len(findings),
        "severity_counts": severity_counts,
        "kind_counts": kind_counts,
        "confidence_counts": confidence_counts,
        "high_count": severity_counts.get("high", 0),
        "medium_count": severity_counts.get("medium", 0),
        "info_count": severity_counts.get("info", 0),
        "high_confidence_count": confidence_counts.get("high", 0),
        "medium_confidence_count": confidence_counts.get("medium", 0),
        "low_confidence_count": confidence_counts.get("low", 0),
    }


def _empty_summary() -> dict[str, Any]:
    return _summary([])


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


def _is_ignored_path(path: str, ignored_path_parts: Sequence[str]) -> bool:
    if not path:
        return False
    return any(part and part in path for part in ignored_path_parts)


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
    repo_root: str | Path | None = None,
    ignored_path_parts: Sequence[str] = DEFAULT_IGNORED_PATH_PARTS,
) -> dict[str, Any]:
    current_all = [_normalize_finding(item, repo_root=repo_root) for item in current_findings if isinstance(item, dict)]
    baseline_all = [_normalize_finding(item, repo_root=repo_root) for item in baseline_findings if isinstance(item, dict)]
    current = [item for item in current_all if not _is_ignored_path(item["path"], ignored_path_parts)]
    baseline = [item for item in baseline_all if not _is_ignored_path(item["path"], ignored_path_parts)]
    # no-silent: 被排除的 finding 数显式上报, 不静默消失。
    ignored_count = (len(current_all) - len(current)) + (len(baseline_all) - len(baseline))
    if baseline_status != "loaded":
        return {
            "status": "baseline_unavailable",
            "baseline_status": baseline_status,
            "baseline_count": len(baseline),
            "current_count": len(current),
            "ignored_count": ignored_count,
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
        "ignored_count": ignored_count,
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
            "summary": _empty_summary(),
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

    return {
        "command": normalized_command,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "verdict": verdict,
        "issues": issues,
        "findings": findings,
        "summary": _summary(findings),
    }


def _is_repo_root_arg(value: str, root: Path) -> bool:
    if value in {".", str(root)}:
        return True
    try:
        return Path(value).expanduser().resolve() == root
    except (OSError, RuntimeError):
        return False


def command_for_target(root: str | Path, command: Sequence[str], target: str | Path) -> list[str]:
    normalized_command = _force_json_format(command)
    repo_root = Path(root).resolve()
    target_text = str(Path(target))
    for index, part in enumerate(normalized_command):
        if _is_repo_root_arg(part, repo_root):
            normalized_command[index] = target_text
            return normalized_command
    insert_at = len(normalized_command)
    for option in ("--format", "-f"):
        if option in normalized_command:
            insert_at = min(insert_at, normalized_command.index(option))
    normalized_command.insert(insert_at, target_text)
    return normalized_command


def run_analysis_for_paths(root: str | Path, command: Sequence[str], paths: Sequence[str | Path]) -> dict[str, Any]:
    repo_root = Path(root).resolve()
    files: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    issues: list[str] = []
    for raw_path in paths:
        target = Path(raw_path)
        if not target.is_absolute():
            target = repo_root / target
        rel_path = _normalize_path(target, repo_root)
        if not target.exists():
            issue = f"complexity target missing: {rel_path}"
            issues.append(issue)
            files.append(
                {
                    "path": rel_path,
                    "command": [],
                    "returncode": 1,
                    "verdict": "FAIL",
                    "issues": [issue],
                    "findings": [],
                    "summary": _empty_summary(),
                }
            )
            continue

        result = run_analysis(repo_root, command_for_target(repo_root, command, target))
        normalized_findings = [
            _normalize_finding(finding, repo_root=repo_root)
            for finding in result.get("findings") or []
            if isinstance(finding, dict)
        ]
        all_findings.extend(normalized_findings)
        file_issues = list(result.get("issues") or [])
        if result.get("verdict") == "FAIL":
            issues.extend(f"{rel_path}: {issue}" for issue in file_issues or ["complexity analysis failed"])
        files.append(
            {
                "path": rel_path,
                "command": result.get("command") or [],
                "returncode": result.get("returncode", 0),
                "verdict": result.get("verdict", "UNKNOWN"),
                "issues": file_issues,
                "findings": normalized_findings,
                "summary": _summary(normalized_findings),
            }
        )

    return {
        "command_template": _force_json_format(command),
        "verdict": "FAIL" if issues else "PASS",
        "issues": issues,
        "files": files,
        "findings": all_findings,
        "summary": _summary(all_findings),
    }
