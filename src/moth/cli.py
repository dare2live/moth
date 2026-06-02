from __future__ import annotations

import argparse
import sys

from moth.profiles.loader import load_profile, match_profile
from moth.report import build_sync_report
from moth.snapshot import build_snapshot, render_json, render_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="moth", description="Cross-repo audit atlas")
    sub = parser.add_subparsers(dest="cmd", required=True)

    snapshot = sub.add_parser("snapshot", help="Emit a machine-readable repo snapshot")
    snapshot.add_argument("--repo", required=True, help="Repo path to inspect")
    snapshot.add_argument("--profile", help="Explicit profile name or YAML path")
    snapshot.add_argument("--format", choices=("markdown", "json"), default="json")

    doctor = sub.add_parser("doctor", help="Validate a repo profile and emit a summary")
    doctor.add_argument("--repo", required=True, help="Repo path to inspect")
    doctor.add_argument("--profile", help="Explicit profile name or YAML path")
    doctor.add_argument("--format", choices=("markdown", "json"), default="markdown")

    report = sub.add_parser("report", help="Render a report for a repo profile")
    report.add_argument("--repo", required=True, help="Repo path to inspect")
    report.add_argument("--profile", help="Explicit profile name or YAML path")
    report.add_argument("--format", choices=("markdown", "json"), default="markdown")

    profile_cmd = sub.add_parser("profile", help="Show a profile")
    profile_cmd.add_argument("ref", help="Profile name or YAML path")
    profile_cmd.add_argument("--format", choices=("markdown", "json"), default="json")

    sync_cmd = sub.add_parser("sync", help="Refresh CodeGraph and emit the latest snapshot")
    sync_cmd.add_argument("--repo", required=True, help="Repo path to inspect")
    sync_cmd.add_argument("--profile", help="Explicit profile name or YAML path")
    sync_cmd.add_argument("--format", choices=("markdown", "json"), default="json")

    return parser


def _resolve_profile(repo: str, profile_ref: str | None):
    if profile_ref:
        return load_profile(profile_ref)
    matched = match_profile(repo)
    if matched is None:
        raise SystemExit(f"no profile matched repo {repo!r}; pass --profile explicitly")
    return matched


def _render_mapping_block(mapping: dict[str, object]) -> list[str]:
    return [f"  - {sub_key}: `{sub_value}`" for sub_key, sub_value in mapping.items()]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd in {"doctor", "report", "snapshot"}:
        profile = _resolve_profile(args.repo, args.profile)
        payload = build_snapshot(profile)
        if args.format == "json":
            sys.stdout.write(render_json(payload) + "\n")
        else:
            sys.stdout.write(render_markdown(payload))
        return 0 if payload["status"] != "FAIL" else 1

    if args.cmd == "profile":
        profile = load_profile(args.ref)
        payload = {
            "name": profile.name,
            "repo_path": str(profile.repo_path),
            "codegraph_root": str(profile.codegraph_root),
            "complexity_command": profile.complexity_command,
            "evidence_paths": {label: str(path) for label, path in profile.evidence_paths.items()},
            "notes": profile.notes,
        }
        if args.format == "markdown":
            sys.stdout.write("# Moth profile\n\n")
            for key, value in payload.items():
                if isinstance(value, dict):
                    sys.stdout.write(f"- {key}:\n")
                    sys.stdout.write("\n".join(_render_mapping_block(value)) + "\n")
                else:
                    sys.stdout.write(f"- {key}: `{value}`\n")
        else:
            sys.stdout.write(render_json(payload) + "\n")
        return 0

    if args.cmd == "sync":
        profile = _resolve_profile(args.repo, args.profile)
        payload = build_sync_report(profile)
        if args.format == "json":
            sys.stdout.write(render_json(payload) + "\n")
        else:
            sys.stdout.write("# Moth sync\n\n")
            sys.stdout.write(f"- Status: `{payload['status']}`\n")
            sys.stdout.write(f"- Repo: `{payload['profile']['repo_path']}`\n")
            sys.stdout.write(f"- CodeGraph sync: `{payload['sync']['verdict']}`\n")
            if payload.get("issues"):
                sys.stdout.write("\n## Issues\n")
                for item in payload["issues"]:
                    sys.stdout.write(f"- {item}\n")
            if payload.get("warnings"):
                sys.stdout.write("\n## Warnings\n")
                for item in payload["warnings"]:
                    sys.stdout.write(f"- {item}\n")
            sys.stdout.write("\n## Snapshot\n")
            sys.stdout.write(render_markdown(payload["snapshot"]))
        return 0 if payload["status"] != "FAIL" else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
