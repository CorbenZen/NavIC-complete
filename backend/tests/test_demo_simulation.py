"""The in-app demo simulation must use the server's configured device registry.

Regression: it previously always read ``config/devices.json`` (SIM-* devices),
while the seeded fleet and ``DEVICE_REGISTRY`` use ``config/devices.demo.json``
(IVTD_BUS_*), so every simulated fix was dropped as an unknown device.
"""

from __future__ import annotations

import json
from pathlib import Path

from navic_tcp.demo_simulation import DemoSimulation

PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def _noop(_message):
    return None


def test_demo_devices_follow_configured_registry(monkeypatch):
    monkeypatch.setenv("DEVICE_REGISTRY", str(PROJECT_ROOT / "config" / "devices.demo.json"))
    devices = DemoSimulation(_noop)._get_demo_devices()
    assert devices == [f"IVTD_BUS_0{i}" for i in range(1, 7)]


def test_demo_devices_only_include_simulated_entries(monkeypatch, tmp_path):
    def entry(device_id: str, identifier_type: str) -> dict[str, str]:
        return {
            "device_id": device_id,
            "device_type": "gps_tracker_simulator",
            "identifier_type": identifier_type,
            "vehicle_id": device_id,
            "registration_number": f"REG-{device_id}",
            "driver_id": "1",
            "driver_name": "Test Driver",
        }

    registry = tmp_path / "devices.json"
    registry.write_text(
        json.dumps([entry("SIM_A", "simulated_serial"), entry("REAL_1", "imei")]),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEVICE_REGISTRY", str(registry))
    assert DemoSimulation(_noop)._get_demo_devices() == ["SIM_A"]
