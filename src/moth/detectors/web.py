"""Evidence-driven Node/Web manifest detector."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from moth.detectors.common import (
    bounded_manifest_paths,
    detector_result,
    load_platform_rules,
    manifest_evidence,
    read_manifest,
)


def _mapping(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9_.-]+)")


def _path_slug(path: Path) -> str:
    raw = "-".join(path.parts) if path.parts else "root"
    return re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-_") or "root"


def _requirements(raw: bytes) -> tuple[list[str], set[str]]:
    declared: list[str] = []
    names: set[str] = set()
    for line in raw.decode("utf-8").splitlines():
        value = line.split("#", 1)[0].strip()
        if not value or value.startswith(("-", "http://", "https://")):
            continue
        match = _REQUIREMENT_NAME.match(value)
        if match is None:
            continue
        declared.append(value)
        names.add(match.group(1).lower().replace("_", "-"))
    return declared, names


def detect_web_project(repo_path: str | Path) -> dict[str, Any]:
    rules = load_platform_rules()
    limits = rules["limits"]
    config = rules["web"]
    paths, package_truncated = bounded_manifest_paths(
        repo_path,
        config["package_globs"],
        limits=limits,
    )
    python_manifests, python_truncated = bounded_manifest_paths(
        repo_path,
        config["python_dependency_globs"],
        limits=limits,
    )
    python_entries, entry_truncated = bounded_manifest_paths(
        repo_path,
        config["python_entry_globs"],
        limits=limits,
    )
    static_entries, static_truncated = bounded_manifest_paths(
        repo_path,
        config["static_entry_globs"],
        limits=limits,
    )
    truncated = any(
        (package_truncated, python_truncated, entry_truncated, static_truncated)
    )
    if not paths and not python_manifests and not static_entries:
        return detector_result(
            config["detector_id"],
            "NOT_DETECTED",
            warnings=(
                ["web project coverage partial: bounded filesystem scan was incomplete"]
                if truncated
                else []
            ),
        )

    applications: list[dict[str, Any]] = []
    modules: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, str]] = []
    issues: list[str] = []
    warnings: list[str] = []
    dependencies: set[str] = set()
    constraints: set[str] = set()
    runtime_evidence: list[str] = []
    application_roots: set[Path] = set()
    for relative in paths:
        raw, failure = read_manifest(
            repo_path,
            relative,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        if raw is None:
            issues.append(f"web manifest invalid: {relative.as_posix()} is {failure}")
            continue
        try:
            package = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            issues.append(f"web manifest invalid: {relative.as_posix()} is malformed")
            continue
        if not isinstance(package, dict):
            issues.append(f"web manifest invalid: {relative.as_posix()} must be an object")
            continue
        dependency_sections: list[dict[str, Any]] = []
        invalid_section = False
        for section_name in ("dependencies", "devDependencies"):
            section = package.get(section_name, {})
            section_mapping = _mapping(section)
            if section_mapping is None or not all(
                isinstance(name, str) and isinstance(version, str)
                for name, version in section_mapping.items()
            ):
                issues.append(
                    f"web manifest invalid: {relative.as_posix()} {section_name} must map strings to strings"
                )
                invalid_section = True
                break
            dependency_sections.append(section_mapping)
        if invalid_section:
            continue
        item = manifest_evidence(relative, raw)
        evidence.append(item)
        runtime_evidence.append(item["id"])
        package_dependencies = {
            name: version
            for section in dependency_sections
            for name, version in section.items()
        }
        dependencies.update(
            f"{name}@{version}" for name, version in package_dependencies.items()
        )
        engines = _mapping(package.get("engines", {}))
        if engines is None:
            issues.append(
                f"web manifest invalid: {relative.as_posix()} engines must be an object"
            )
            continue
        node_constraint = engines.get("node")
        if node_constraint is not None and not isinstance(node_constraint, str):
            issues.append(
                f"web manifest invalid: {relative.as_posix()} engines.node must be a string"
            )
            continue
        if node_constraint:
            constraints.add(node_constraint)

        matched = [
            framework
            for dependency, framework in config["framework_dependencies"].items()
            if dependency in package_dependencies
        ]
        if not matched:
            continue
        capabilities = {framework["capability"] for framework in matched}
        for capability in sorted(capabilities):
            capability_config = config["capabilities"][capability]
            module_id = f"platform:{capability}"
            module = modules.setdefault(
                module_id,
                {
                    "id": module_id,
                    "kind": "platform",
                    "name": capability_config["name"],
                    "subtype": capability_config["subtype"],
                    "evidence_ids": [],
                },
            )
            module["evidence_ids"].append(item["id"])
        for framework in matched:
            module_id = f"framework:{framework['id']}"
            module = modules.setdefault(
                module_id,
                {
                    "id": module_id,
                    "kind": "framework",
                    "name": framework["name"],
                    "subtype": "web",
                    "evidence_ids": [],
                },
            )
            module["evidence_ids"].append(item["id"])
        name = package.get("name")
        if not isinstance(name, str) or not name.strip():
            warnings.append(
                f"web application coverage partial: {relative.as_posix()} has no package name"
            )
            continue
        applications.append(
            {
                "id": f"web:{name.strip()}",
                "name": name.strip(),
                "kind": "application",
                "subtype": "web_application",
                "entrypoint": relative.as_posix(),
                "runtime_id": "nodejs",
                "evidence_ids": [item["id"]],
            }
        )
        application_roots.add(relative.parent)

    python_dependencies: set[str] = set()
    python_runtime_evidence: list[str] = []
    # **深的清单优先**: 一个 monorepo 的仓根清单, 其 entrypoint 候选是全仓所有 main.py,
    # min() 会挑中某个子服务的入口。若仓根先建应用, 那个子服务再来时就会撞上 entrypoint
    # 去重被丢掉 —— 结果是真实存在的 svc_a 从清单里消失, 换成一个以仓名命名、入口却指向
    # svc_a 的应用(2026-08-15 独立审查实测复现, 且当时零告警)。
    # 按深度降序遍历让最贴近入口的那份清单先认领它。
    for relative in sorted(
        python_manifests, key=lambda item: (-len(item.parts), item.as_posix())
    ):
        raw, failure = read_manifest(
            repo_path,
            relative,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        if raw is None:
            issues.append(
                f"python web manifest invalid: {relative.as_posix()} is {failure}"
            )
            continue
        try:
            declared, dependency_names = _requirements(raw)
        except UnicodeError:
            issues.append(
                f"python web manifest invalid: {relative.as_posix()} is malformed"
            )
            continue
        matched = [
            framework
            for dependency, framework in config[
                "python_framework_dependencies"
            ].items()
            if dependency in dependency_names
        ]
        if not matched:
            continue
        item = manifest_evidence(relative, raw)
        evidence.append(item)
        python_runtime_evidence.append(item["id"])
        python_dependencies.update(declared)
        capabilities = {framework["capability"] for framework in matched}
        for capability in sorted(capabilities):
            capability_config = config["capabilities"][capability]
            module_id = f"platform:{capability}"
            module = modules.setdefault(
                module_id,
                {
                    "id": module_id,
                    "kind": "platform",
                    "name": capability_config["name"],
                    "subtype": capability_config["subtype"],
                    "evidence_ids": [],
                },
            )
            module["evidence_ids"].append(item["id"])
        for framework in matched:
            module_id = f"framework:{framework['id']}"
            module = modules.setdefault(
                module_id,
                {
                    "id": module_id,
                    "kind": "framework",
                    "name": framework["name"],
                    "subtype": "web",
                    "evidence_ids": [],
                },
            )
            module["evidence_ids"].append(item["id"])
        root = relative.parent
        candidates = [
            path
            for path in python_entries
            if path.parts[: len(root.parts)] == root.parts
        ]
        if not candidates:
            warnings.append(
                f"python web application coverage partial: {relative.as_posix()} has no entrypoint"
            )
            continue
        entrypoint = min(candidates, key=lambda path: (len(path.parts), path.as_posix()))
        entry_raw, entry_failure = read_manifest(
            repo_path,
            entrypoint,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        evidence_ids = [item["id"]]
        if entry_raw is not None:
            entry_item = manifest_evidence(entrypoint, entry_raw)
            if not any(known["id"] == entry_item["id"] for known in evidence):
                evidence.append(entry_item)
            evidence_ids.append(entry_item["id"])
        elif entry_failure:
            warnings.append(
                f"python web entrypoint coverage partial: {entrypoint.as_posix()} is {entry_failure}"
            )
        # 同一 entrypoint 只产一个应用: 仓根与子目录(如 . 与 backend)会各自扫到
        # 同一份 backend/main.py, 之前因此产出两个重复应用。entrypoint 就是应用的身份。
        # **丢弃必须发声** —— 静默 continue 会变成"少报一个应用还全绿", 正是本仓自己在
        # loader.py 写下的那条原则要禁的(2026-08-15 独立审查指出此处违反了自家规矩)。
        owner = next(
            (a for a in applications if a.get("entrypoint") == entrypoint.as_posix()), None
        )
        if owner is not None:
            warnings.append(
                f"python web application coverage partial: {relative.as_posix()} shares "
                f"entrypoint {entrypoint.as_posix()} with {owner['id']}; only one application "
                "is reported for it"
            )
            continue
        root_slug = _path_slug(root)
        # `Path(".").as_posix()` 返回 "." 而不是空串 —— 它是**真值**, 于是原来的
        # `or` 兜底永远不触发, 仓根应用在界面上显示成一个名为 "." 的条目
        # (2026-08-14 Web Console 实测发现)。显式判 "." 才能落到仓目录名。
        root_name = root.as_posix()
        applications.append(
            {
                "id": f"python-web:{root_slug}",
                "name": Path(repo_path).resolve().name if root_name in ("", ".") else root_name,
                "kind": "application",
                "subtype": (
                    "python_api" if "api" in capabilities else "python_web_application"
                ),
                "entrypoint": entrypoint.as_posix(),
                "runtime_id": "python",
                "evidence_ids": sorted(set(evidence_ids)),
            }
        )
        application_roots.add(root)

    browser_evidence: list[str] = []
    for relative in static_entries:
        root = relative.parent
        root_name = "." if root == Path(".") else root.name
        if root_name not in set(config["static_root_names"]):
            continue
        if relative.parent in application_roots:
            continue
        raw, failure = read_manifest(
            repo_path,
            relative,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        if raw is None:
            issues.append(f"static web entry invalid: {relative.as_posix()} is {failure}")
            continue
        item = manifest_evidence(relative, raw)
        evidence.append(item)
        browser_evidence.append(item["id"])
        module = modules.setdefault(
            "platform:web",
            {
                "id": "platform:web",
                "kind": "platform",
                "name": config["capabilities"]["web"]["name"],
                "subtype": config["capabilities"]["web"]["subtype"],
                "evidence_ids": [],
            },
        )
        module["evidence_ids"].append(item["id"])
        applications.append(
            {
                "id": f"static-web:{_path_slug(root)}",
                "name": root.as_posix() or "web",
                "kind": "application",
                "subtype": "static_web_application",
                "entrypoint": relative.as_posix(),
                "runtime_id": "browser",
                "evidence_ids": [item["id"]],
            }
        )

    if len(constraints) > 1:
        warnings.append("node runtime coverage partial: manifests declare conflicting constraints")
    if truncated:
        warnings.append("web project coverage partial: bounded filesystem scan was incomplete")
    state = (
        "INVALID"
        if issues and not evidence
        else "DETECTED"
        if evidence
        else "NOT_DETECTED"
    )
    return detector_result(
        config["detector_id"],
        state,
        applications=applications,
        runtimes=[
            *(
                [
                {
                    "id": "nodejs",
                    "kind": "runtime",
                    "constraint": next(iter(constraints)) if len(constraints) == 1 else None,
                    "dependencies": sorted(dependencies),
                    "evidence_ids": runtime_evidence,
                }
                ]
                if runtime_evidence
                else []
            ),
            *(
                [
                    {
                        "id": "python",
                        "kind": "runtime",
                        "constraint": None,
                        "dependencies": sorted(python_dependencies),
                        "evidence_ids": sorted(set(python_runtime_evidence)),
                    }
                ]
                if python_runtime_evidence
                else []
            ),
            *(
                [
                    {
                        "id": "browser",
                        "kind": "runtime",
                        "constraint": None,
                        "dependencies": [],
                        "evidence_ids": sorted(set(browser_evidence)),
                    }
                ]
                if browser_evidence
                else []
            ),
        ],
        modules=modules.values(),
        evidence=evidence,
        issues=issues,
        warnings=warnings,
    )
