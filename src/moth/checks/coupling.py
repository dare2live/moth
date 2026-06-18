"""Coupling / orphan-reference checker (moth coupling).

删一个实体 (DB表/脚本/config/doc) 常在别处留悬空引用, 删前不审 = 来回崩 (跨项目通病)。两模式:
  impact(repo, name): 删 name 前看全 fan-in (代码/配置/文档/测试/CI/moth 哪里引用) = 爆炸半径。
  orphans(repo):      扫孤儿引用 (引用了不存在的实体) → FAIL 类。

孤儿类型 (静态, 不依赖 repo 运行时):
  T1 测试 spec_from_file_location / 路径字符串 import 不存在的脚本 (collection 崩根因)
  T4 moth claims.yaml command/database 引用的文件路径不存在
  T5 CI workflow (.github/workflows) 硬编码测试清单引用不存在的测试文件
通用于任何 repo (moth 跨仓审计图谱的一员)。
"""
from __future__ import annotations

import glob
import re
import subprocess
from pathlib import Path

import yaml

_EXCLUDE_PARTS = (".venv", "__pycache__", ".git", "node_modules", ".pytest_cache", ".codegraph", "dist", "build")
_SCAN_EXTS = (".py", ".yaml", ".yml", ".json", ".md", ".sh", ".toml", ".cfg")


def _tracked_files(repo: Path) -> list[Path]:
    """Git-visible files (tracked + untracked, non-ignored); fallback to glob."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        files = [repo / line for line in out.splitlines() if line]
        if files:
            return [f for f in files if f.exists() and not any(p in f.parts for p in _EXCLUDE_PARTS)]
    except Exception:
        pass
    out = []
    for ext in _SCAN_EXTS:
        out += [Path(p) for p in glob.glob(str(repo / "**" / f"*{ext}"), recursive=True)]
    return [f for f in out if f.exists() and not any(p in f.parts for p in _EXCLUDE_PARTS)]


def _impact_terms(name: str) -> list[str]:
    """Terms to search for fan-in.

    Plain identifiers keep the historical stem behavior. Explicit path/file
    inputs also search the path and basename, but avoid broad short stems such
    as ``main`` from ``backend/main.py``.
    """

    normalized = name.strip().replace("\\", "/")
    basename = normalized.split("/")[-1]
    stem = basename.rsplit(".", 1)[0]
    if "/" not in normalized and "." not in basename:
        return [stem]
    terms = [normalized, basename]
    if len(stem) >= 6:
        terms.append(stem)
    return list(dict.fromkeys(term for term in terms if term))


def _resolve_repo_path(repo: Path, value: object, *, base: Path | None = None) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return (base or repo) / path


def impact(repo: Path, name: str) -> dict:
    """删 name 前的 fan-in (按文件类别分组)。name = 表名 / 文件名 basename / 标识符。"""
    stem = name.split("/")[-1].rsplit(".", 1)[0]
    terms = _impact_terms(name)
    pat = re.compile("|".join(re.escape(term) for term in terms))
    cats: dict[str, list] = {"code": [], "config": [], "doc": [], "test": [], "ci": [], "moth": [], "shell": []}
    for f in _tracked_files(repo):
        if f.suffix not in _SCAN_EXTS:
            continue
        rel = f.relative_to(repo).as_posix()
        if rel == name.replace("\\", "/"):
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        hits = [i + 1 for i, ln in enumerate(lines) if pat.search(ln)]
        if not hits:
            continue
        if "/tests/" in f"/{rel}" or rel.startswith("tests/") or "test_" in f.name:
            cats["test"].append((rel, hits))
        elif ".github/workflows" in rel:
            cats["ci"].append((rel, hits))
        elif "/.moth/" in f"/{rel}" or rel.startswith(".moth/"):
            cats["moth"].append((rel, hits))
        elif f.suffix == ".py":
            cats["code"].append((rel, hits))
        elif f.suffix in (".yaml", ".yml", ".json", ".toml", ".cfg"):
            cats["config"].append((rel, hits))
        elif f.suffix == ".md":
            cats["doc"].append((rel, hits))
        elif f.suffix == ".sh":
            cats["shell"].append((rel, hits))
    total = sum(len(v) for v in cats.values())
    return {
        "name": name,
        "stem": stem,
        "query_terms": terms,
        "total_files": total,
        "categories": {k: v for k, v in cats.items() if v},
    }


def orphans(repo: Path) -> dict:
    """扫孤儿引用 (引用不存在实体)。返回 {verdict, fails, warns}。"""
    fails: list[str] = []
    warns: list[str] = []

    def _exists_rel(rel: str) -> bool:
        return (repo / rel).exists()

    # T1: 测试 spec_from_file_location / 路径字符串引用不存在脚本 (module 级 = collection 崩根因)
    test_files = [f for f in _tracked_files(repo) if f.suffix == ".py" and ("test" in f.name or "/tests/" in f"/{f.relative_to(repo).as_posix()}")]
    for f in test_files:
        txt = f.read_text(encoding="utf-8", errors="ignore")
        rel = f.relative_to(repo).as_posix()
        for m in set(re.findall(r'spec_from_file_location\([^,]+,\s*[^"\']*["\']([^"\']+\.py)["\']', txt)):
            cand = repo / m
            base_hit = list(repo.glob(f"**/{Path(m).name}"))
            if not cand.exists() and not base_hit:
                fails.append(f"T1 {rel} spec 引用不存在脚本 {m}")

    # T4: moth claims.yaml 引用的文件路径不存在
    for claims in glob.glob(str(repo / ".moth/assertions/*.yaml")):
        ct = Path(claims).read_text(encoding="utf-8", errors="ignore")
        crel = Path(claims).relative_to(repo).as_posix()
        for ref in sorted(set(re.findall(r'((?:backend|src|scripts|analysis)/[\w/.-]+\.(?:py|sh|json|md|yaml))', ct))):
            if not _exists_rel(ref):
                fails.append(f"T4 {crel} 引用不存在文件 {ref}")

    # T4b: repo-local moth profile paths must point at real files/directories.
    profile_path = repo / ".moth/profile.yaml"
    if profile_path.exists():
        try:
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            fails.append(f"T4b .moth/profile.yaml 无法解析: {exc}")
            profile = {}
        if isinstance(profile, dict):
            base = _resolve_repo_path(repo, profile.get("repo_path", repo))
            path_fields = {
                "repo_path": profile.get("repo_path"),
                "codegraph_root": profile.get("codegraph_root"),
                "complexity_baseline_path": profile.get("complexity_baseline_path"),
            }
            for field, value in path_fields.items():
                if value in (None, ""):
                    continue
                path = _resolve_repo_path(repo, value, base=base)
                if not path.exists():
                    fails.append(f"T4b .moth/profile.yaml {field} 不存在: {value}")
            evidence_paths = profile.get("evidence_paths") or {}
            if isinstance(evidence_paths, dict):
                for label, value in sorted(evidence_paths.items()):
                    path = _resolve_repo_path(repo, value, base=base)
                    if not path.exists():
                        fails.append(f"T4b .moth/profile.yaml evidence_paths.{label} 不存在: {value}")
            for ref in profile.get("assertion_packs") or []:
                path = _resolve_repo_path(repo, ref, base=base)
                if not path.exists():
                    fails.append(f"T4b .moth/profile.yaml assertion_packs 引用不存在: {ref}")

    # T5: CI workflow 硬编码测试清单引用不存在的测试文件
    for wf in glob.glob(str(repo / ".github/workflows/*.yml")) + glob.glob(str(repo / ".github/workflows/*.yaml")):
        wt = Path(wf).read_text(encoding="utf-8", errors="ignore")
        wrel = Path(wf).relative_to(repo).as_posix()
        for ref in sorted(set(re.findall(r'((?:tests|backend/tests)/[\w/]+\.py)', wt))):
            if not _exists_rel(ref) and not (repo / "backend" / ref).exists():
                fails.append(f"T5 {wrel} 引用不存在测试 {ref}")

    return {"verdict": "FAIL" if fails else "PASS", "fails": fails, "warns": warns}


def render_impact(result: dict) -> str:
    out = [f"# coupling impact: '{result['name']}' — fan-in {result['total_files']} files\n"]
    labels = {"code": "代码(.py)", "config": "配置(yaml)", "doc": "文档(md)", "test": "测试", "ci": "CI", "moth": "moth", "shell": "shell(.sh)"}
    for cat, items in result["categories"].items():
        out.append(f"\n## {labels.get(cat, cat)} ({len(items)})")
        for rel, hits in sorted(items):
            out.append(f"- {rel}: line {hits[:8]}{'...' if len(hits) > 8 else ''}")
    if not result["total_files"]:
        out.append("\n无引用, 删除安全。")
    else:
        out.append(f"\n删前须逐个处理这 {result['total_files']} 个引用 (改引用/删消费者/迁移)。")
    return "\n".join(out) + "\n"


def render_orphans(result: dict) -> str:
    lines = [f"[FAIL] {f}" for f in result["fails"]] + [f"[WARN] {w}" for w in result["warns"]]
    lines.append(f"coupling verdict={result['verdict']} fails={len(result['fails'])} warns={len(result['warns'])}")
    lines.append("提示: 删表/脚本/config 前先 `moth coupling --repo <r> --impact <name>` 看 fan-in, 改完所有引用再删。")
    return "\n".join(lines) + "\n"
