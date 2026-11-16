"""Fleet data-access service.

These functions are the transactional CRUD layer for vehicles, drivers, routes,
geofences and tracking devices.  The HTTP path operations keep their existing
response shaping; this service provides reusable, tested access for backend
tooling and new features.
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.python_sqlalchemy.models import (
    Bus,
    Driver,
    Geofence,
    Route,
    TrackingDevice,
)

ModelT = TypeVar("ModelT")


def _list(db: Session, model: type[ModelT]) -> list[ModelT]:
    return list(db.scalars(select(model).order_by(model.id)).all())


def list_buses(db: Session) -> list[Bus]:
    return _list(db, Bus)


def get_bus(db: Session, bus_id: int) -> Bus | None:
    return db.get(Bus, bus_id)


def list_drivers(db: Session) -> list[Driver]:
    return _list(db, Driver)


def get_driver(db: Session, driver_id: int) -> Driver | None:
    return db.get(Driver, driver_id)


def list_routes(db: Session) -> list[Route]:
    return _list(db, Route)


def get_route(db: Session, route_id: int) -> Route | None:
    return db.get(Route, route_id)


def list_geofences(db: Session) -> list[Geofence]:
    return _list(db, Geofence)


def get_geofence(db: Session, geofence_id: int) -> Geofence | None:
    return db.get(Geofence, geofence_id)


def list_devices(db: Session) -> list[TrackingDevice]:
    return _list(db, TrackingDevice)


def get_device(db: Session, device_pk: int) -> TrackingDevice | None:
    return db.get(TrackingDevice, device_pk)


def get_device_by_identifier(db: Session, device_id: str) -> TrackingDevice | None:
    return db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == device_id))


def fleet_counts(db: Session) -> dict[str, int]:
    """Return record counts used by dashboards and diagnostics."""
    return {
        "vehicles": int(db.scalar(select(func.count()).select_from(Bus)) or 0),
        "drivers": int(db.scalar(select(func.count()).select_from(Driver)) or 0),
        "routes": int(db.scalar(select(func.count()).select_from(Route)) or 0),
        "geofences": int(db.scalar(select(func.count()).select_from(Geofence)) or 0),
        "devices": int(db.scalar(select(func.count()).select_from(TrackingDevice)) or 0),
    }


def create_record(db: Session, model: type[ModelT], **fields: Any) -> ModelT:
    """Insert a record in a transaction and return the refreshed instance."""
    record = model(**fields)
    db.add(record)
    try:
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        raise
    return record


def update_record(db: Session, model: type[ModelT], record_id: Any, **fields: Any) -> ModelT | None:
    """Update a record in a transaction; return ``None`` when it is absent."""
    record = db.get(model, record_id)
    if record is None:
        return None
    for key, value in fields.items():
        setattr(record, key, value)
    try:
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        raise
    return record


def delete_record(db: Session, model: type[ModelT], record_id: Any) -> bool:
    """Delete a record in a transaction; return whether it existed."""
    record = db.get(model, record_id)
    if record is None:
        return False
    db.delete(record)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True


__all__ = [
    "create_record",
    "delete_record",
    "fleet_counts",
    "get_bus",
    "get_device",
    "get_device_by_identifier",
    "get_driver",
    "get_geofence",
    "get_route",
    "list_buses",
    "list_devices",
    "list_drivers",
    "list_geofences",
    "list_routes",
    "update_record",
]
