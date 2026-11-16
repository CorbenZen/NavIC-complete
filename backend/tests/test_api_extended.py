"""Extended REST/dashboard/report regression tests for the management API."""

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from navic_tcp import fastapi_app as api
from navic_tcp.db import Base
from navic_tcp.models import (
    Alert,
    AuditLog,
    Bus,
    Driver,
    LocationHistory,
    Route,
    SystemSetting,
    TrackingDevice,
)


class ExtendedApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.patch = patch.object(api, "SessionLocal", self.factory)
        self.patch.start()
        with self.factory() as db:
            driver = Driver(name="Test Driver", email="driver@example.invalid", license_number="TEST-LIC")
            route = Route(name="North Route", identifier="NORTH", start_point="Campus", destination="Gate")
            bus = Bus(vehicle_id="TEST-01", registration_number="TEST-01", driver=driver, route=route)
            device = TrackingDevice(device_id="TEST_DEVICE", bus=bus, simulated=False)
            db.add_all([driver, route, bus, device])
            db.flush()
            start = datetime.now(timezone.utc) - timedelta(minutes=4)
            db.add_all(
                [
                    LocationHistory(
                        device_id=device.device_id,
                        message_id="00000000-0000-0000-0000-000000000001",
                        timestamp=start,
                        latitude=13.0,
                        longitude=77.6,
                        speed=0,
                        course=0,
                        simulated=True,
                        ignition=True,
                        odometer=100.0,
                    ),
                    LocationHistory(
                        device_id=device.device_id,
                        message_id="00000000-0000-0000-0000-000000000002",
                        timestamp=start + timedelta(minutes=2),
                        latitude=13.001,
                        longitude=77.601,
                        speed=24,
                        course=90,
                        simulated=True,
                        ignition=True,
                        odometer=101.0,
                        gnss_metadata={"fix_valid": True, "constellations": ["gps", "navic"]},
                    ),
                ]
            )
            db.add(Alert(event_type="overspeed", message="test alert", device_id=device.device_id))
            db.add(SystemSetting(key="overspeed_kmh", value="60"))
            db.commit()

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()

    def test_tracking_latest_reports_fix_provenance_separately_from_device_registry(self):
        result = api.tracking_latest({"role": "admin"})
        row = next(item for item in result["vehicles"] if item["device_id"] == "TEST_DEVICE")
        self.assertTrue(row["simulated"])
        self.assertFalse(row["device_simulated"])
        self.assertEqual(row["route_name"], "North Route")
        self.assertEqual(row["driver_name"], "Test Driver")

    def test_summary_is_derived_from_persisted_telemetry(self):
        summary = api.dashboard_summary({"role": "admin"})
        self.assertEqual(summary["fleet"]["total"], 1)
        self.assertEqual(summary["fleet"]["moving"], 1)
        self.assertEqual(summary["simulation"]["simulated_fixes"], 1)
        self.assertEqual(summary["simulation"]["simulated_devices"], 1)
        self.assertEqual(summary["devices"]["total"], 1)
        self.assertEqual(summary["recent"][0]["vehicle_id"], "TEST-01")
        self.assertTrue(summary["recent"][0]["simulated"])

    def test_admin_dashboard_summary_is_counts_only_and_admin_guarded(self):
        summary = api.dashboard_admin_summary({"role": "admin"})
        self.assertEqual({"attention", "hygiene"}, set(summary))
        self.assertTrue(all(set(row) == {"key", "count", "target"} for group in summary.values() for row in group))
        self.assertTrue(all(isinstance(row["count"], int) for group in summary.values() for row in group))
        with self.assertRaises(HTTPException) as denied:
            api.admin_user({"role": "student"})
        self.assertEqual(denied.exception.status_code, 403)
        route = next(route for route in api.app.routes if getattr(route, "path", None) == "/api/dashboard/admin-summary")
        self.assertIs(route.dependant.dependencies[0].call, api.admin_user)

    def test_device_latest_telemetry_exposes_gnss_but_not_a_navic_capability_claim(self):
        result = api.device_telemetry_latest("TEST_DEVICE", {"role": "admin"})
        self.assertEqual(result["latest"]["gnss"]["constellations"], ["gps", "navic"])
        self.assertEqual(result["gnss_compatibility"]["navic"], "unsupported_or_unverified")
        self.assertEqual(result["identity"]["device_id"], "TEST_DEVICE")

    def test_dashboard_stats_remain_flattened_and_consistent(self):
        stats = api.dashboard_stats({"role": "admin"})
        self.assertEqual(stats["all"], 1)
        self.assertEqual(stats["on_move"], 1)
        self.assertEqual(stats["total_devices"], 1)
        self.assertEqual(stats["simulated_devices"], 1)

    def test_reports_and_csv_export_use_persisted_rows(self):
        report = api.report_data("km", limit=10, offset=0)
        self.assertEqual(report["data"][0]["records"], 2)
        response = api.export_report_csv("history")
        self.assertTrue(response.media_type.startswith("text/csv"))
        body = response.body.decode("utf-8")
        self.assertIn("device_id", body)
        self.assertIn("TEST_DEVICE", body)

    def test_bus_history_returns_playback_points_in_time_order(self):
        with self.factory() as db:
            bus_id = db.scalar(select(Bus.id))
        result = api.bus_history(bus_id, None, None, 100, {"role": "admin"})
        self.assertEqual(len(result["history"]), 2)
        self.assertEqual(result["summary"]["point_count"], 2)
        self.assertEqual(result["device_id"], "TEST_DEVICE")

    def test_settings_round_trip_and_audit(self):
        updated = api.update_settings(
            api.SettingIn(overspeed_kmh=72, device_offline_minutes=15), {"username": "admin", "role": "admin"}
        )
        self.assertEqual(updated["overspeed_kmh"], 72)
        self.assertEqual(updated["device_offline_minutes"], 15)
        with self.factory() as db:
            self.assertEqual(db.get(SystemSetting, "device_offline_minutes").value, "15.0")
            self.assertIsNotNone(db.scalar(select(AuditLog).where(AuditLog.entity == "settings")))

    def test_mark_all_alerts_read(self):
        result = api.mark_all_alerts_read({"username": "admin", "role": "admin"})
        self.assertGreaterEqual(result["updated"], 1)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(Alert).where(Alert.is_read.is_(False))), None)

    def test_management_audit_trail_records_mutations(self):
        api.create_bus(
            api.BusIn(vehicle_id="AUDIT-01", registration_number="AUDIT-01"), {"username": "admin", "role": "admin"}
        )
        trail = api.audit_log(limit=50, offset=0, user={"role": "admin"})
        self.assertTrue(any(item["action"] == "create" and item["entity"] == "vehicle" for item in trail["audit"]))

    def test_device_with_history_cannot_be_deleted(self):
        with self.factory() as db:
            device_pk = db.scalar(select(TrackingDevice.id))
        with self.assertRaises(HTTPException) as blocked:
            api.delete_device(device_pk, {"role": "admin"})
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertIn("deactivate", blocked.exception.detail)

    def test_assigned_driver_cannot_be_deleted(self):
        delete_driver = next(
            route.endpoint
            for route in api.app.routes
            if getattr(route, "path", None) == "/drivers/{item_id}" and "DELETE" in getattr(route, "methods", set())
        )
        with self.factory() as db:
            driver_id = db.scalar(select(Driver.id))
        with self.assertRaises(HTTPException) as blocked:
            delete_driver(driver_id, {"role": "admin"})
        self.assertEqual(blocked.exception.status_code, 409)
        self.assertIn("assigned", blocked.exception.detail)

    def test_unknown_device_telemetry_is_ignored(self):
        async def run():
            message = {
                "device_id": "UNKNOWN_DEVICE",
                "message_id": "00000000-0000-0000-0000-000000000099",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "latitude": 13.1,
                "longitude": 77.6,
                "speed": 14,
                "course": 45,
                "simulated": True,
            }
            await api.on_telemetry(message)

        asyncio.run(run())
        with self.factory() as db:
            self.assertIsNone(
                db.scalar(
                    select(LocationHistory).where(
                        LocationHistory.message_id == "00000000-0000-0000-0000-000000000099"
                    )
                )
            )

    def test_duplicate_telemetry_message_is_not_persisted_twice(self):
        async def run():
            message = {
                "device_id": "TEST_DEVICE",
                "message_id": "00000000-0000-0000-0000-000000000002",
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "latitude": 13.1,
                "longitude": 77.6,
                "speed": 14,
                "course": 45,
                "simulated": True,
            }
            await api.on_telemetry(message)

        asyncio.run(run())
        with self.factory() as db:
            count = db.query(LocationHistory).filter(
                LocationHistory.message_id == "00000000-0000-0000-0000-000000000002"
            ).count()
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
