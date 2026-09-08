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
    diagram = payload.get("diagram")
    if not isinstance(diagram, dict):
        raise ValueError("visual policy diagram must be a mapping")
    sparse_rule = diagram.get("sparse_rule")
    if not isinstance(sparse_rule, dict):
        raise ValueError("visual policy diagram sparse_rule must be a mapping")
    min_edges = sparse_rule.get("min_edges")
    if not isinstance(min_edges, int) or min_edges < 0:
        raise ValueError(
            "visual policy diagram sparse_rule.min_edges must be a non-negative int"
        )
    min_connected_ratio = sparse_rule.get("min_connected_ratio")
    if (
        not isinstance(min_connected_ratio, (int, float))
        or not 0 <= min_connected_ratio <= 1
    ):
        raise ValueError(
            "visual policy diagram sparse_rule.min_connected_ratio must be between 0 and 1"
        )
    for key in ("provenance_legend", "kind_reading"):
        items = diagram.get(key)
        if not isinstance(items, list) or not items:
            raise ValueError(f"visual policy diagram {key} must be a non-empty list")
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                raise ValueError(f"visual policy diagram {key} items must have an id")
    for item in diagram["provenance_legend"]:
        if item.get("line") not in {"solid", "dashed", "dotted"}:
            raise ValueError(
                "visual policy diagram provenance_legend line must be "
                "solid, dashed, or dotted"
            )
    terms = payload.get("terms")
    if not isinstance(terms, dict) or not terms:
        raise ValueError("visual policy terms must be a non-empty mapping")
    for key, value in terms.items():
        if not isinstance(value, str) or not value:
            raise ValueError("visual policy terms values must be non-empty strings")
    return payload
