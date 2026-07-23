"""Load the packaged task/activation taxonomy as one truth source."""

from __future__ import annotations

from importlib.resources import files
from typing import Any

import yaml


def load_guidance_policy() -> dict[str, Any]:
    payload = yaml.safe_load(
        files("moth").joinpath("guidance_policy.yaml").read_text(encoding="utf-8")
    )
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != "moth_guidance_policy"
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("activations"), list)
        or not isinstance(payload.get("task_kinds"), dict)
    ):
        raise ValueError("invalid packaged guidance policy")
    activations = payload["activations"]
    if not activations or not all(isinstance(item, str) for item in activations):
        raise ValueError("invalid packaged guidance activations")
    allowed = set(activations)
    for task_kind, task_activations in payload["task_kinds"].items():
        if not isinstance(task_kind, str) or not isinstance(task_activations, list):
            raise ValueError("invalid packaged guidance task taxonomy")
        if not all(isinstance(item, str) and item in allowed for item in task_activations):
            raise ValueError("invalid packaged guidance task activation")
    return payload


GUIDANCE_POLICY = load_guidance_policy()
ACTIVATIONS = frozenset(GUIDANCE_POLICY["activations"])
TASK_ACTIVATIONS = {
    str(task): frozenset(activations)
    for task, activations in GUIDANCE_POLICY["task_kinds"].items()
}
TASK_KINDS = tuple(TASK_ACTIVATIONS)
