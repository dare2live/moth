#!/usr/bin/env python3
"""Create bounded executor self-attestations for planned Guidance sources."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("inspection JSON is unreadable") from exc
    if not isinstance(payload, dict):
        raise ValueError("inspection JSON must be an object")
    return payload


def build_receipts(
    inspection: dict[str, Any],
    *,
    loaded_sources: list[str],
) -> list[dict[str, Any]]:
    orchestration = inspection.get("orchestration")
    if not isinstance(orchestration, dict):
        raise ValueError("inspection has no orchestration contract")
    decision = orchestration.get("decision_context")
    guidance = orchestration.get("guidance")
    if not isinstance(decision, dict) or not isinstance(guidance, dict):
        raise ValueError("inspection has no decision context or guidance")
    task = decision.get("task")
    run_id = (
        task.get("run_id")
        if isinstance(task, dict)
        else decision.get("run_id")
    )
    ordered = decision.get("ordered_guidance_sources")
    if not isinstance(run_id, str) or not SAFE_ID.fullmatch(run_id):
        raise ValueError("inspection run_id is invalid")
    if (
        not isinstance(ordered, list)
        or not all(
            isinstance(source_id, str) and SAFE_ID.fullmatch(source_id)
            for source_id in ordered
        )
    ):
        raise ValueError("inspection activation order is invalid")
    if loaded_sources != ordered:
        raise ValueError(
            "loaded sources must exactly match activation order"
        )

    sources = guidance.get("sources")
    if not isinstance(sources, list):
        raise ValueError("inspection guidance sources are invalid")
    by_id = {
        source.get("id"): source
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("id"), str)
    }
    loaded_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    receipts: list[dict[str, Any]] = []
    for source_id in ordered:
        source = by_id.get(source_id)
        if not isinstance(source, dict) or source.get("state") != "DISCOVERED":
            raise ValueError(f"guidance source {source_id} is not DISCOVERED")
        digest = source.get("source_digest")
        if not isinstance(digest, str) or not digest:
            raise ValueError(
                f"guidance source {source_id} has no source digest"
            )
        digest_token = re.sub(r"[^A-Za-z0-9]", "", digest)[-12:] or "digest"
        receipts.append(
            {
                "receipt_id": f"receipt-{source_id}-{digest_token}",
                "run_id": run_id,
                "source_id": source_id,
                "source_digest": digest,
                "executor_id": "codex-moth-skill",
                "loaded_at": loaded_at,
                "contract_id": "moth-skill-self-attestation-v1",
                "evidence_refs": [f"ev:self-attested-skill-read:{source_id}"],
            }
        )
    return receipts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--loaded-source",
        action="append",
        default=[],
        help="Skill ID loaded by the executor; repeat in activation order",
    )
    args = parser.parse_args()
    try:
        inspection = _load_object(args.inspection)
        receipts = build_receipts(
            inspection,
            loaded_sources=args.loaded_source,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipts, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
