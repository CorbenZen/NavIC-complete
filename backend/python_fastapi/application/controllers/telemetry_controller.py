"""Telemetry controller: latest device fix and GNSS metadata."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from backend.python_fastapi.application.controllers.base import Controller
from backend.python_fastapi.application.core.dependencies import current_user
from backend.python_services import fleet_service, telemetry_service
from backend.python_sqlalchemy.database.session import SessionLocal
from navic_tcp.fastapi_app import GNSS_COMPATIBILITY, _device_payload, _point_payload


def device_telemetry_latest(device_id: str, user=Depends(current_user)):
    with SessionLocal() as db:
        device = fleet_service.get_device_by_identifier(db, device_id)
        if not device:
            raise HTTPException(404, "device not found")
        latest = telemetry_service.latest_for_device(db, device_id)
        return {
            "device_id": device_id,
            "identity": _device_payload(db, device)["identity"],
            "latest": _point_payload(latest),
            "gnss_compatibility": GNSS_COMPATIBILITY,
        }


class TelemetryController(Controller):
    operations = {
        "/api/devices/{device_id}/telemetry/latest": device_telemetry_latest,
    }


__all__ = ["TelemetryController", "device_telemetry_latest"]
