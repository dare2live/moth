from __future__ import annotations

from datetime import datetime, timezone

SNAPSHOT_SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
