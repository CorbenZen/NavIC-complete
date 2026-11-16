"""Pure reporting helpers: geodesic distance, trips and measured stop/idle spans."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from itertools import pairwise
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Any


def _utc_timestamp(point: Any) -> datetime | None:
    """Normalize persisted fix timestamps so naive SQLite and aware SQL values compare consistently."""
    value = getattr(point, "timestamp", None)
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def ordered_points(points: Iterable[Any]) -> list[Any]:
    """Return timestamped fixes in stable device/time order, keeping duplicate-time fixes."""
    indexed = [(index, point, _utc_timestamp(point)) for index, point in enumerate(points)]
    usable = [(index, point, stamp) for index, point, stamp in indexed if stamp is not None and getattr(point, "device_id", None)]
    return [point for _, point, _ in sorted(usable, key=lambda item: (item[1].device_id, item[2], item[0]))]


def finite_number(value: Any) -> float | None:
    """Convert telemetry to a finite number, excluding missing and non-finite values."""
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if isfinite(numeric) else None


def valid_coordinates(point: Any) -> bool:
    """Identify fixes with finite coordinates inside the geographic ranges."""
    latitude = finite_number(getattr(point, "latitude", None))
    longitude = finite_number(getattr(point, "longitude", None))
    return latitude is not None and longitude is not None and -90 <= latitude <= 90 and -180 <= longitude <= 180


def distance_km(a: Any, b: Any) -> float:
    """Return a finite great-circle distance; invalid or absent coordinates contribute no distance."""
    values = (getattr(a, "latitude", None), getattr(a, "longitude", None), getattr(b, "latitude", None), getattr(b, "longitude", None))
    if any(value is None for value in values):
        return 0.0
    try:
        lat_a, lon_a, lat_b, lon_b = (float(value) for value in values)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not all(isfinite(value) for value in (lat_a, lon_a, lat_b, lon_b)):
        return 0.0
    if not (-90 <= lat_a <= 90 and -90 <= lat_b <= 90 and -180 <= lon_a <= 180 and -180 <= lon_b <= 180):
        return 0.0
    lat1, lat2 = radians(lat_a), radians(lat_b)
    dlat = lat2 - lat1
    dlon = radians(lon_b - lon_a)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    # Floating-point rounding can push a valid haversine a few ULPs outside [0, 1].
    return 6371.0 * 2 * asin(sqrt(min(1.0, max(0.0, h))))


def _periods(
    points: Iterable[Any],
    predicate: Callable[[Any], bool],
    minimum_minutes: float,
    max_gap_seconds: float,
) -> list[dict]:
    spans: list[dict] = []
    run: list[Any] = []

    def flush() -> None:
        nonlocal run
        if len(run) > 1:
            minutes = (_utc_timestamp(run[-1]) - _utc_timestamp(run[0])).total_seconds() / 60
            if minutes >= minimum_minutes:
                spans.append(
                    {
                        "device_id": run[0].device_id,
                        "start_time": _utc_timestamp(run[0]).isoformat(),
                        "end_time": _utc_timestamp(run[-1]).isoformat(),
                        "duration_minutes": round(minutes, 1),
                        "start_latitude": run[0].latitude,
                        "start_longitude": run[0].longitude,
                        "ends": len(run),
                    }
                )
        run = []

    for point in ordered_points(points):
        qualifying = predicate(point)
        gap = None
        if run:
            gap = (_utc_timestamp(point) - _utc_timestamp(run[-1])).total_seconds()
        if not qualifying or (run and (run[-1].device_id != point.device_id or gap is None or gap < 0 or gap > max_gap_seconds)):
            flush()
        if qualifying:
            run.append(point)
    flush()
    return spans


def stationary_periods(points: Iterable[Any], minimum_minutes: float = 5, max_gap_seconds: float = 300) -> list[dict]:
    """Measured stoppages: consecutive slow fixes with no telemetry gap."""

    return _periods(points, lambda p: _finite_speed(p) is not None and _finite_speed(p) <= 1, minimum_minutes, max_gap_seconds)


def _finite_speed(point: Any) -> float | None:
    """Read a finite speed value without treating missing or corrupt telemetry as zero."""
    return finite_number(getattr(point, "speed", None))


def idle_periods(
    points: Iterable[Any],
    minimum_minutes: float = 5,
    max_gap_seconds: float = 300,
    threshold_kmh: float = 1.0,
) -> list[dict]:
    """Engine-on, not-moving spans. Requires persisted ignition state.

    If a device never reports ignition the caller must treat idle as unsupported
    rather than guessing from speed (speed alone cannot distinguish idle from a
    parked, switched-off bus).
    """

    def predicate(point: Any) -> bool:
        return (
            getattr(point, "ignition", None) is True
            and _finite_speed(point) is not None
            and _finite_speed(point) <= threshold_kmh
        )

    return _periods(points, predicate, minimum_minutes, max_gap_seconds)


def trip_groups(points: list[Any], gap_minutes: float = 30, max_segment_km: float = 100) -> list[list[Any]]:
    """Split valid fixes into device-specific trips. Duplicate timestamps stay together; gaps over 30m split.

    Example: fixes at 08:00 and 08:02 form one trip; a fix at 08:40 starts another.
    """
    groups: list[list[Any]] = []
    by_device: dict[str, list[Any]] = {}
    for point in ordered_points(points):
        by_device.setdefault(point.device_id, []).append(point)
    for device_id in sorted(by_device):
        current: list[Any] = []
        for point in by_device[device_id]:
            if current and (_utc_timestamp(point) - _utc_timestamp(current[-1])).total_seconds() > gap_minutes * 60:
                groups.append(current)
                current = []
            current.append(point)
        if current:
            groups.append(current)
    return groups


def trip_distance_km(points: list[Any], max_gap_seconds: float = 1800, max_segment_km: float = 100) -> float:
    """Sum finite, plausible distances between consecutive same-device fixes in UTC order."""
    total = 0.0
    for first, second in pairwise(ordered_points(points)):
        if first.device_id != second.device_id:
            continue
        seconds = (_utc_timestamp(second) - _utc_timestamp(first)).total_seconds()
        segment = distance_km(first, second)
        if 0 <= seconds <= max_gap_seconds and segment <= max_segment_km:
            total += segment
    return total
