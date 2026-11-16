"""Small, dependency-free backend helpers."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """Normalise a datetime to UTC, treating naive values as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def isoformat(value: datetime | date | None) -> str | None:
    """Serialise a datetime/date as an ISO-8601 string."""
    return value.isoformat() if value is not None else None


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse common boolean representations."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def clamp(value: float, low: float, high: float) -> float:
    """Clamp *value* into the inclusive ``[low, high]`` range."""
    return max(low, min(high, value))


def page_params(limit: int | None, offset: int | None, *, max_limit: int = 500) -> tuple[int, int]:
    """Normalise pagination arguments to safe non-negative values."""
    safe_limit = max(1, min(int(limit or 100), max_limit))
    safe_offset = max(0, int(offset or 0))
    return safe_limit, safe_offset


def json_default(value: Any) -> Any:
    """``json.dumps`` fallback for dates and datetimes."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def to_json(payload: Any) -> str:
    """Serialise *payload* with date support."""
    return json.dumps(payload, default=json_default, sort_keys=True)


__all__ = [
    "as_utc",
    "clamp",
    "isoformat",
    "json_default",
    "page_params",
    "parse_bool",
    "to_json",
    "utc_now",
]
