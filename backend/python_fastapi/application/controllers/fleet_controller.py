"""Fleet controller: read models for vehicles, drivers, routes, geofences and devices."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from backend.python_fastapi.application.controllers.base import Controller
from backend.python_fastapi.application.core.dependencies import current_user
from backend.python_services import fleet_service
from backend.python_sqlalchemy.database.session import SessionLocal
from navic_tcp.fastapi_app import _device_payload, _route_payload, bus_response


def _driver_payload(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "email": row.email,
        "phone": row.phone,
        "license_number": row.license_number,
        "active": row.active,
        "assigned_vehicles": [
            {"id": bus.id, "registration_number": bus.registration_number, "vehicle_id": bus.vehicle_id}
            for bus in row.buses
        ],
    }


def list_buses(user=Depends(current_user)):
    with SessionLocal() as db:
        rows = fleet_service.list_buses(db)
        return [bus_response(db, row) for row in rows]


def get_bus(bus_id: int, user=Depends(current_user)):
    with SessionLocal() as db:
        row = fleet_service.get_bus(db, bus_id)
        if not row:
            raise HTTPException(404, "bus not found")
        return bus_response(db, row)


def list_drivers(user=Depends(current_user)):
    with SessionLocal() as db:
        return [_driver_payload(row) for row in fleet_service.list_drivers(db)]


def list_routes(user=Depends(current_user)):
    with SessionLocal() as db:
        return [_route_payload(row) for row in fleet_service.list_routes(db)]


def list_geofences(user=Depends(current_user)):
    with SessionLocal() as db:
        return fleet_service.list_geofences(db)


def list_devices(user=Depends(current_user)):
    with SessionLocal() as db:
        return {"devices": [_device_payload(db, device) for device in fleet_service.list_devices(db)]}


class FleetController(Controller):
    # Paths that also expose POST/PUT/DELETE are matched by method so the
    # read overrides never shadow the shared write handlers.
    operations = {
        "/buses": {"GET": list_buses},
        "/api/vehicles": {"GET": list_buses},
        "/buses/{bus_id}": {"GET": get_bus},
        "/api/vehicles/{bus_id}": {"GET": get_bus},
        "/drivers": {"GET": list_drivers},
        "/api/drivers": {"GET": list_drivers},
        "/routes": {"GET": list_routes},
        "/api/routes": {"GET": list_routes},
        "/geofences": {"GET": list_geofences},
        "/api/geofences": {"GET": list_geofences},
        "/devices": {"GET": list_devices},
        "/api/devices": {"GET": list_devices},
    }


__all__ = [
    "FleetController",
    "get_bus",
    "list_buses",
    "list_devices",
    "list_drivers",
    "list_geofences",
    "list_routes",
]
