"""Tests for the roadmap features that live in the API layer.

Covers alert incidents, geofence incidents, public share links, observed GNSS
constellations and explicit telemetry provenance (``data_source``).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request
from starlette.responses import Response

from navic_tcp import fastapi_app as api
from navic_tcp.db import Base
from navic_tcp.models import (
    Alert,
    AlertIncident,
    Bus,
    DeviceGeofenceState,
    Geofence,
    GeofenceIncident,
    LocationHistory,
    ShareToken,
    TrackingDevice,
    User,
)
from navic_tcp.protocol import MessageError, decode_telemetry


def make_point(device_id, message_id, timestamp, *, simulated=True, gnss=None, data_source=None):
    """Build a complete LocationHistory row for tests."""
    return LocationHistory(
        device_id=device_id,
        message_id=message_id,
        timestamp=timestamp,
        latitude=13.0,
        longitude=80.0,
        speed=0,
        course=0,
        simulated=simulated,
        data_source=data_source or ("simulator" if simulated else "hardware"),
        gnss_metadata=gnss,
    )


def make_request():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/public/bus/test",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 43210),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


class Phase2Phase3Tests(unittest.TestCase):
    """Base test class with an isolated in-memory database."""

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.patch = patch.object(api, "SessionLocal", self.factory)
        self.patch.start()

        with self.factory() as db:
            user = User(username="testuser", role="admin", email="test@example.com")
            user.password_hash = "test"
            db.add(user)
            db.commit()
            self.user_id = user.id

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()

    def create_bus_with_device(self, device_id, bus_id, simulated=True):
        with self.factory() as db:
            bus = Bus(vehicle_id=bus_id, registration_number=f"REG-{bus_id}")
            db.add(bus)
            db.flush()

            device = TrackingDevice(device_id=device_id, bus_id=bus.id, simulated=simulated, active=True)
            db.add(device)
            db.commit()
            return bus, device


class TestAlertIncidents(Phase2Phase3Tests):
    """Alert incidents group an outage instead of creating one alert per check."""

    def test_create_offline_alerts_creates_incidents(self):
        with self.factory() as db:
            db.add(TrackingDevice(device_id="TEST_INCIDENT_DEVICE", simulated=True, active=True))
            now = datetime.now(timezone.utc)
            db.add(make_point("TEST_INCIDENT_DEVICE", "test-msg-1", now - timedelta(minutes=10)))
            db.commit()

            created = api.create_offline_alerts(db, now=now)
            self.assertEqual(created, 1)

            incident = db.scalar(select(AlertIncident).where(AlertIncident.device_id == "TEST_INCIDENT_DEVICE"))
            self.assertIsNotNone(incident)
            self.assertEqual(incident.state, "open")
            self.assertEqual(incident.alert_count, 1)

            alert = db.scalar(select(Alert).where(Alert.incident_id == incident.id))
            self.assertIsNotNone(alert)
            self.assertEqual(alert.event_type, "device_offline")

    def test_incident_grouping_with_cooldown(self):
        with self.factory() as db:
            db.add(TrackingDevice(device_id="TEST_INCIDENT_DEVICE_2", simulated=True, active=True))
            now = datetime.now(timezone.utc)
            db.add(make_point("TEST_INCIDENT_DEVICE_2", "test-msg-2", now - timedelta(minutes=10)))
            db.commit()

            self.assertEqual(api.create_offline_alerts(db, now=now), 1)
            self.assertEqual(api.create_offline_alerts(db, now=now + timedelta(minutes=10)), 0)

            incident = db.scalar(select(AlertIncident).where(AlertIncident.device_id == "TEST_INCIDENT_DEVICE_2"))
            self.assertEqual(incident.alert_count, 1)

    def test_incident_resolves_when_telemetry_resumes(self):
        with self.factory() as db:
            db.add(TrackingDevice(device_id="TEST_INCIDENT_DEVICE_3", simulated=True, active=True))
            now = datetime.now(timezone.utc)
            db.add(make_point("TEST_INCIDENT_DEVICE_3", "test-msg-3", now - timedelta(minutes=10)))
            db.commit()

            api.create_offline_alerts(db, now=now)
            incident = db.scalar(select(AlertIncident).where(AlertIncident.device_id == "TEST_INCIDENT_DEVICE_3"))
            self.assertEqual(incident.state, "open")

            db.add(make_point("TEST_INCIDENT_DEVICE_3", "test-msg-4", now, simulated=False))
            db.commit()
            api.create_offline_alerts(db, now=now + timedelta(minutes=1))

            incident = db.scalar(select(AlertIncident).where(AlertIncident.device_id == "TEST_INCIDENT_DEVICE_3"))
            self.assertEqual(incident.state, "resolved")
            self.assertIsNotNone(incident.resolved_at)


class TestShareTokenUtilities(Phase2Phase3Tests):
    def test_hash_token_deterministic(self):
        token = "test-token-123"
        hash1 = api._hash_token(token)
        hash2 = api._hash_token(token)
        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA-256 hex

    def test_generate_token_unique(self):
        tokens = set()
        for _ in range(100):
            token = api._generate_token()
            self.assertNotIn(token, tokens)
            tokens.add(token)
            self.assertGreater(len(token), 20)  # URL-safe base64

    def test_humanize_ago(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(api._humanize_ago(now), "just now")
        self.assertEqual(api._humanize_ago(now - timedelta(seconds=30)), "just now")
        self.assertEqual(api._humanize_ago(now - timedelta(minutes=5)), "5 min ago")
        self.assertEqual(api._humanize_ago(now - timedelta(hours=2)), "2 hr ago")
        self.assertEqual(api._humanize_ago(now - timedelta(days=3)), "3 day ago")
        self.assertEqual(api._humanize_ago(None), "never")


class TestShareTokenLifecycle(Phase2Phase3Tests):
    """Create -> public read -> revoke -> gone, without leaking private fields."""

    def _create(self, bus_id, name="Test Share"):
        return api.create_share_token(
            bus_id,
            api.ShareTokenCreate(name=name),
            user={"id": self.user_id, "username": "testuser", "role": "admin"},
        )

    def test_create_stores_only_a_hash(self):
        bus, _device = self.create_bus_with_device("SHARE_DEVICE", "SHARE_BUS", simulated=False)
        created = self._create(bus.id)
        with self.factory() as db:
            stored = db.scalar(select(ShareToken).where(ShareToken.id == created["id"]))
            self.assertIsNotNone(stored)
            self.assertEqual(stored.token_hash, api._hash_token(created["token"]))
            self.assertNotEqual(stored.token_hash, created["token"])

    def test_public_payload_is_minimal(self):
        bus, device = self.create_bus_with_device("SHARE_DEVICE_2", "SHARE_BUS_2", simulated=True)
        with self.factory() as db:
            db.add(make_point("SHARE_DEVICE_2", "share-msg-1", datetime.now(timezone.utc)))
            db.commit()

        created = self._create(bus.id)
        response = Response()
        payload = api.public_bus_page(created["token"], make_request(), response)

        self.assertEqual(payload["registration_number"], bus.registration_number)
        self.assertEqual(payload["source"], "simulator")
        self.assertEqual(payload["source_badge"], "Simulated")
        self.assertIsNotNone(payload["position"])
        for forbidden in ("driver_name", "driver_phone", "driver_email", "device_id", "imei", "token", "id", "bus_id"):
            self.assertNotIn(forbidden, payload)
        # Public responses must not be cached or indexed.
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("noindex", response.headers["X-Robots-Tag"])
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_revoked_token_returns_410(self):
        bus, _device = self.create_bus_with_device("SHARE_DEVICE_3", "SHARE_BUS_3", simulated=False)
        created = self._create(bus.id)

        api.revoke_share_token(bus.id, created["id"], user={"id": self.user_id, "role": "admin"})
        with self.assertRaises(api.HTTPException) as raised:
            api.public_bus_page(created["token"], make_request(), Response())
        self.assertEqual(raised.exception.status_code, 410)

    def test_revoke_twice_is_rejected(self):
        bus, _device = self.create_bus_with_device("SHARE_DEVICE_4", "SHARE_BUS_4", simulated=False)
        created = self._create(bus.id)
        user = {"id": self.user_id, "role": "admin"}
        api.revoke_share_token(bus.id, created["id"], user=user)
        with self.assertRaises(api.HTTPException) as raised:
            api.revoke_share_token(bus.id, created["id"], user=user)
        self.assertEqual(raised.exception.status_code, 400)

    def test_unknown_token_is_404(self):
        with self.assertRaises(api.HTTPException) as raised:
            api.public_bus_page("not-a-real-token", make_request(), Response())
        self.assertEqual(raised.exception.status_code, 404)

    def test_expired_token_returns_410(self):
        bus, _device = self.create_bus_with_device("SHARE_DEVICE_5", "SHARE_BUS_5", simulated=False)
        created = self._create(bus.id)
        with self.factory() as db:
            stored = db.get(ShareToken, created["id"])
            stored.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()
        with self.assertRaises(api.HTTPException) as raised:
            api.public_bus_page(created["token"], make_request(), Response())
        self.assertEqual(raised.exception.status_code, 410)


class TestGNSSObservedConstellations(Phase2Phase3Tests):
    def test_observed_constellations_excludes_simulator(self):
        with self.factory() as db:
            db.add(TrackingDevice(device_id="GNSS_TEST_DEVICE", simulated=True, active=True))
            now = datetime.now(timezone.utc)

            db.add(
                make_point(
                    "GNSS_TEST_DEVICE",
                    "gnss-sim-1",
                    now - timedelta(hours=1),
                    simulated=True,
                    gnss={"constellations": ["gps", "glonass"], "satellites": [{"constellation": "gps", "satellite_id": 1}]},
                )
            )
            db.add(
                make_point(
                    "GNSS_TEST_DEVICE",
                    "gnss-hw-1",
                    now,
                    simulated=False,
                    gnss={"constellations": ["gps", "navic"], "satellites": [{"constellation": "navic", "satellite_id": 1}]},
                )
            )
            db.commit()

            result = api.device_observed_constellations("GNSS_TEST_DEVICE", limit=100, user=None)
            self.assertEqual(result["hardware_fixes"], 1)
            self.assertEqual(result["simulator_fixes"], 1)

            constellations = {item["constellation"] for item in result["constellations"]}
            self.assertIn("NavIC", constellations)
            self.assertIn("GPS", constellations)
            self.assertNotIn("GLONASS", constellations)


class TestGeofenceIncidents(Phase2Phase3Tests):
    def test_geofence_state_tracks_hysteresis_counters(self):
        with self.factory() as db:
            fence = Geofence(name="Test Fence", latitude=13.0, longitude=80.0, radius_m=100, active=True)
            db.add(fence)
            db.flush()
            db.add(TrackingDevice(device_id="GEO_TEST_DEVICE", simulated=True, active=True))
            db.add(
                DeviceGeofenceState(
                    device_id="GEO_TEST_DEVICE",
                    geofence_id=fence.id,
                    inside=False,
                    consecutive_inside=0,
                    consecutive_outside=1,
                )
            )
            db.commit()

            state = db.get(DeviceGeofenceState, ("GEO_TEST_DEVICE", fence.id))
            self.assertEqual(state.consecutive_outside, 1)
            self.assertEqual(state.consecutive_inside, 0)
            self.assertFalse(state.inside)

    def test_incident_list_resolves_vehicle(self):
        """Regression: incidents used db.get(TrackingDevice, device_id_string)."""
        bus, _device = self.create_bus_with_device("GEO_INCIDENT_DEVICE", "GEO_INCIDENT_BUS", simulated=True)
        with self.factory() as db:
            fence = Geofence(name="Fence", latitude=13.0, longitude=80.0, radius_m=100, active=True)
            db.add(fence)
            db.flush()
            incident = GeofenceIncident(
                device_id="GEO_INCIDENT_DEVICE",
                geofence_id=fence.id,
                state="inside",
                transitioned_at=datetime.now(timezone.utc),
            )
            db.add(incident)
            db.commit()
            incident_id = incident.id

        result = api.list_geofence_incidents(
            state=None, device_id=None, geofence_id=None, unread_only=False, limit=100, offset=0, user=None
        )
        rows = [row for row in result["incidents"] if row["id"] == incident_id]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["geofence_name"], "Fence")
        self.assertEqual(rows[0]["vehicle_reg"], bus.registration_number)
        self.assertFalse(rows[0]["is_read"])
        self.assertIsNotNone(rows[0]["created_at"])

    def test_mark_incident_read(self):
        with self.factory() as db:
            fence = Geofence(name="Fence 2", latitude=13.0, longitude=80.0, radius_m=100, active=True)
            db.add(fence)
            db.flush()
            incident = GeofenceIncident(
                device_id="GEO_READ_DEVICE",
                geofence_id=fence.id,
                state="inside",
                transitioned_at=datetime.now(timezone.utc),
            )
            db.add(incident)
            db.commit()
            incident_id = incident.id

        api.mark_geofence_incident_read(incident_id, user={"username": "testuser", "role": "admin"})
        with self.factory() as db:
            self.assertTrue(db.get(GeofenceIncident, incident_id).is_read)


class TestTelemetryProvenance(Phase2Phase3Tests):
    """``data_source`` is explicit, validated and never inferred from names."""

    def _message(self, **overrides):
        base = {
            "protocol_version": 1,
            "type": "telemetry",
            "message_id": "4f8a3c1e-6b1e-4c1a-9a1e-5b2c3d4e5f60",
            "device_id": "IVTD_TEST_001",
            "timestamp": "2026-11-15T10:00:00Z",
            "latitude": 13.0,
            "longitude": 80.0,
            "speed": 10,
            "course": 90,
            "ignition": True,
            "simulated": False,
        }
        base.update(overrides)
        import json

        return json.dumps(base).encode()

    def test_simulated_flag_derives_source(self):
        message = decode_telemetry(self._message(simulated=True))
        self.assertEqual(message["data_source"], "simulator")

    def test_hardware_flag_derives_source(self):
        message = decode_telemetry(self._message())
        self.assertEqual(message["data_source"], "hardware")

    def test_explicit_test_replay_is_kept(self):
        message = decode_telemetry(self._message(simulated=True, data_source="test_replay"))
        self.assertEqual(message["data_source"], "test_replay")

    def test_contradictory_source_is_rejected(self):
        with self.assertRaises(MessageError):
            decode_telemetry(self._message(simulated=False, data_source="simulator"))

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(MessageError):
            decode_telemetry(self._message(simulated=False, data_source="made_up"))

    def test_bus_response_exposes_source(self):
        bus, _device = self.create_bus_with_device("PROV_DEVICE", "PROV_BUS", simulated=True)
        with self.factory() as db:
            db.add(make_point("PROV_DEVICE", "prov-msg-1", datetime.now(timezone.utc)))
            db.commit()
            response = api.bus_response(db, db.get(Bus, bus.id))
            self.assertEqual(response.data_source, "simulator")
            self.assertTrue(response.simulated)


class TestVersionedMigrations(Phase2Phase3Tests):
    """Schema changes live in Alembic revisions, not ad-hoc scripts."""

    def test_roadmap_revision_exists(self):
        from pathlib import Path

        versions = Path("backend/python_sqlalchemy/migrations/versions")
        names = {path.name for path in versions.glob("*.py")}
        self.assertIn("0007_roadmap_tables.py", names)

    def test_new_models_are_shared(self):
        from backend.python_sqlalchemy.models import AlertIncident as BackendAlertIncident
        from backend.python_sqlalchemy.models import GeofenceIncident as BackendGeofenceIncident
        from backend.python_sqlalchemy.models import ShareToken as BackendShareToken

        self.assertIs(BackendAlertIncident, AlertIncident)
        self.assertIs(BackendGeofenceIncident, GeofenceIncident)
        self.assertIs(BackendShareToken, ShareToken)


if __name__ == "__main__":
    unittest.main()
