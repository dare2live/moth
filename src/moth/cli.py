from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import uuid
from pathlib import Path

import yaml

from moth import __version__
from moth.adapters.complexity import build_complexity_diff_report
from moth.adapters.complexity import load_complexity_baseline
from moth.adapters.complexity import run_analysis as run_complexity_analysis
from moth.guidance import resolve_guidance_sources, sanitize_instruction_sources
from moth.guidance_policy import TASK_KINDS
from moth.html_report import render_html_report
from moth.inspection import build_failed_inspection
from moth.inspection import build_inspection, render_inspection_markdown
from moth.profiles.loader import build_default_profile, load_profile, match_profile
from moth.profiles.scaffold import build_profile_scaffold
from moth.profiles.scaffold import default_profile_path
from moth.profiles.scaffold import parse_complexity_command
from moth.profiles.scaffold import parse_evidence_paths
from moth.profiles.scaffold import write_profile_scaffold
from moth.report import build_affected_report
from moth.report import build_profiles_report
from moth.report import build_sync_report
from moth.report import render_affected_markdown
from moth.report import render_profiles_markdown
from moth.snapshot import build_snapshot, render_json, render_markdown
from moth.schema import SNAPSHOT_SCHEMA_VERSION
from moth.schema import utc_now_iso
from moth.workspace import build_workspace_report
from moth.workspace import render_workspace_markdown
from moth.visual_model import build_visual_model
from moth.visual_model import validate_visual_document_schema, validate_visual_model
from moth.output_transport import OUTPUT_TARGET_HELP, persist_optional_output
from moth.web_server import serve_web_console
from moth.web_registry import default_web_config_path, register_web_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moth", description="Cross-repo audit atlas")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    inspect = sub.add_parser("inspect", help="One-call portable project and task preflight")
    inspect.add_argument("--repo", required=True)
    inspect.add_argument("--profile")
    inspect.add_argument(
        "--task-kind",
        choices=TASK_KINDS,
        default="substantive_judgment",
    )
    inspect.add_argument("--run-id")
    inspect.add_argument("--receipts")
    inspect.add_argument(
        "--application-reports",
        help="Structured Guidance application evidence bound to this run",
    )
    inspect.add_argument("--plan-only", action="store_true")
    inspect.add_argument(
        "--change-phase",
        choices=("pre", "during", "post"),
        help="Attach fail-closed change safety evidence to this inspection",
    )
    inspect.add_argument(
        "--file",
        "--changed-file",
        dest="changed_files",
        action="append",
        default=[],
        help="Explicit repository-relative changed file; may be repeated",
    )
    inspect.add_argument(
        "--gate",
        dest="change_gates",
        action="append",
        default=[],
        help="Repository-owned gate to execute; ignored by --plan-only",
    )
    inspect.add_argument("--change-depth", type=int, default=5)
    inspect.add_argument("--test-filter")
    inspect.add_argument("--baseline-digest")
    inspect.add_argument("--format", choices=("markdown", "json", "html"), default="json")
    inspect.add_argument("--output", help=OUTPUT_TARGET_HELP)

    serve_cmd = sub.add_parser(
        "serve",
        help="Run the local authenticated Web Console and project API",
    )
    serve_cmd.add_argument(
        "--config",
        default=str(default_web_config_path()),
        help="Web Console project registry (default: user Moth config)",
    )
    serve_cmd.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the authenticated local Web Console after the server binds",
    )

    snapshot = sub.add_parser("snapshot", help="Emit a machine-readable repo snapshot")
    snapshot.add_argument("--repo", required=True, help="Repo path to inspect")
    snapshot.add_argument("--profile", help="Explicit profile name or YAML path")
    snapshot.add_argument("--format", choices=("markdown", "json"), default="json")
    snapshot.add_argument("--output", help=OUTPUT_TARGET_HELP)

    doctor = sub.add_parser("doctor", help="Validate a repo profile and emit a summary")
    doctor.add_argument("--repo", required=True, help="Repo path to inspect")
    doctor.add_argument("--profile", help="Explicit profile name or YAML path")
    doctor.add_argument("--format", choices=("markdown", "json"), default="markdown")
    doctor.add_argument("--output", help=OUTPUT_TARGET_HELP)

    report = sub.add_parser("report", help="Render a report for a repo profile")
    report.add_argument("--repo", required=True, help="Repo path to inspect")
    report.add_argument("--profile", help="Explicit profile name or YAML path")
    report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    report.add_argument("--output", help=OUTPUT_TARGET_HELP)

    profile_cmd = sub.add_parser("profile", help="Show a profile")
    profile_cmd.add_argument("ref", help="Profile name or YAML path")
    profile_cmd.add_argument("--format", choices=("markdown", "json"), default="json")
    profile_cmd.add_argument("--output", help=OUTPUT_TARGET_HELP)

    profiles_cmd = sub.add_parser("profiles", help="List available profiles")
    profiles_cmd.add_argument("--workspace", help="Workspace root to discover repo-local profiles")
    profiles_cmd.add_argument("--format", choices=("markdown", "json"), default="json")
    profiles_cmd.add_argument("--output", help=OUTPUT_TARGET_HELP)

    assert_cmd = sub.add_parser("assert", help="Run only the profile's assertion packs (fast path)")
    assert_cmd.add_argument("--repo", required=True, help="Repo path to inspect")
    assert_cmd.add_argument("--profile", help="Explicit profile name or YAML path")
    assert_cmd.add_argument("--format", choices=("markdown", "json"), default="markdown")

    complexity_cmd = sub.add_parser(
        "complexity",
        help="内建复杂度热点扫描 (vendored complexity-optimizer analyzer, 进程内, schema-frozen)",
    )
    complexity_cmd.add_argument("root", nargs="?", default=".", help="Repository or directory to scan.")
    complexity_cmd.add_argument(
        "--repo",
        help="Repository root; applies its Moth profile when available.",
    )
    complexity_cmd.add_argument("--profile", help="Explicit profile name or YAML path")
    complexity_cmd.add_argument(
        "--no-profile",
        action="store_true",
        help="Ignore a matching Moth profile and use only command-line options.",
    )
    complexity_cmd.add_argument("--format", choices=["markdown", "json"], default="markdown")
    complexity_cmd.add_argument("--exclude", action="append", default=[], help="Additional directory name to exclude.")
    complexity_cmd.add_argument("--max-findings", type=int, default=80)
    complexity_cmd.add_argument(
        "--include-ignored",
        action="store_true",
        help="Include files ignored by Git.",
    )
    complexity_cmd.add_argument(
        "--write-baseline",
        metavar="PATH",
        help="Write all current findings as a validated baseline JSON file.",
    )

    coupling_cmd = sub.add_parser("coupling", help="Coupling/orphan-ref check: --impact <name> 看删前 fan-in, 或扫孤儿引用")
    coupling_cmd.add_argument("--repo", required=True, help="Repo path to inspect")
    coupling_cmd.add_argument("--impact", metavar="NAME", help="删 NAME (表名/文件名/标识符) 前看全 fan-in 爆炸半径")
    coupling_cmd.add_argument("--format", choices=("markdown", "json"), default="markdown")

    cycles_cmd = sub.add_parser("cycles", help="Import-cycle check: 跑 profile 的 import_cycles 配置 (AST 图 + Tarjan SCC)")
    cycles_cmd.add_argument("--repo", required=True, help="Repo path to inspect")
    cycles_cmd.add_argument("--profile", help="Explicit profile name or YAML path")
    cycles_cmd.add_argument("--format", choices=("markdown", "json"), default="markdown")

    workspace_cmd = sub.add_parser("workspace", help="Inspect all repo-local profiles in a workspace")
    workspace_cmd.add_argument("--workspace", required=True, help="Workspace root to inspect")
    workspace_cmd.add_argument("--format", choices=("markdown", "json"), default="json")
    workspace_cmd.add_argument("--output", help=OUTPUT_TARGET_HELP)

    init_cmd = sub.add_parser("init", help="Create a repo-local moth profile scaffold")
    init_cmd.add_argument("--repo", required=True, help="Repo path to scaffold")
    init_cmd.add_argument("--name", help="Profile name to write")
    init_cmd.add_argument("--output", help="Output profile path (defaults to <repo>/.moth/profile.yaml)")
    init_cmd.add_argument(
        "--complexity-command",
        help="Shell-style complexity command to store in the scaffold",
    )
    init_cmd.add_argument(
        "--evidence-path",
        action="append",
        default=[],
        help="Evidence path in label=path form; may be repeated",
    )
    init_cmd.add_argument("--notes", default="Generated by moth init.", help="Profile notes")
    init_cmd.add_argument("--force", action="store_true", help="Overwrite an existing profile")
    web_registration = init_cmd.add_mutually_exclusive_group()
    web_registration.add_argument(
        "--register-web",
        dest="register_web",
        action="store_true",
        help="Register this repository for the Web Console (default)",
    )
    web_registration.add_argument(
        "--no-register-web",
        dest="register_web",
        action="store_false",
        help="Create project files without adding it to the Web Console",
    )
    init_cmd.set_defaults(register_web=True)
    init_cmd.add_argument(
        "--web-config",
        help="Web registry path (default: MOTH_WEB_CONFIG or the user config directory)",
    )
    init_cmd.add_argument("--format", choices=("markdown", "json"), default="json")

    sync_cmd = sub.add_parser("sync", help="Refresh CodeGraph and emit the latest snapshot")
    sync_cmd.add_argument("--repo", required=True, help="Repo path to inspect")
    sync_cmd.add_argument("--profile", help="Explicit profile name or YAML path")
    sync_cmd.add_argument("--format", choices=("markdown", "json"), default="json")
    sync_cmd.add_argument("--output", help=OUTPUT_TARGET_HELP)

    affected_cmd = sub.add_parser("affected", help="Map changed files to affected tests and scoped complexity findings")
    affected_cmd.add_argument("--repo", required=True, help="Repo path to inspect")
    affected_cmd.add_argument("--profile", help="Explicit profile name or YAML path")
    affected_cmd.add_argument("--file", action="append", default=[], help="Changed file path; may be repeated")
    affected_cmd.add_argument("files", nargs="*", help="Changed file paths")
    affected_cmd.add_argument("--depth", type=int, default=5, help="CodeGraph dependency traversal depth")
    affected_cmd.add_argument("--test-filter", help="CodeGraph affected test glob filter")
    affected_cmd.add_argument("--format", choices=("markdown", "json"), default="json")
    affected_cmd.add_argument("--output", help=OUTPUT_TARGET_HELP)

    takeover_cmd = sub.add_parser("takeover", help="接手对账: 跑 .sherpa/takeover.yaml (兼容) 或 .moth/takeover.yaml 清单出单页 verdict")
    takeover_cmd.add_argument("--repo", required=True, help="目标 repo 路径")
    takeover_cmd.add_argument("--format", choices=("markdown", "json"), default="markdown")

    gates_cmd = sub.add_parser("gates", help="实验 go/no-go: 跑 .sherpa/gates/<experiment>.yaml (兼容) 或 .moth/gates/<experiment>.yaml")
    gates_cmd.add_argument("--repo", required=True, help="目标 repo 路径")
    gates_cmd.add_argument("experiment", nargs="?", help="实验名; 缺省列出全部 gate 包")
    gates_cmd.add_argument("--format", choices=("markdown", "json"), default="markdown")

    return parser


def _resolve_profile(repo: str, profile_ref: str | None):
    if profile_ref:
        return load_profile(profile_ref)
    matched = match_profile(repo)
    if matched is None:
        raise SystemExit(f"no profile matched repo {repo!r}; pass --profile explicitly")
    return matched


def _resolve_inspection_profile(repo: str, profile_ref: str | None):
    if profile_ref:
        return load_profile(profile_ref)
    return match_profile(repo) or build_default_profile(repo)


def _load_object_array(path: str | None, *, label: str) -> list[dict[str, object]]:
    if path is None:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{label} must be a JSON array of objects")
    return payload


def _load_receipts(path: str | None) -> list[dict[str, object]]:
    return _load_object_array(path, label="receipts")


def _render_mapping_block(mapping: dict[str, object]) -> list[str]:
    return [f"  - {sub_key}: `{sub_value}`" for sub_key, sub_value in mapping.items()]


def _write_output(output_path: str | None, rendered: str) -> None:
    persist_optional_output(output_path, rendered)


def _write_complexity_baseline(
    path: str | Path,
    findings: list[dict[str, object]],
) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "moth.complexity-baseline.v1",
        "generated_at": utc_now_iso(),
        "identity_mode": "path_kind_message",
        "findings": findings,
    }
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "serve":
        try:
            return serve_web_console(
                args.config,
                open_browser=args.open_browser,
            )
        except (OSError, UnicodeError, ValueError) as exc:
            sys.stderr.write(f"moth serve: {exc}\n")
            return 1

    if args.cmd == "inspect":
        visual_document = None
        try:
            receipts = _load_receipts(args.receipts)
            application_reports = _load_object_array(
                args.application_reports,
                label="application reports",
            )
            profile = _resolve_inspection_profile(args.repo, args.profile)
            inspection_kwargs = {
                "task_kind": args.task_kind,
                "run_id": args.run_id or f"run-{uuid.uuid4().hex}",
                "receipts": receipts,
                "application_reports": application_reports,
                "codex_home": Path(
                    os.environ.get("CODEX_HOME", Path.home() / ".codex")
                ),
            }
            if args.change_phase is not None:
                inspection_kwargs.update(
                    {
                        "change_phase": f"{args.change_phase}_change",
                        "changed_files": args.changed_files,
                        "gate_names": args.change_gates,
                        "change_depth": args.change_depth,
                        "test_filter": args.test_filter,
                        "baseline_digest": args.baseline_digest,
                        "execute_gates": not args.plan_only,
                    }
                )
            elif (
                args.changed_files
                or args.change_gates
                or args.baseline_digest is not None
            ):
                raise ValueError(
                    "change files, gates, and baseline require --change-phase"
                )
            payload = build_inspection(profile, **inspection_kwargs)
            if args.format == "html":
                visual_document = build_visual_model(payload)
                visual_errors = [
                    *validate_visual_document_schema(visual_document),
                    *validate_visual_model(visual_document),
                ]
                if visual_errors:
                    raise ValueError(
                        f"visual document validation failed: {visual_errors[0]}"
                    )
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            payload = build_failed_inspection(exc)
            if args.format == "html":
                visual_document = build_visual_model(payload)
        if args.format == "json":
            rendered = render_json(payload) + "\n"
        elif args.format == "html":
            rendered = render_html_report(visual_document or build_visual_model(payload))
        else:
            rendered = render_inspection_markdown(payload)
        _write_output(args.output, rendered)
        sys.stdout.write(rendered)
        if payload["status"] == "FAIL":
            return 1
        change_verdict = payload.get("change_safety_verdict")
        if change_verdict == "NO_GO":
            return 1
        if change_verdict == "CAUTION":
            return 2
        if payload["status"] == "NEEDS_EXECUTOR" and not args.plan_only:
            return 2
        return 0

    if args.cmd == "assert":
        from moth.checks.assertions import run_assertion_packs

        profile = _resolve_profile(args.repo, args.profile)
        outcome = run_assertion_packs(profile.assertion_packs, profile.repo_path)
        if args.format == "json":
            sys.stdout.write(render_json(outcome) + "\n")
        else:
            totals = outcome["totals"]
            sys.stdout.write(
                f"verdict={outcome['verdict']} pass={totals['pass']}"
                f" fail={totals['fail']} error={totals['error']}\n"
            )
            for pack in outcome["packs"]:
                for r in pack["results"]:
                    if r["status"] != "pass":
                        sys.stdout.write(
                            f"[{r['status'].upper()}] {r['id']}: observed={r['observed']!r}"
                            + (f" | {r['detail']}" if r["detail"] else "") + "\n"
                        )
            for issue in outcome["issues"]:
                sys.stdout.write(f"[ISSUE] {issue}\n")
        return 0 if outcome["verdict"] != "FAIL" else 1

    if args.cmd == "complexity":
        from moth.analyzers.complexity import render_markdown as render_complexity_markdown
        from moth.analyzers.complexity import run as run_complexity

        root = Path(args.repo or args.root).expanduser().resolve()
        if args.repo and args.root != "." and Path(args.root).expanduser().resolve() != root:
            sys.stderr.write("moth complexity: positional root and --repo disagree\n")
            return 2
        profile = None
        if not args.no_profile:
            profile = load_profile(args.profile) if args.profile else match_profile(root)
        if profile is not None and profile.repo_path.resolve() != root:
            sys.stderr.write("moth complexity: profile repository does not match scan root\n")
            return 2

        excludes = list(dict.fromkeys([*(profile.complexity_excludes if profile else []), *args.exclude]))
        scan_limit = 1_000_000 if args.write_baseline else args.max_findings
        if profile is not None and profile.complexity_command:
            analysis = run_complexity_analysis(root, profile.complexity_command)
            if analysis["verdict"] == "FAIL":
                for issue in analysis.get("issues") or ["complexity analysis failed"]:
                    sys.stderr.write(f"moth complexity: {issue}\n")
                return 1
            external_findings = list(analysis.get("findings") or [])
            result = {
                "findings": external_findings,
                "total": len(external_findings),
                "truncated": False,
            }
        else:
            result = run_complexity(
                root,
                excludes,
                max_findings=scan_limit,
                include_ignored=args.include_ignored,
            )
        all_findings = list(result["findings"])
        display_limit = max(0, args.max_findings)
        findings = all_findings[:display_limit]

        baseline_path = profile.complexity_baseline_path if profile else None
        baseline_findings, baseline_status = load_complexity_baseline(baseline_path)
        diff_kwargs = {}
        if profile is not None and profile.complexity_ignored_path_parts is not None:
            diff_kwargs["ignored_path_parts"] = profile.complexity_ignored_path_parts
        # 截断判定: 非 baseline 模式下 scan_limit == --max-findings(默认 80), 扫满即意味着
        # 后面还有没扫到的。不告诉 diff 这件事, 它会把"没扫到"当成"已解决"。
        current_truncated = bool(
            not args.write_baseline and scan_limit and len(all_findings) >= scan_limit
        )
        diff = build_complexity_diff_report(
            all_findings,
            baseline_findings,
            baseline_status=baseline_status,
            current_truncated=current_truncated,
            repo_root=root,
            **diff_kwargs,
        )
        governance_state = (
            "UNBASELINED"
            if diff["status"] != "compared"
            else "CAUTION"
            if int(diff.get("new_high_count") or 0)
            else "REVIEW"
            if int(diff.get("new_count") or 0)
            else "STABLE"
        )

        if profile is None:
            sys.stderr.write("profile not applied; using defaults\n")
        else:
            sys.stderr.write(
                f"profile applied: {profile.name}; excludes={excludes or []}; "
                f"analyzer={'external' if profile.complexity_command else 'builtin'}; "
                f"baseline={baseline_status}; governance={governance_state}\n"
            )
        if args.write_baseline:
            written = _write_complexity_baseline(args.write_baseline, all_findings)
            sys.stderr.write(f"baseline written: {written}\n")

        if args.format == "json":
            sys.stdout.write(json.dumps(findings, indent=2) + "\n")
        else:
            rendered = render_complexity_markdown(findings)
            if int(result["total"]) > len(findings):
                rendered += (
                    f"\nShowing {len(findings)} of {result['total']} findings. "
                    "Raise --max-findings to see the rest.\n"
                )
            sys.stdout.write(rendered)
        return 0

    if args.cmd == "coupling":
        from moth.checks.coupling import impact, orphans, render_impact, render_orphans

        repo = Path(args.repo).resolve()
        if args.impact:
            result = impact(repo, args.impact)
            sys.stdout.write(render_json(result) + "\n" if args.format == "json" else render_impact(result))
            return 0
        result = orphans(repo)
        sys.stdout.write(render_json(result) + "\n" if args.format == "json" else render_orphans(result))
        return 0 if result["verdict"] != "FAIL" else 1

    if args.cmd == "cycles":
        from moth.checks.import_cycles import audit_import_cycles_for_profile
        from moth.checks.import_cycles import render_markdown as render_cycles_markdown

        profile = _resolve_profile(args.repo, args.profile)
        if not profile.import_cycles:
            sys.stdout.write(
                "profile 未配置 import_cycles — 在 profile YAML 加:\n"
                "import_cycles:\n"
                "  scan_paths: [backend/services, backend/api]\n"
                "  package_prefix: backend\n"
                "  allowlist_path: config/architecture_known_cycles.json  # 可选\n"
            )
            return 2
        result = audit_import_cycles_for_profile(profile)
        rendered = render_json(result) + "\n" if args.format == "json" else render_cycles_markdown(result)
        sys.stdout.write(rendered)
        return 0 if result["verdict"] != "FAIL" else 1

    if args.cmd == "takeover":
        from moth.takeover import find_checklist, load_checklist, run_takeover
        from moth.takeover import render_markdown as render_takeover_markdown

        repo = Path(args.repo).resolve()
        checklist_path = find_checklist(repo)
        if checklist_path is None:
            sys.stdout.write(f"未找到 takeover 清单: {repo}/.sherpa/takeover.yaml 或 {repo}/.moth/takeover.yaml\n")
            sys.stdout.write("先初始化: moth init --repo <path> (顺带生成 .moth/takeover.yaml 模板, 按本仓实情编辑)\n")
            return 2
        checklist = load_checklist(checklist_path)
        outcome = run_takeover(checklist, repo)
        sys.stdout.write(
            render_json(outcome) + "\n" if args.format == "json" else render_takeover_markdown(outcome)
        )
        return 0 if outcome["overall"] != "FAIL" else 1

    if args.cmd == "gates":
        from moth.gates import list_gates, run_gate
        from moth.gates import render_markdown as render_gate_markdown

        repo = Path(args.repo).resolve()
        if not args.experiment:
            gates = list_gates(repo)
            sys.stdout.write("可用 gate 包:\n" if gates else "无 gate 包 (.sherpa/gates/*.yaml 或 .moth/gates/*.yaml)\n")
            for name in gates:
                sys.stdout.write(f"  - {name}\n")
            return 0
        try:
            outcome = run_gate(repo, args.experiment)
        except FileNotFoundError as exc:
            sys.stdout.write(f"{exc}\n")
            return 2
        sys.stdout.write(
            render_json(outcome) + "\n" if args.format == "json" else render_gate_markdown(outcome)
        )
        return 0 if outcome["go"] else 1

    if args.cmd in {"doctor", "report", "snapshot"}:
        profile = _resolve_profile(args.repo, args.profile)
        payload = build_snapshot(profile)
        rendered = render_json(payload) + "\n" if args.format == "json" else render_markdown(payload)
        _write_output(args.output, rendered)
        sys.stdout.write(rendered)
        return 0 if payload["status"] != "FAIL" else 1

    if args.cmd == "profile":
        profile = load_profile(args.ref)
        payload = {
            "kind": profile.kind,
            "name": profile.name,
            "repo_path": str(profile.repo_path),
            "codegraph_root": str(profile.codegraph_root),
            "complexity_command": profile.complexity_command,
            "complexity_baseline_path": str(profile.complexity_baseline_path) if profile.complexity_baseline_path else None,
            "complexity_excludes": profile.complexity_excludes,
            "evidence_paths": {label: str(path) for label, path in profile.evidence_paths.items()},
            "instruction_sources": sanitize_instruction_sources(profile.instruction_sources),
            "guidance": resolve_guidance_sources(profile.instruction_sources),
            "notes": profile.notes,
        }
        if args.format == "markdown":
            rendered = "# Moth profile\n\n"
            for key, value in payload.items():
                if isinstance(value, dict):
                    rendered += f"- {key}:\n"
                    rendered += "\n".join(_render_mapping_block(value)) + "\n"
                else:
                    rendered += f"- {key}: `{value}`\n"
        else:
            rendered = render_json(payload) + "\n"
        _write_output(args.output, rendered)
        if args.format == "markdown":
            sys.stdout.write(rendered)
        else:
            sys.stdout.write(rendered)
        return 0

    if args.cmd == "profiles":
        payload = build_profiles_report(args.workspace)
        rendered = render_json(payload) + "\n" if args.format == "json" else render_profiles_markdown(payload)
        _write_output(args.output, rendered)
        sys.stdout.write(rendered)
        return 0 if payload["status"] != "FAIL" else 1

    if args.cmd == "workspace":
        payload = build_workspace_report(args.workspace)
        rendered = render_json(payload) + "\n" if args.format == "json" else render_workspace_markdown(payload)
        _write_output(args.output, rendered)
        sys.stdout.write(rendered)
        return 0 if payload["status"] != "FAIL" else 1

    if args.cmd == "init":
        repo_path = args.repo
        output = args.output or str(default_profile_path(repo_path))
        payload = build_profile_scaffold(
            repo_path,
            name=args.name,
            complexity_command=parse_complexity_command(args.complexity_command),
            evidence_paths=parse_evidence_paths(args.evidence_path),
            notes=args.notes,
        )
        profile_created = True
        try:
            written = write_profile_scaffold(output, payload, force=args.force)
        except FileExistsError as exc:
            if args.register_web and Path(output).resolve().is_file():
                written = Path(output).resolve()
                profile_created = False
            else:
                result = {
                    "schema_version": SNAPSHOT_SCHEMA_VERSION,
                    "generated_at": utc_now_iso(),
                    "status": "FAIL",
                    "output_path": str(output),
                    "profile": payload,
                    "issues": [str(exc)],
                    "warnings": [],
                }
                if args.format == "json":
                    sys.stdout.write(render_json(result) + "\n")
                else:
                    sys.stdout.write("# Moth init\n\n")
                    sys.stdout.write("- Status: `FAIL`\n")
                    sys.stdout.write(f"- Output path: `{output}`\n")
                    sys.stdout.write("\n## Issues\n")
                    sys.stdout.write(f"- {exc}\n")
                return 1
        except Exception as exc:
            result = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "generated_at": utc_now_iso(),
                "status": "FAIL",
                "output_path": str(output),
                "profile": payload,
                "issues": [str(exc)],
                "warnings": [],
            }
            if args.format == "json":
                sys.stdout.write(render_json(result) + "\n")
            else:
                sys.stdout.write("# Moth init\n\n")
                sys.stdout.write(f"- Status: `FAIL`\n")
                sys.stdout.write(f"- Output path: `{output}`\n")
                sys.stdout.write("\n## Issues\n")
                sys.stdout.write(f"- {exc}\n")
            return 1
        from moth.takeover_scaffold import init_takeover

        # 顺带生成 takeover 清单模板 (幂等: 已存在不覆盖) — moth takeover 的起点。
        takeover_created = (
            init_takeover(repo_path, name=args.name) if profile_created else []
        )
        try:
            web_registration = (
                register_web_project(
                    repo_path,
                    name=args.name,
                    config_path=args.web_config or default_web_config_path(),
                )
                if args.register_web
                else None
            )
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
            result = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "generated_at": utc_now_iso(),
                "status": "FAIL",
                "output_path": str(written),
                "profile_created": profile_created,
                "profile": payload,
                "takeover_scaffold": takeover_created,
                "web_registration": None,
                "issues": [f"web registration failed: {exc}"],
                "warnings": [],
            }
            sys.stdout.write(render_json(result) + "\n")
            return 1
        result = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "generated_at": utc_now_iso(),
            "status": "PASS",
            "output_path": str(written),
            "profile_created": profile_created,
            "profile": payload,
            "takeover_scaffold": takeover_created,
            "web_registration": web_registration,
            "issues": [],
            "warnings": [],
        }
        if args.format == "json":
            sys.stdout.write(render_json(result) + "\n")
        else:
            sys.stdout.write("# Moth init\n\n")
            sys.stdout.write(f"- Status: `PASS`\n")
            sys.stdout.write(f"- Output path: `{written}`\n")
            sys.stdout.write(f"- Profile: `{payload['name']}`\n")
            if web_registration:
                sys.stdout.write(
                    f"- Web project: `{web_registration['project_id']}` in "
                    f"`{web_registration['config_path']}`\n"
                )
            if takeover_created:
                sys.stdout.write(f"- Takeover scaffold: `{takeover_created[0]}`\n")
            if payload.get("complexity_command"):
                sys.stdout.write(f"- Complexity command: `{shlex.join(payload['complexity_command'])}`\n")
            if payload.get("evidence_paths"):
                sys.stdout.write("\n## Evidence paths\n")
                for label, rel_path in payload["evidence_paths"].items():
                    sys.stdout.write(f"- {label}: `{rel_path}`\n")
        return 0

    if args.cmd == "sync":
        profile = _resolve_profile(args.repo, args.profile)
        payload = build_sync_report(profile)
        if args.format == "json":
            rendered = render_json(payload) + "\n"
        else:
            rendered = "# Moth sync\n\n"
            rendered += f"- Schema version: `{payload['schema_version']}`\n"
            rendered += f"- Generated at: `{payload['generated_at']}`\n"
            rendered += f"- Status: `{payload['status']}`\n"
            rendered += f"- Repo: `{payload['profile']['repo_path']}`\n"
            rendered += f"- CodeGraph sync: `{payload['sync']['verdict']}`\n"
            if payload.get("issues"):
                rendered += "\n## Issues\n"
                for item in payload["issues"]:
                    rendered += f"- {item}\n"
            if payload.get("warnings"):
                rendered += "\n## Warnings\n"
                for item in payload["warnings"]:
                    rendered += f"- {item}\n"
            rendered += "\n## Snapshot\n"
            rendered += render_markdown(payload["snapshot"])
        _write_output(args.output, rendered)
        sys.stdout.write(rendered)
        return 0 if payload["status"] != "FAIL" else 1

    if args.cmd == "affected":
        profile = _resolve_profile(args.repo, args.profile)
        files = [*args.file, *args.files]
        payload = build_affected_report(profile, files, depth=args.depth, test_filter=args.test_filter)
        rendered = render_json(payload) + "\n" if args.format == "json" else render_affected_markdown(payload)
        _write_output(args.output, rendered)
        sys.stdout.write(rendered)
        if payload["status"] == "FAIL":
            return 1
        if payload["status"] == "WARN":
            return 2
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
