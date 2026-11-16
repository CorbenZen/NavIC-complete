"""In-memory latest tracking state and bounded recent history."""

from __future__ import annotations

from collections import deque
from copy import deepcopy
from datetime import datetime
from typing import Any

from .protocol import utc_now
from .registry import DeviceRegistry


class TelemetryStore:
    def __init__(self, history_limit: int = 100, registry: DeviceRegistry | None = None):
        if history_limit < 1:
            raise ValueError("history_limit must be positive")
        self.history_limit = history_limit
        self.registry_enforced = registry is not None
        self.registry = registry or DeviceRegistry([])
        self._devices: dict[str, dict[str, Any]] = {}
        self._history: dict[str, deque[dict[str, Any]]] = {}
        self._sessions: dict[str, int] = {}

    def record(self, telemetry: dict[str, Any]) -> None:
        device_id = telemetry["device_id"]
        received_at = utc_now()
        point = {
            "message_id": telemetry["message_id"],
            "timestamp": telemetry["timestamp"],
            "received_at": received_at,
            "latitude": telemetry["latitude"],
            "longitude": telemetry["longitude"],
            "speed": telemetry["speed"],
            "course": telemetry["course"],
            "ignition": telemetry["ignition"],
            "simulated": telemetry["simulated"],
        }
        if "odometer" in telemetry:
            point["odometer"] = telemetry["odometer"]

        history = self._history.setdefault(device_id, deque(maxlen=self.history_limit))
        history.append(deepcopy(point))
        previous = self._devices.get(device_id)
        previous_point = previous["latest"] if previous else None
        if previous_point is None or datetime.fromisoformat(telemetry["timestamp"].replace("Z", "+00:00")) >= datetime.fromisoformat(previous_point["timestamp"].replace("Z", "+00:00")):
            latest = deepcopy(point)
        else:
            latest = previous_point
        self._devices[device_id] = {
            "device_id": device_id,
            "identity": self.registry.get(device_id),
            "online": self._sessions.get(device_id, 0) > 0,
            "first_received_at": previous["first_received_at"] if previous else received_at,
            "last_received_at": received_at,
            "last_message_timestamp": telemetry["timestamp"],
            "message_count": (previous["message_count"] if previous else 0) + 1,
            "latest": latest,
        }

    def _empty_state(self, device_id: str) -> dict[str, Any]:
        return {
            "device_id": device_id,
            "identity": self.registry.get(device_id),
            "online": self._sessions.get(device_id, 0) > 0,
            "first_received_at": None,
            "last_received_at": None,
            "last_message_timestamp": None,
            "message_count": 0,
            "latest": None,
        }

    def connect_device(self, device_id: str) -> None:
        if device_id not in self._devices:
            return
        self._sessions[device_id] = self._sessions.get(device_id, 0) + 1
        self._devices[device_id]["online"] = True

    def disconnect_device(self, device_id: str) -> None:
        active = self._sessions.get(device_id, 0)
        if active <= 1:
            self._sessions.pop(device_id, None)
            active = 0
        else:
            active -= 1
            self._sessions[device_id] = active
        if device_id in self._devices:
            self._devices[device_id]["online"] = active > 0

    def list_devices(self) -> list[dict[str, Any]]:
        known = set(self.registry.device_ids) | set(self._devices)
        return [deepcopy(self._devices.get(key) or self._empty_state(key)) for key in sorted(known)]

    def get_device(self, device_id: str) -> dict[str, Any] | None:
        state = self._devices.get(device_id)
        if state is not None:
            return deepcopy(state)
        if self.registry.get(device_id) is not None:
            return self._empty_state(device_id)
        return None

    def get_history(self, device_id: str, limit: int | None = None) -> list[dict[str, Any]] | None:
        if device_id not in self._devices and self.registry.get(device_id) is None:
            return None
        history = self._history.get(device_id, deque())
        points = sorted(history, key=lambda point: point["timestamp"])
        if limit is not None:
            points = points[-limit:]
        return deepcopy(points)

    @property
    def device_count(self) -> int:
        return len(set(self.registry.device_ids) | set(self._devices))
