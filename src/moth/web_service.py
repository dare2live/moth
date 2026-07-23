"""Safe-view orchestration boundary for one configured Web Console project."""

from __future__ import annotations

import os
import uuid
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from moth.inspection import build_inspection
from moth.visual_model import (
    build_visual_model,
    validate_visual_document_schema,
    validate_visual_model,
)
from moth.web_config import WebProject, load_web_policy


def _codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def build_project_view(project: WebProject) -> dict[str, Any]:
    """Build one fresh, portable view without repo-configured executables."""

    policy = load_web_policy()
    inspection = build_inspection(
        project.profile,
        task_kind=str(policy["api"]["task_kind"]),
        run_id=f"web-{uuid.uuid4().hex}",
        receipts=[],
        codex_home=_codex_home(),
        execution_policy="safe_view",
    )
    visual_document = build_visual_model(inspection)
    validation_errors = [
        *validate_visual_document_schema(visual_document),
        *validate_visual_model(visual_document),
    ]
    if validation_errors:
        raise ValueError("visual document failed validation")
    result = {
        "schema_version": "moth.web-project-view.v1",
        "project": project.public_metadata(),
        "execution_policy": "safe_view",
        "inspection": inspection,
        "visual_document": visual_document,
    }
    wrapper_schema = json.loads(
        files("moth.schemas")
        .joinpath("moth.web-project-view.schema.json")
        .read_text(encoding="utf-8")
    )
    if next(Draft202012Validator(wrapper_schema).iter_errors(result), None) is not None:
        raise ValueError("web project view failed validation")
    return result
