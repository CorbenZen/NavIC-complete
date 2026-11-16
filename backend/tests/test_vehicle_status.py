"""Boundary and API tests for centralized live vehicle status classification."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from navic_tcp import fastapi_app as api
from navic_tcp.db import Base
from navic_tcp.models import Bus, Driver, LocationHistory, TrackingDevice
from navic_tcp.vehicle_status import classify_vehicle_status

NOW = datetime.now(timezone.utc)


class VehicleStatusUnitTests(unittest.TestCase):
    def status(self, speed, ignition, seconds=30, stamp=True):
        return classify_vehicle_status(speed, ignition, NOW - timedelta(seconds=seconds) if stamp else None, now=NOW)

    def test_status_thresholds_and_priority(self):
        cases = [
            (25, True, 30, "ON_MOVE"),
            (2, True, 30, "STOPPED"),
            (0, False, 30, "IDLE"),
            (0, True, 301, "OUT_OF_NETWORK"),
            (8, False, 30, "TOING"),
            (5, False, 30, "IDLE"),
            (2.1, True, 30, "ON_MOVE"),
            (1, True, 300, "STOPPED"),
            (2.0001, True, 30, "ON_MOVE"),
            (2.0, True, 30, "STOPPED"),
            (5.0, False, 30, "IDLE"),
            (5.0001, False, 30, "TOING"),
        ]
        for speed, ignition, age, expected in cases:
            with self.subTest(speed=speed, ignition=ignition, age=age):
                self.assertEqual(self.status(speed, ignition, age).status, expected)
        self.assertEqual(self.status(0, False, stamp=False).status, "OUT_OF_NETWORK")

    def test_unknown_or_invalid_values_are_not_assumed_engine_off(self):
        moving = self.status(8, None)
        stationary = self.status(0, None)
        self.assertEqual(moving.status, "ON_MOVE")
        self.assertNotEqual(moving.status, "TOING")
        self.assertEqual(stationary.status, "STOPPED")
        self.assertFalse(stationary.ignition_available)
        self.assertEqual(stationary.reason, "stationary_ignition_unknown")
        self.assertEqual(self.status(None, False).status, "OUT_OF_NETWORK")
        self.assertEqual(self.status(-1, True).status, "OUT_OF_NETWORK")

    def test_invalid_and_far_future_timestamps_are_safe(self):
        self.assertEqual(classify_vehicle_status(10, True, "not-a-date", now=NOW).status, "OUT_OF_NETWORK")
        self.assertEqual(classify_vehicle_status(10, True, NOW + timedelta(seconds=121), now=NOW).status, "OUT_OF_NETWORK")
        self.assertEqual(classify_vehicle_status(10, True, NOW + timedelta(seconds=60), now=NOW).status, "ON_MOVE")

    def test_toing_transition_to_idle(self):
        self.assertEqual(self.status(8, False).status, "TOING")
        self.assertEqual(self.status(5, False).status, "IDLE")


class VehicleStatusApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.session_patch = patch.object(api, "SessionLocal", self.factory)
        self.session_patch.start()
        self.old_status_map = dict(api._last_vehicle_status)
        api._last_vehicle_status.clear()
        with self.factory() as db:
            driver = Driver(name="Actual Driver", email="driver@example.invalid", phone="555-0100", license_number="LIC-01")
            db.add(driver)
            db.flush()
            specs = [
                ("MOVE", 25, True, 30),
                ("STOP", 2, True, 30),
                ("IDLE", 0, False, 30),
                ("TOW", 8, False, 30),
                ("STALE", 8, True, 301),
            ]
            for index, (name, speed, ignition, age) in enumerate(specs):
                bus = Bus(vehicle_id=name, registration_number=f"REG-{name}", driver=driver if index == 0 else None)
                device = TrackingDevice(device_id=f"DEVICE-{name}", device_type="ELENA IVTS", identifier_type="imei", bus=bus)
                db.add(bus)
                db.flush()
                db.add(LocationHistory(
                    device_id=device.device_id,
                    message_id=f"00000000-0000-0000-0000-{index + 1:012d}",
                    timestamp=NOW - timedelta(seconds=age), received_at=NOW,
                    latitude=13.0 + index / 1000, longitude=77.0, speed=speed, course=0,
                    ignition=ignition, simulated=False, fix_valid=True,
                ))
            db.add(Bus(vehicle_id="NO-FIX", registration_number="REG-NO-FIX"))
            db.commit()

    def tearDown(self):
        api._last_vehicle_status.clear()
        api._last_vehicle_status.update(self.old_status_map)
        self.session_patch.stop()
        self.engine.dispose()

    def test_dashboard_stats_assign_every_bus_to_exactly_one_status(self):
        result = api.dashboard_stats({"role": "admin"})
        expected = {"all": 6, "on_move": 1, "stopped": 1, "idle": 1, "out_of_network": 2, "toing": 1}
        for key, value in expected.items():
            self.assertEqual(result[key], value)
        self.assertEqual(sum(result[key] for key in ("on_move", "stopped", "idle", "out_of_network", "toing")), result["all"])

    def test_vehicle_listing_has_actual_details_and_null_unavailable_fields(self):
        rows = api.buses({"role": "admin"})
        move = next(row for row in rows if row.registration_number == "REG-MOVE")
        self.assertEqual((move.vehicle_name, move.device_name, move.device_model, move.imei_no), ("MOVE", "DEVICE-MOVE", "ELENA IVTS", "DEVICE-MOVE"))
        self.assertEqual((move.driver_name, move.driver_phone, move.driver_email), ("Actual Driver", "555-0100", "driver@example.invalid"))
        self.assertEqual((move.status, move.status_key, move.ignition, move.latitude), ("On Move", "on_move", True, 13.0))
        self.assertIsNone(move.make)
        nofix = next(row for row in rows if row.registration_number == "REG-NO-FIX")
        self.assertEqual(nofix.status_key, "out_of_network")
        self.assertIsNone(nofix.imei_no)
        self.assertIsNone(nofix.latitude)

    def test_periodic_evaluator_broadcasts_fresh_to_out_of_network_transition(self):
        api._last_vehicle_status["DEVICE-MOVE"] = "ON_MOVE"
        with patch.object(api.hub, "publish", new=AsyncMock()) as publish:
            emitted = asyncio.run(api.evaluate_vehicle_status_transitions(now=NOW + timedelta(seconds=301)))
        self.assertGreaterEqual(emitted, 1)
        events = [call.args[0] for call in publish.await_args_list]
        transition = next(event for event in events if event["device_id"] == "DEVICE-MOVE")
        self.assertEqual((transition["type"], transition["status"]), ("vehicle_status", "OUT_OF_NETWORK"))


if __name__ == "__main__":
    unittest.main()
