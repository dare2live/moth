from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = ROOT / "profiles"
_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")


@dataclass(slots=True)
class RepoProfile:
    kind: str
    name: str
    repo_path: Path
    codegraph_root: Path
    # 可选: 缺省/空 = 内建模式 (进程内跑 moth.analyzers.complexity, 无外部脚本依赖)。
    complexity_command: list[str] = field(default_factory=list)
    complexity_baseline_path: Path | None = None
    # 仅内建模式消费的目录名排除 (拼进内建调用); 显式 complexity_command 模式忽略,
    # doctor 会以 warning 提示。
    complexity_excludes: list[str] = field(default_factory=list)
    # None = 用 adapters.complexity.DEFAULT_IGNORED_PATH_PARTS; [] = 不过滤 (显式关闭)。
    complexity_ignored_path_parts: list[str] | None = None
    evidence_paths: dict[str, Path] = field(default_factory=dict)
    instruction_sources: dict[str, Any] = field(default_factory=dict)
    assertion_packs: list[Path] = field(default_factory=list)
    # 可选 import-cycle 检查配置: {scan_paths: [], package_prefix: str, allowlist_path: str|None}
    import_cycles: dict[str, Any] | None = None
    tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: str = ""


def build_default_profile(repo_path: str | Path) -> RepoProfile:
    repo = Path(repo_path).resolve()
    return RepoProfile(
        kind="ephemeral_profile",
        name=repo.name,
        repo_path=repo,
        codegraph_root=repo,
        instruction_sources={"sources": []},
        notes="Ephemeral profile generated for one Moth inspection.",
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping")
    return raw


def _resolve(base: Path, value: Any) -> Path:
    path = Path(str(value))
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _is_repo_local_profile(path: Path) -> bool:
    return path.name == "profile.yaml" and path.parent.name == ".moth"


def _is_moth_owned_profile(path: Path) -> bool:
    """Only bundled profiles may intentionally reference cross-repo evidence."""

    return path.resolve().parent == PROFILES_DIR.resolve()


def _resolve_profile_path(
    base: Path,
    value: Any,
    *,
    field_name: str,
    require_repo_local: bool,
) -> Path:
    resolved = _resolve(base, value)
    if require_repo_local:
        try:
            resolved.relative_to(base.resolve())
        except ValueError as exc:
            raise ValueError(
                f"{field_name} escapes the profile repository"
            ) from exc
    return resolved


def _load_evidence_paths(
    data: dict[str, Any],
    base: Path,
    *,
    require_repo_local: bool,
) -> dict[str, Path]:
    raw = data.get("evidence_paths")
    if isinstance(raw, dict):
        return {
            str(label): _resolve_profile_path(
                base,
                value,
                field_name=f"evidence_paths.{label}",
                require_repo_local=require_repo_local,
            )
            for label, value in raw.items()
        }

    legacy_keys = {
        "goal": data.get("goal_path"),
        "handoff": data.get("handoff_path"),
        "workflow_checkpoint": data.get("workflow_checkpoint_path"),
        "quickstart": data.get("quickstart_path"),
        "docs": data.get("docs_root"),
    }
    return {
        label: _resolve_profile_path(
            base,
            value,
            field_name=f"evidence_paths.{label}",
            require_repo_local=require_repo_local,
        )
        for label, value in legacy_keys.items()
        if value is not None
    }


def _load_instruction_sources(data: dict[str, Any]) -> dict[str, Any]:
    """Preserve policy-source metadata as authored in the profile."""

    raw = data.get("instruction_sources")
    if not isinstance(raw, dict):
        return {}
    return {str(label): value for label, value in raw.items()}


def _expand_command_part(value: Any) -> str:
    return os.path.expandvars(os.path.expanduser(str(value)))


def _load_ignored_path_parts(data: dict[str, Any]) -> list[str] | None:
    raw = data.get("complexity_ignored_path_parts")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("complexity_ignored_path_parts must be a list of path fragments")
    return [str(item) for item in raw]


def _load_complexity_excludes(data: dict[str, Any]) -> list[str]:
    raw = data.get("complexity_excludes")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("complexity_excludes must be a list of directory names")
    return [str(item) for item in raw]


def _load_import_cycles(
    data: dict[str, Any],
    base: Path,
    *,
    require_repo_local: bool,
) -> dict[str, Any] | None:
    raw = data.get("import_cycles")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("import_cycles must be a mapping (scan_paths/package_prefix/allowlist_path)")
    options = {str(key): value for key, value in raw.items()}
    raw_scan_paths = options.get("scan_paths") or []
    if not isinstance(raw_scan_paths, list):
        raise ValueError("import_cycles.scan_paths must be a list")

    def portable_path(value: Any, field_name: str) -> str:
        resolved = _resolve_profile_path(
            base,
            value,
            field_name=field_name,
            require_repo_local=require_repo_local,
        )
        if require_repo_local:
            return resolved.relative_to(base.resolve()).as_posix()
        return str(resolved)

    options["scan_paths"] = [
        portable_path(value, f"import_cycles.scan_paths[{index}]")
        for index, value in enumerate(raw_scan_paths)
    ]
    if options.get("allowlist_path"):
        options["allowlist_path"] = portable_path(
            options["allowlist_path"],
            "import_cycles.allowlist_path",
        )
    return options


def _load_tools(
    data: dict[str, Any],
    base: Path,
    *,
    require_repo_local: bool,
) -> dict[str, dict[str, Any]]:
    raw = data.get("tools")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("tools must be a mapping keyed by tool id")
    tools: dict[str, dict[str, Any]] = {}
    for raw_id, raw_options in raw.items():
        tool_id = str(raw_id)
        if not _TOOL_ID_RE.fullmatch(tool_id):
            raise ValueError(f"invalid tool id: {tool_id}")
        if not isinstance(raw_options, dict):
            raise ValueError(f"tool {tool_id} config must be a mapping")
        options = {str(key): value for key, value in raw_options.items()}
        if {"binary", "executable"} & set(options):
            raise ValueError(
                f"tool {tool_id} executable belongs in the trusted user installation registry"
            )
        if isinstance(options.get("config_path"), str):
            options["config_path"] = _resolve_profile_path(
                base,
                options["config_path"],
                field_name=f"tools.{tool_id}.config_path",
                require_repo_local=require_repo_local,
            )
        tools[tool_id] = options
    return tools


def load_profile(ref: str | Path) -> RepoProfile:
    path = Path(ref)
    if not path.is_absolute():
        if path.suffix:
            # 相对的文件路径 (e.g. `.moth/profile.yaml`) 相对**调用者 cwd** 解析,
            # 不是 moth 仓 ROOT (修: 否则 `moth profile .moth/profile.yaml` 在别的项目下
            # 会读成 moth 仓的同名文件, 须用绝对路径才正常 — lifehack 2026-06-14 反例)。
            path = (Path.cwd() / path).resolve()
        else:
            path = (PROFILES_DIR / f"{path.name}.yaml").resolve()
    data = _load_yaml(path)
    raw_repo = str(data["repo_path"]).strip()
    declared_repo = Path(raw_repo)
    if not declared_repo.is_absolute():
        declared_repo = (path.parent / declared_repo).resolve()
    else:
        declared_repo = declared_repo.resolve()
    if _is_repo_local_profile(path):
        expected_repo = path.parent.parent.resolve()
        # Legacy repo-local profiles used "." under a process-cwd interpretation.
        # It is accepted as an ownership marker but never used as a path.
        if declared_repo != expected_repo and raw_repo != ".":
            raise ValueError("repo-local profile repo_path must resolve to its owning repository")
        base = expected_repo
    else:
        base = declared_repo
    require_repo_local = not _is_moth_owned_profile(path)
    complexity_command = [
        _expand_command_part(part) for part in data.get("complexity_command") or []
    ]
    if require_repo_local and complexity_command:
        raise ValueError("non-bundled profiles cannot select external complexity executables")
    baseline_path = data.get("complexity_baseline_path")
    return RepoProfile(
        kind=str(data.get("kind", "profile")),
        name=str(data["name"]),
        repo_path=base,
        codegraph_root=_resolve_profile_path(
            base,
            data["codegraph_root"],
            field_name="codegraph_root",
            require_repo_local=require_repo_local,
        ),
        complexity_command=complexity_command,
        complexity_baseline_path=(
            _resolve_profile_path(
                base,
                baseline_path,
                field_name="complexity_baseline_path",
                require_repo_local=require_repo_local,
            )
            if baseline_path
            else None
        ),
        complexity_excludes=_load_complexity_excludes(data),
        complexity_ignored_path_parts=_load_ignored_path_parts(data),
        evidence_paths=_load_evidence_paths(
            data,
            base,
            require_repo_local=require_repo_local,
        ),
        instruction_sources=_load_instruction_sources(data),
        assertion_packs=[
            _resolve_profile_path(
                base,
                item,
                field_name=f"assertion_packs[{index}]",
                require_repo_local=require_repo_local,
            )
            for index, item in enumerate(data.get("assertion_packs") or [])
        ],
        import_cycles=_load_import_cycles(
            data,
            base,
            require_repo_local=require_repo_local,
        ),
        tools=_load_tools(
            data,
            base,
            require_repo_local=require_repo_local,
        ),
        notes=str(data.get("notes", "")),
    )


def list_profiles() -> list[RepoProfile]:
    if not PROFILES_DIR.exists():
        return []
    profiles = [load_profile(path) for path in sorted(PROFILES_DIR.glob("*.yaml"))]
    return [profile for profile in profiles if profile.kind == "profile"]


def discover_profiles_with_failures(
    search_root: str | Path,
) -> tuple[list[RepoProfile], list[dict[str, str]]]:
    """扫工作区里的 repo-local profile, **一份坏的不得带走整批**。

    2026-08-14 实测: 原实现在列表推导里逐个 ``load_profile``, 任何一份不合法都会抛出,
    于是 ``moth workspace`` / ``moth profiles`` 在真实工作区**整条命令崩溃** ——
    8 份 profile 里 3 份声明了 ``complexity_command``(repo-local 禁用, 见下), 全局即挂。
    这与"扫到的候选解析不了"同属发现式扫描: 坏件应被**报告**, 不是让整批消失。

    跳过必须可见: 失败以结构化条目返回, 由 workspace/profiles 报告渲染出来 ——
    静默跳过就变成"少查几份还全绿", 比直接崩更危险。
    """
    root = Path(search_root).resolve()
    if not root.exists():
        return [], []
    profile_paths = sorted(
        {
            path.resolve()
            for path in root.rglob("profile.yaml")
            if path.parent.name == ".moth"
        }
    )
    profiles: list[RepoProfile] = []
    failures: list[dict[str, str]] = []
    for path in profile_paths:
        try:
            profile = load_profile(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures.append(
                {
                    "path": str(path),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if profile.kind == "profile":
            profiles.append(profile)
    return profiles, failures


def discover_profiles(search_root: str | Path) -> list[RepoProfile]:
    """只要能加载的 profile。失败清单见 :func:`discover_profiles_with_failures`。"""

    return discover_profiles_with_failures(search_root)[0]


def match_profile(repo_path: str | Path) -> RepoProfile | None:
    target = Path(repo_path).resolve()
    local_profile_path = target / ".moth" / "profile.yaml"
    if local_profile_path.exists():
        profile = load_profile(local_profile_path)
        if profile.repo_path.resolve() != target:
            raise ValueError("repo-local profile cannot redirect inspection to another repository")
        return profile
    for profile in list_profiles():
        if profile.repo_path.resolve() == target:
            return profile
    return None
