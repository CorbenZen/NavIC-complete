"""Fictional local registry joining tracking devices to vehicle/driver records."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_REQUIRED = {"device_id", "device_type", "identifier_type", "vehicle_id", "registration_number", "driver_id", "driver_name"}
_OPTIONAL = {"sim_identifier", "device_secret"}
_ALLOWED_IDENTIFIER_TYPES = {
    "simulated_imei",
    "simulated_serial",
    "imei",
    "serial",
    "iccid",
    "device_serial",
}
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "devices.json"


class DeviceRegistry:
    def __init__(self, entries: list[dict[str, Any]]):
        self._entries: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or _REQUIRED - entry.keys() or entry.keys() - (_REQUIRED | _OPTIONAL):
                raise ValueError("each device registry entry must use the documented fields")
            device_id = entry["device_id"]
            if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
                raise ValueError("registry device_id must be 1-64 safe identifier characters")
            if device_id in self._entries:
                raise ValueError(f"duplicate registry device_id: {device_id}")
            if not isinstance(entry["identifier_type"], str) or entry["identifier_type"] not in _ALLOWED_IDENTIFIER_TYPES:
                raise ValueError("identifier_type must be one of " + ", ".join(sorted(_ALLOWED_IDENTIFIER_TYPES)))
            for field in _REQUIRED - {"device_id"}:
                if not isinstance(entry[field], str) or not entry[field].strip():
                    raise ValueError(f"registry {field} must be a non-empty string")
            sim_id = entry.get("sim_identifier")
            if sim_id is not None and not isinstance(sim_id, str):
                raise ValueError("sim_identifier must be a string or null")
            device_secret = entry.get("device_secret")
            if device_secret is not None and (not isinstance(device_secret, str) or not device_secret):
                raise ValueError("device_secret must be a non-empty string or null")
            self._entries[device_id] = dict(entry)

    @classmethod
    def load(cls, path: str | Path) -> DeviceRegistry:
        with Path(path).open(encoding="utf-8") as source:
            entries = json.load(source)
        if not isinstance(entries, list):
            raise ValueError("device registry JSON must contain an array")
        return cls(entries)

    def get(self, device_id: str) -> dict[str, Any] | None:
        entry = self._entries.get(device_id)
        return dict(entry) if entry is not None else None

    def upsert(self, entry: dict[str, Any]) -> None:
        """Register/update an application-managed device for TCP identity checks."""
        validated = DeviceRegistry([entry])
        self._entries[entry["device_id"]] = validated.get(entry["device_id"])

    def remove(self, device_id: str) -> None:
        self._entries.pop(device_id, None)

    def list(self) -> list[dict[str, Any]]:
        return [dict(self._entries[key]) for key in sorted(self._entries)]

    @property
    def device_ids(self) -> list[str]:
        return sorted(self._entries)
