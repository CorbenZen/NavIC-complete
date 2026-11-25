"""Deterministic live vehicle classification from a persisted telemetry fix."""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

LOG = logging.getLogger("navic_tcp.vehicle_status")

FRESHNESS_SECONDS = 300
MOVE_SPEED_KMH = 2.0
TOING_SPEED_KMH = 5.0
FUTURE_CLOCK_SKEW_SECONDS = 120
DEMO_FRESHNESS_SECONDS = 20.0  # Shorter window for demo devices


def freshness_for_source(data_source: str | None) -> float:
    """Display freshness window for a persisted fix, chosen by its provenance.

    Simulator fixes arrive every 1-2 s, so they use the short demo window and
    a stopped simulation reads as Out Of N/w within seconds after a page
    refresh, matching the live view. Hardware and unknown sources keep the
    5-minute window that tolerates brief real-world signal loss.
    """
    return DEMO_FRESHNESS_SECONDS if data_source == "simulator" else FRESHNESS_SECONDS

STATUS_LABELS = {
    "ON_MOVE": "On Move",
    "STOPPED": "Stopped",
    "IDLE": "Idle",
    "OUT_OF_NETWORK": "Out Of N/w",
    "TOING": "Toing",
}


@dataclass(frozen=True)
class VehicleStatus:
    status: str
    status_key: str
    ignition_available: bool
    age_seconds: int | None
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def _parse_timestamp(value: datetime | str | None) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            LOG.warning("vehicle status received an invalid telemetry timestamp")
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def classify_vehicle_status(
    speed: float | None,
    ignition: bool | None,
    last_seen: datetime | str | None,
    now: datetime | None = None,
    *,
    freshness_seconds: float = FRESHNESS_SECONDS,
) -> VehicleStatus:
    """Classify one vehicle; missing/unsafe data never implies ignition OFF.

    Fresh stationary records with unknown ignition use STOPPED as the legacy
    safe display bucket, while ``ignition_available`` and ``reason`` preserve
    the fact that STOPPED could not be confirmed as engine-on.
    """
    now_utc = _parse_timestamp(now or datetime.now(timezone.utc))
    stamp = _parse_timestamp(last_seen)
    if stamp is None:
        return VehicleStatus("OUT_OF_NETWORK", "out_of_network", ignition is not None, None, "no_valid_fix")

    age = (now_utc - stamp).total_seconds() if now_utc else math.inf
    if age < -FUTURE_CLOCK_SKEW_SECONDS:
        LOG.warning("vehicle status ignored telemetry timestamp beyond clock-skew tolerance")
        return VehicleStatus("OUT_OF_NETWORK", "out_of_network", ignition is not None, None, "future_timestamp")
    age = max(0.0, age)
    if age > freshness_seconds:
        return VehicleStatus("OUT_OF_NETWORK", "out_of_network", ignition is not None, int(age), "stale_telemetry")

    if speed is None or isinstance(speed, bool):
        LOG.warning("vehicle status has no valid speed for a fresh telemetry fix")
        return VehicleStatus("OUT_OF_NETWORK", "out_of_network", ignition is not None, int(age), "invalid_speed")
    try:
        speed_value = float(speed)
    except (TypeError, ValueError):
        speed_value = math.nan
    if not math.isfinite(speed_value) or speed_value < 0:
        LOG.warning("vehicle status ignored an invalid telemetry speed")
        return VehicleStatus("OUT_OF_NETWORK", "out_of_network", ignition is not None, int(age), "invalid_speed")

    if ignition is False and speed_value > TOING_SPEED_KMH:
        code, reason = "TOING", "moving_with_ignition_off"
    elif ignition is False:
        # With ignition explicitly off, the 5 km/h towing threshold is the
        # movement discriminator; values at or below it use the idle bucket.
        code, reason = "IDLE", "ignition_off_below_toing_threshold"
    elif speed_value > MOVE_SPEED_KMH:
        code, reason = "ON_MOVE", "moving"
    elif ignition is True:
        code, reason = "STOPPED", "stationary_with_ignition_on"
    else:
        code, reason = "STOPPED", "stationary_ignition_unknown"

    return VehicleStatus(code, code.lower(), ignition is not None, int(age), reason)
