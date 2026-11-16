"""Create the development schema and seed demo records.

Run from the repository root with the configured local environment:
    .venv-local/bin/python -m backend.python_sqlalchemy.database.seed

All seeded buses, drivers, routes and coordinates are demo data. The script is
idempotent and never deletes existing records or resets a database.
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load the project-root .env before importing ``navic_tcp.db``: the engine reads
# DATABASE_URL at import time.
from navic_tcp.env import load_env_file

load_env_file(PROJECT_ROOT / ".env")

from navic_tcp.db import SessionLocal, engine
from navic_tcp.models import Bus, Driver, Geofence, Route, TrackingDevice
from navic_tcp.schema import ensure_schema

# Illustrative stop sequences around the HKBK campus area (Bengaluru). These
# are demo points, not a surveyed road route or a claim about a real bus service.
DEMO_ROUTES = [
    {
        "identifier": "DEMO-NORTH",
        "name": "Demo North Route",
        "start_point": "HKBK Campus (demo)",
        "destination": "North Gate (demo)",
        "color": "#0f766e",
        "stops": [
            {"name": "Campus", "latitude": 13.0405, "longitude": 77.6200},
            {"name": "Demo Stop A", "latitude": 13.0460, "longitude": 77.6240},
            {"name": "Demo Stop B", "latitude": 13.0515, "longitude": 77.6285},
            {"name": "North Gate", "latitude": 13.0560, "longitude": 77.6320},
        ],
    },
    {
        "identifier": "DEMO-SOUTH",
        "name": "Demo South Route",
        "start_point": "HKBK Campus (demo)",
        "destination": "South Gate (demo)",
        "color": "#2563eb",
        "stops": [
            {"name": "Campus", "latitude": 13.0405, "longitude": 77.6200},
            {"name": "Demo Stop C", "latitude": 13.0350, "longitude": 77.6150},
            {"name": "Demo Stop D", "latitude": 13.0300, "longitude": 77.6100},
            {"name": "South Gate", "latitude": 13.0250, "longitude": 77.6050},
        ],
    },
]


def seed() -> None:
    ensure_schema(engine)

    with SessionLocal() as db:
        routes = []
        for item in DEMO_ROUTES:
            route = db.scalar(select(Route).where(Route.identifier == item["identifier"]))
            if route is None:
                route = Route(**item)
                db.add(route)
                db.flush()
            else:
                route.name = item["name"]
                route.start_point = item["start_point"]
                route.destination = item["destination"]
                route.color = item["color"]
                route.stops = item["stops"]
            routes.append(route)

        for number in range(1, 7):
            vehicle_id = f"IVTD_BUS_{number:02d}"
            registration = f"KA-04-HB-{1000 + number}"
            driver_email = f"driver{number:02d}@demo.invalid"
            driver = db.scalar(select(Driver).where(Driver.email == driver_email))
            if driver is None:
                driver = Driver(
                    name=f"Demo Driver {number:02d}",
                    email=driver_email,
                    phone=f"+91-90000-{10000 + number:05d}",
                    license_number=f"DEMO-LIC-{number:04d}",
                )
                db.add(driver)
                db.flush()
            else:
                driver.name = f"Demo Driver {number:02d}"
                driver.phone = f"+91-90000-{10000 + number:05d}"
                driver.license_number = f"DEMO-LIC-{number:04d}"
                driver.active = True

            bus = db.scalar(select(Bus).where(Bus.vehicle_id == vehicle_id))
            if bus is None:
                bus = Bus(
                    vehicle_id=vehicle_id,
                    registration_number=registration,
                    driver_name=driver.name,
                    driver_id=driver.id,
                    route_id=routes[0 if number <= 3 else 1].id,
                )
                db.add(bus)
                db.flush()
            else:
                bus.registration_number = registration
                bus.driver_name = driver.name
                bus.driver_id = driver.id
                bus.route_id = routes[0 if number <= 3 else 1].id
                bus.route_name = routes[0 if number <= 3 else 1].name

            device_id = f"IVTD_BUS_{number:02d}"
            device = db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == device_id))
            if device is None:
                db.add(
                    TrackingDevice(
                        device_id=device_id,
                        device_type="IVTD",
                        identifier_type="serial",
                        bus_id=bus.id,
                        # The demo fleet has no real hardware behind it; every
                        # frame for these IDs comes from the labelled simulator.
                        simulated=True,
                        active=True,
                    )
                )
            else:
                device.device_type = "IVTD"
                device.bus_id = bus.id
                device.simulated = True
                device.active = True

        if db.scalar(select(Geofence).where(Geofence.name == "Demo Campus Geofence")) is None:
            db.add(
                Geofence(
                    name="Demo Campus Geofence",
                    latitude=13.0405,
                    longitude=77.6200,
                    radius_m=800,
                    active=True,
                )
            )

        db.commit()


if __name__ == "__main__":
    seed()
    print("Database seed complete.")
    print("No user accounts or credentials were created.")
    print("Seeded demo buses/devices: IVTD_BUS_01-06, demo drivers, two demo routes, one demo geofence")
    print("No telemetry is fabricated by this script; start the simulator to produce labelled simulated fixes.")
