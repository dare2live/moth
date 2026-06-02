from __future__ import annotations

from moth.report import build_report, render_json, render_markdown

__all__ = ["build_snapshot", "render_json", "render_markdown"]


def build_snapshot(profile):
    return build_report(profile)
