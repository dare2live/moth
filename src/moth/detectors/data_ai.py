"""Evidence-driven detector for declared data and AI dependencies."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from moth.detectors.common import (
    bounded_manifest_paths,
    detector_result,
    load_platform_rules,
    manifest_evidence,
    read_manifest,
)


_DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*")


def _dependency_name(requirement: str) -> str | None:
    matched = _DISTRIBUTION_NAME.match(requirement.strip())
    if not matched:
        return None
    return matched.group(0).lower().replace("_", "-").replace(".", "-")


def detect_data_ai_project(repo_path: str | Path) -> dict[str, Any]:
    rules = load_platform_rules()
    limits = rules["limits"]
    config = rules["data_ai"]
    paths, truncated = bounded_manifest_paths(
        repo_path,
        config["python_manifest_globs"],
        limits=limits,
    )
    modules: dict[str, dict[str, Any]] = {}
    evidence_by_id: dict[str, dict[str, str]] = {}
    warnings: list[str] = []
    for relative in paths:
        raw, failure = read_manifest(
            repo_path,
            relative,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        if raw is None:
            warnings.append(
                f"data/AI coverage partial: {relative.as_posix()} is {failure}"
            )
            continue
        try:
            manifest = tomllib.loads(raw.decode("utf-8"))
        except (UnicodeError, tomllib.TOMLDecodeError):
            # The Python detector owns pyproject validity; this detector only
            # consumes manifests whose dependency declaration is trustworthy.
            continue
        project = manifest.get("project")
        if not isinstance(project, dict):
            continue
        requirements = project.get("dependencies", [])
        if not isinstance(requirements, list) or not all(
            isinstance(requirement, str) for requirement in requirements
        ):
            continue
        declared = {
            name
            for requirement in requirements
            if (name := _dependency_name(requirement)) is not None
        }
        matched = {
            name: technology
            for name, technology in config["dependency_capabilities"].items()
            if name in declared
        }
        if not matched:
            continue
        item = manifest_evidence(relative, raw)
        evidence_by_id[item["id"]] = item
        for capability in sorted(
            {technology["capability"] for technology in matched.values()}
        ):
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
            module["evidence_ids"] = sorted(
                set(module["evidence_ids"]) | {item["id"]}
            )
        for dependency, technology in sorted(matched.items()):
            module_id = f"technology:{dependency}"
            module = modules.setdefault(
                module_id,
                {
                    "id": module_id,
                    "kind": "technology",
                    "name": technology["name"],
                    "subtype": technology["capability"],
                    "evidence_ids": [],
                },
            )
            module["evidence_ids"] = sorted(
                set(module["evidence_ids"]) | {item["id"]}
            )
    notebook_paths, notebook_truncated = bounded_manifest_paths(
        repo_path,
        config["notebook_globs"],
        limits=limits,
    )
    for relative in notebook_paths:
        raw, failure = read_manifest(
            repo_path,
            relative,
            max_bytes=int(limits["max_manifest_bytes"]),
        )
        # 扫到的候选 notebook 解析不了 = **关于这次扫描**的事实, 不是关于项目架构的缺陷 ——
        # 与本文件上方 python manifest 分支同一原则(「only consumes manifests whose
        # dependency declaration is trustworthy」: 信不过的候选跳过, 不升级为 issue)。
        # 2026-08-14 实测: gaokao 的 23 条 issue **全部(100%)**来自 data/external/ 下五个
        # vendored 第三方数据集(GAOKAO-Bench / GAOKAO-Eval / ...), 于是整个项目模型被别人的
        # 畸形 notebook 判成 verdict=FAIL。同一个文件对同一类事件给两种严重级, 是不一致而非设计。
        # 「畸形 notebook 算不算项目缺陷」是**目标仓的业务规则**, 按 AGENTS.md 第一条不属于 Moth;
        # Moth 只如实报覆盖不全, 由目标仓自己决定要不要因此判红。
        if raw is None:
            warnings.append(
                f"notebook coverage partial: {relative.as_posix()} is {failure}"
            )
            continue
        try:
            notebook = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            warnings.append(
                f"notebook coverage partial: {relative.as_posix()} is malformed"
            )
            continue
        if (
            not isinstance(notebook, dict)
            or not isinstance(notebook.get("nbformat"), int)
            or not isinstance(notebook.get("cells"), list)
        ):
            warnings.append(
                f"notebook coverage partial: {relative.as_posix()} lacks notebook structure"
            )
            continue
        item = manifest_evidence(relative, raw)
        evidence_by_id[item["id"]] = item
        notebook_capability = config["notebook_capability"]
        capability_config = config["capabilities"][notebook_capability]
        platform = modules.setdefault(
            f"platform:{notebook_capability}",
            {
                "id": f"platform:{notebook_capability}",
                "kind": "platform",
                "name": capability_config["name"],
                "subtype": capability_config["subtype"],
                "evidence_ids": [],
            },
        )
        platform["evidence_ids"] = sorted(
            set(platform["evidence_ids"]) | {item["id"]}
        )
        modules[f"artifact:notebook:{relative.as_posix()}"] = {
            "id": f"artifact:notebook:{relative.as_posix()}",
            "kind": "artifact",
            "name": relative.name,
            "subtype": "notebook",
            "locator": relative.as_posix(),
            "evidence_ids": [item["id"]],
        }
    if truncated:
        warnings.append("data/AI coverage partial: bounded filesystem scan was incomplete")
    if notebook_truncated:
        warnings.append("notebook coverage partial: bounded filesystem scan was incomplete")
    # 本检测器**没有** INVALID 态, 这是刻意的:
    # 其它检测器的 INVALID 一律指"声明性清单自己坏了"(pyproject 语法错 / 缺 project.name),
    # 而 data/AI 消费的 pyproject 有效性已明确让给 python 检测器(见上方 tomllib 分支注释),
    # 扫到的 notebook 坏了则属覆盖问题、走 warning(2026-08-14 gaokao 实证: 23 条 issue 全部
    # 来自 vendored 第三方数据集, 却把整个项目判成 FAIL)。
    # 两条路都不归它, 于是 `issues` 从此没有任何 append 点、INVALID 永远不可达 ——
    # 与其留一个到不了的状态假装还能报失败, 不如显式退役(2026-08-16 独立审查第 8 条)。
    return detector_result(
        config["detector_id"],
        "DETECTED" if evidence_by_id else "NOT_DETECTED",
        modules=modules.values(),
        evidence=evidence_by_id.values(),
        warnings=warnings,
    )
