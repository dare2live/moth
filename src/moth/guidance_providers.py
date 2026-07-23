"""Explicit provider registry for local Guidance source discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Callable


Resolver = Callable[[str, Path], Path | None]


def _resolve_codex_skill(source_id: str, codex_home: Path) -> Path | None:
    candidates = (
        codex_home / "skills" / source_id / "SKILL.md",
        Path.home() / ".agents" / "skills" / source_id / "SKILL.md",
    )
    return next((path for path in candidates if path.is_file()), None)


_PROVIDERS: dict[str, Resolver] = {"codex_skill": _resolve_codex_skill}


def registered_guidance_providers() -> frozenset[str]:
    return frozenset(_PROVIDERS)


def resolve_guidance_path(provider: str, source_id: str, codex_home: Path) -> Path | None:
    resolver = _PROVIDERS.get(provider)
    return resolver(source_id, codex_home) if resolver is not None else None
