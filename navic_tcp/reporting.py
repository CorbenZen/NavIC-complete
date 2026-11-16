"""Pure reporting helpers: geodesic distance, trips and measured stop/idle spans."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from itertools import pairwise
from math import asin, cos, radians, sin, sqrt
from typing import Any


def distance_km(a: Any, b: Any) -> float:
    """Great-circle distance between two objects with latitude/longitude."""
    if None in (a.latitude, a.longitude, b.latitude, b.longitude):
        return 0.0
    lat1, lat2 = radians(a.latitude), radians(b.latitude)
    dlat = lat2 - lat1
    dlon = radians(b.longitude - a.longitude)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(min(1.0, sqrt(h)))


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
            minutes = (run[-1].timestamp - run[0].timestamp).total_seconds() / 60
            if minutes >= minimum_minutes:
                spans.append(
                    {
                        "device_id": run[0].device_id,
                        "start_time": run[0].timestamp.isoformat(),
                        "end_time": run[-1].timestamp.isoformat(),
                        "duration_minutes": round(minutes, 1),
                        "start_latitude": run[0].latitude,
                        "start_longitude": run[0].longitude,
                        "ends": len(run),
                    }
                )
        run = []

    for point in points:
        qualifying = predicate(point)
        gap = None
        if run:
            gap = (point.timestamp - run[-1].timestamp).total_seconds()
        if not qualifying or (run and (run[-1].device_id != point.device_id or gap is None or gap < 0 or gap > max_gap_seconds)):
            flush()
        if qualifying:
            run.append(point)
    flush()
    return spans


def stationary_periods(points: Iterable[Any], minimum_minutes: float = 5, max_gap_seconds: float = 300) -> list[dict]:
    """Measured stoppages: consecutive slow fixes with no telemetry gap."""

    return _periods(points, lambda p: p.speed is not None and p.speed <= 1, minimum_minutes, max_gap_seconds)


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
            and point.speed is not None
            and point.speed <= threshold_kmh
        )

    return _periods(points, predicate, minimum_minutes, max_gap_seconds)


def trip_groups(points: list[Any], gap_minutes: float = 30, max_segment_km: float = 100) -> list[list[Any]]:
    """Split sorted points per device into trips at long telemetry gaps."""
    groups: list[list[Any]] = []
    by_device: dict[str, list[Any]] = {}
    for point in points:
        by_device.setdefault(point.device_id, []).append(point)
    for device_id in sorted(by_device):
        current: list[Any] = []
        for point in by_device[device_id]:
            if current and (point.timestamp - current[-1].timestamp).total_seconds() > gap_minutes * 60:
                groups.append(current)
                current = []
            current.append(point)
        if current:
            groups.append(current)
    return groups


def trip_distance_km(points: list[Any], max_gap_seconds: float = 1800, max_segment_km: float = 100) -> float:
    total = 0.0
    for first, second in pairwise(points):
        seconds = (second.timestamp - first.timestamp).total_seconds()
        segment = distance_km(first, second)
        if 0 <= seconds <= max_gap_seconds and segment <= max_segment_km:
            total += segment
    return total
