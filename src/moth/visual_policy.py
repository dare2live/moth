"""Packaged visual taxonomy; rendering logic stays separate from page policy."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import Any

import yaml


@lru_cache(maxsize=1)
def load_visual_policy() -> dict[str, Any]:
    resource = files("moth").joinpath("visual_policy.yaml")
    payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("kind") != "moth_visual_policy":
        raise ValueError("visual policy must be a moth_visual_policy mapping")
    layers = payload.get("layers")
    viewpoints = payload.get("viewpoints")
    limits = payload.get("limits")
    if not isinstance(layers, list) or not layers:
        raise ValueError("visual policy layers must be a non-empty list")
    if not isinstance(viewpoints, list) or not viewpoints:
        raise ValueError("visual policy viewpoints must be a non-empty list")
    if not isinstance(limits, dict):
        raise ValueError("visual policy limits must be a mapping")
    if not isinstance(payload.get("status_labels"), dict):
        raise ValueError("visual policy status_labels must be a mapping")
    layer_ids = [str(item.get("id", "")) for item in layers if isinstance(item, dict)]
    if len(layer_ids) != len(layers) or len(set(layer_ids)) != len(layer_ids):
        raise ValueError("visual policy layer ids must be present and unique")
    known_layers = set(layer_ids)
    for viewpoint in viewpoints:
        if not isinstance(viewpoint, dict):
            raise ValueError("visual policy viewpoints must be mappings")
        referenced = viewpoint.get("layer_ids")
        if not isinstance(referenced, list) or not referenced:
            raise ValueError("visual policy viewpoint layer_ids must be non-empty lists")
        if not set(map(str, referenced)) <= known_layers:
            raise ValueError("visual policy viewpoint references unknown layers")
    for key in ("priorities", "avoid"):
        value = limits.get(key)
        if not isinstance(value, int) or value < 1 or value > 20:
            raise ValueError(f"visual policy limit {key} must be between 1 and 20")
    for key in (
        "entities_per_layer",
        "relations_per_layer",
        "findings_per_layer",
        "evidence_per_layer",
    ):
        value = limits.get(key)
        if not isinstance(value, int) or value < 1 or value > 1_000:
            raise ValueError(f"visual policy limit {key} must be between 1 and 1000")
    return payload
