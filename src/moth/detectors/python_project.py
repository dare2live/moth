"""Truth-source-first detector for Python project manifests.

分两级真相源, **不发明身份**:
  1. ``pyproject.toml`` —— 完整清单: 项目名/版本/依赖/runtime 约束/console scripts 全部有据。
  2. ``requirements.txt`` / ``setup.py`` / ``setup.cfg`` —— 部分证据: 只能证明"这是个 Python
     项目"和它的依赖, **证明不了它叫什么**。此时 ``project`` 保持 None 并附 partial warning,
     而不是拿目录名冒充项目名 —— 那是发明证据, 违背本检测器的 truth-source-first 前提。

2026-08-14 扩这一级的实测依据: 5 个注册项目里 4 个是实打实的 Python 代码库
(lifehack 10808 / chunkymonkey 507 / gaozhong 325 / gaokao 87 个 .py), 却因为只认
pyproject.toml 而全部 NOT_DETECTED —— 那不是"证据不足", 是检测面没覆盖到本仓真实生态。
partial 用 warning 表达而非新状态, 与 web/data_ai 检测器的既有惯用法一致。
"""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from typing import Any


def _empty(state: str, *, issue: str | None = None, warning: str | None = None) -> dict[str, Any]:
    return {
        "detector": {"id": "python-project", "state": state},
        "project": None, "applications": [], "runtimes": [], "modules": [],
        "evidence": [], "issues": [issue] if issue else [], "warnings": [warning] if warning else [],
    }


# 次级真相源: 能证明"是 Python 项目", 证明不了"叫什么"。
# requirements 用 glob 而非固定名: `requirements-ci.txt` / `requirements-dev.txt` 是
# 本仓生态里的实际写法(chunkymonkey 根目录就只有 requirements-ci.txt), 只认裸名会漏掉。
_FALLBACK_EXACT = ("setup.py", "setup.cfg")
_REQUIREMENTS_GLOB = "requirements*.txt"


def _fallback_manifests(root: Path) -> list[str]:
    found = [p.name for p in sorted(root.glob(_REQUIREMENTS_GLOB)) if p.is_file()]
    found += [name for name in _FALLBACK_EXACT if (root / name).is_file()]
    return found


def _requirement_lines(raw: str) -> list[str]:
    """从 requirements.txt 取依赖行。跳过注释/空行/pip 选项/递归引用/可编辑安装。

    刻意不解析版本约束语义 —— 这里只是"有哪些依赖"的证据, 不冒充解析器。
    """
    out: list[str] = []
    for line in raw.splitlines():
        item = line.split("#", 1)[0].strip()
        if not item or item.startswith("-"):
            continue
        out.append(item)
    return sorted(set(out))


def _detect_from_fallback(root: Path) -> dict[str, Any]:
    present = _fallback_manifests(root)
    if not present:
        return _empty("NOT_DETECTED")

    evidence: list[dict[str, Any]] = []
    dependencies: list[str] = []
    for name in present:
        path = root / name
        try:
            raw = path.read_bytes()
        except OSError:
            # 读不到就不当它存在 —— 不把"扫描失败"记成"有这份证据"。
            continue
        evidence.append({
            "id": f"manifest:{name}", "kind": "manifest", "locator": name,
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        })
        if name.startswith("requirements") and name.endswith(".txt"):
            try:
                dependencies = sorted(set(dependencies) | set(_requirement_lines(raw.decode("utf-8"))))
            except UnicodeError:
                return _empty(
                    "INVALID",
                    issue=f"python project manifest invalid: {name} is not valid UTF-8",
                )
    if not evidence:
        return _empty("NOT_DETECTED")

    evidence_ids = [item["id"] for item in evidence]
    warnings = [
        "python project coverage partial: no pyproject.toml; project identity "
        f"is unavailable from {'/'.join(present)} (name and version not claimed)",
        "python runtime coverage partial: requires-python is unavailable without pyproject.toml",
    ]
    return {
        "detector": {"id": "python-project", "state": "DETECTED"},
        # 身份留空: 次级清单证明不了项目名, 拿目录名填等于发明证据。
        "project": None,
        "applications": [],
        "runtimes": [{
            "id": "python", "kind": "runtime", "constraint": None,
            "dependencies": dependencies, "evidence_ids": evidence_ids,
        }],
        "modules": [], "evidence": evidence, "issues": [], "warnings": warnings,
    }


def detect_python_project(repo_path: str | Path) -> dict[str, Any]:
    root = Path(repo_path)
    manifest = root / "pyproject.toml"
    if not manifest.is_file():
        return _detect_from_fallback(root)
    try:
        raw = manifest.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return _empty("INVALID", issue="python project manifest invalid: pyproject.toml is malformed")
    project = data.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str) or not project["name"].strip():
        return _empty("INVALID", issue="python project manifest invalid: pyproject.toml requires project.name")
    name = project["name"].strip()
    for key in ("version", "description"):
        if key in project and not isinstance(project[key], str):
            return _empty("INVALID", issue=f"python project manifest invalid: project.{key} must be a string")
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list):
        return _empty("INVALID", issue="python project manifest invalid: project.dependencies must be a list")
    if not all(isinstance(item, str) for item in dependencies):
        return _empty("INVALID", issue="python project manifest invalid: project.dependencies values must be strings")
    constraint = project.get("requires-python")
    if constraint is not None and not isinstance(constraint, str):
        return _empty("INVALID", issue="python project manifest invalid: project.requires-python must be a string")
    scripts = project.get("scripts", {})
    if not isinstance(scripts, dict):
        return _empty("INVALID", issue="python project manifest invalid: project.scripts must be a mapping")
    if not all(isinstance(value, str) for value in scripts.values()):
        return _empty("INVALID", issue="python project manifest invalid: project.scripts values must be strings")
    evidence_id = "manifest:pyproject.toml"
    evidence = [{"id": evidence_id, "kind": "manifest", "locator": "pyproject.toml", "sha256": "sha256:" + hashlib.sha256(raw).hexdigest()}]
    applications = [
        {
            "id": f"python-console:{script}", "name": script, "kind": "application",
            "subtype": "python_console_script", "entrypoint": entrypoint,
            "runtime_id": "python", "evidence_ids": [evidence_id],
        }
        for script, entrypoint in sorted(scripts.items())
    ]
    warnings = [] if constraint is not None else ["python runtime coverage partial: project.requires-python is missing"]
    return {
        "detector": {"id": "python-project", "state": "DETECTED"},
        "project": {
            "id": f"python:{name}", "name": name, "version": project.get("version"),
            "description": project.get("description"), "evidence_ids": [evidence_id],
        },
        "applications": applications,
        "runtimes": [{
            "id": "python", "kind": "runtime", "constraint": constraint,
            "dependencies": sorted(dependencies), "evidence_ids": [evidence_id],
        }],
        "modules": [], "evidence": evidence, "issues": [], "warnings": warnings,
    }
