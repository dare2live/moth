"""Single core call for registry, discovery, and task context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from moth.decision_context import build_decision_context
from moth.guidance import resolve_guidance_sources
from moth.guidance_registry import load_guidance_registry


def prepare_task_context(
    profile_sources: dict[str, Any],
    *,
    task_kind: str,
    run_id: str,
    receipts: list[dict[str, Any]],
    codex_home: str | Path,
    application_reports: list[dict[str, Any]] | None = None,
    available_evidence_ids: set[str] | None = None,
) -> dict[str, Any]:
    registry = load_guidance_registry(profile_sources, codex_home=codex_home)
    guidance = resolve_guidance_sources({"sources": registry["sources"]}, codex_home=codex_home)
    context = build_decision_context(
        guidance,
        task_kind=task_kind,
        run_id=run_id,
        receipts=receipts,
        application_reports=application_reports,
        available_evidence_ids=available_evidence_ids,
    )
    return {
        "schema_version": "moth.orchestration.v1",
        "registry": registry,
        "guidance": guidance,
        "decision_context": context,
    }
