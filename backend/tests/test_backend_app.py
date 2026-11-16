"""Tests for the modular website backend (``backend.python_fastapi.application``).

These tests exercise the composition layer that serves the NavIC website: the
route surface, application lifecycle, database access and service functions.
The domain implementation itself is covered by the neighbouring test modules.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# The lifespan refuses to start outside development without an explicit JWT
# secret.  Set the development defaults before the shared app is imported.
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("TCP_ENABLED", "false")

from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient
from starlette.routing import Mount

from backend.python_fastapi.application.core import config as backend_config
from backend.python_fastapi.application.main import app
from backend.python_services.telemetry_service import (
    history_for_device,
    latest_points,
    point_count,
)
from backend.python_sqlalchemy.database import connection as backend_connection
from navic_tcp import fastapi_app as shared
from navic_tcp.db import Base
from navic_tcp.models import Bus, LocationHistory
from navic_tcp.protocol import MessageError

_CLIENT: TestClient | None = None
_ORIGINAL_DEVELOPMENT_MODE = shared.DEVELOPMENT_MODE
_ORIGINAL_BYPASS = shared.DEMO_AUTH_BYPASS
_ORIGINAL_APP_ENV = shared.APP_ENV


def _flatten(routes):
    """Flatten APIRoutes, WebSocket routes, mounts and included routers."""
    flattened = []
    for route in routes:
        if isinstance(route, (APIRoute, APIWebSocketRoute)):
            flattened.append(
                (
                    route.path,
                    tuple(sorted(getattr(route, "methods", None) or ())),
                    route.name,
                )
            )
        elif isinstance(route, Mount):
            flattened.append((route.path, ("MOUNT",), route.name))
        elif type(route).__name__ == "_IncludedRouter":
            flattened.extend(_flatten(route.original_router.routes))
    return flattened


def setUpModule():
    global _CLIENT, _ORIGINAL_BYPASS
    # Discovery may import ``navic_tcp.fastapi_app`` before this module.  The
    # shared app then captured APP_ENV from the repository .env, which does not
    # set it, so force the development lifecycle for the test session.
    shared.DEVELOPMENT_MODE = True
    shared.APP_ENV = "development"
    os.environ["TCP_ENABLED"] = "false"
    _ORIGINAL_BYPASS = shared.DEMO_AUTH_BYPASS
    shared.DEMO_AUTH_BYPASS = True
    _CLIENT = TestClient(app)
    _CLIENT.__enter__()


def tearDownModule():
    global _CLIENT
    if _CLIENT is not None:
        _CLIENT.__exit__(None, None, None)
        _CLIENT = None
    shared.DEVELOPMENT_MODE = _ORIGINAL_DEVELOPMENT_MODE
    shared.APP_ENV = _ORIGINAL_APP_ENV
    shared.DEMO_AUTH_BYPASS = _ORIGINAL_BYPASS


class InMemoryDatabaseMixin:
    """Provide an isolated database for service-level CRUD tests."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.db = self.factory()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()


class ApplicationCompositionTests(unittest.TestCase):
    def test_every_shared_route_is_registered(self):
        source = set(_flatten(shared.app.routes))
        modular = set(_flatten(app.routes))
        self.assertEqual(source - modular, set(), "routes missing from backend.python_fastapi.application")
        self.assertEqual(
            {(path, methods) for path, methods, _name in modular - source},
            {
                ("/auth/verify-email", ("POST",)),
                ("/auth/register", ("POST",)),
                ("/auth/resend-verification", ("POST",)),
                ("/auth/verification-status", ("GET",)),
                ("/api/auth/register", ("POST",)),
                ("/api/auth/login", ("POST",)),
                ("/api/auth/verify-email", ("POST",)),
                ("/api/auth/resend-verification", ("POST",)),
                ("/api/auth/verification-status", ("GET",)),
                ("/api/auth/logout", ("POST",)),
                ("/api/auth/me", ("GET",)),
                ("/auth/login/id", ("POST",)),
            },
            "unexpected routes in backend.python_fastapi.application",
        )
        self.assertGreaterEqual(len(modular), 80)

    def test_middleware_and_exception_handlers_are_preserved(self):
        source = [middleware.cls for middleware in shared.app.user_middleware]
        modular = [middleware.cls for middleware in app.user_middleware]
        self.assertEqual(source, modular)
        for handler in shared.app.exception_handlers:
            self.assertIn(handler, app.exception_handlers)

    def test_openapi_document_covers_domain_groups(self):
        response = _CLIENT.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        for path in ("/auth/login", "/buses", "/devices", "/alerts", "/health"):
            self.assertIn(path, paths)
        self.assertGreaterEqual(len(paths), 40)


class HealthAndStaticTests(unittest.TestCase):
    def test_health_reports_database_and_environment(self):
        response = _CLIENT.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "ok")
        self.assertEqual(payload["environment"], "development")
        self.assertEqual(payload["tcp"], "disabled")

    def test_swagger_ui_is_served(self):
        response = _CLIENT.get("/docs")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])

    def test_static_asset_is_served(self):
        response = _CLIENT.get("/logo.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")

    def test_spa_fallback_returns_index_html(self):
        response = _CLIENT.get("/devices", headers={"Accept": "text/html"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])


class AuthenticationAndValidationTests(unittest.TestCase):
    def test_password_hashing_round_trip(self):
        from backend.python_fastapi.application.core.security import (
            hash_password,
            password_needs_rehash,
            verify_password,
        )

        encoded = hash_password("correct horse battery staple")
        self.assertNotIn("correct horse battery staple", encoded)
        self.assertTrue(verify_password("correct horse battery staple", encoded))
        self.assertFalse(verify_password("wrong password", encoded))
        self.assertFalse(password_needs_rehash(encoded))

    def test_access_token_round_trip_and_tampering(self):
        from backend.python_fastapi.application.core.security import (
            issue_access_token,
            verify_access_token,
        )

        token = issue_access_token("fleet-admin", ttl_seconds=120)
        claims = verify_access_token(token)
        self.assertEqual(claims["sub"], "fleet-admin")
        with self.assertRaises(ValueError):
            verify_access_token(token + "x")

    def test_protected_route_rejects_anonymous_requests(self):
        shared.DEMO_AUTH_BYPASS = False
        try:
            response = _CLIENT.get("/buses")
        finally:
            shared.DEMO_AUTH_BYPASS = True
        self.assertEqual(response.status_code, 401)
        self.assertTrue(response.headers.get("www-authenticate", "").startswith("Bearer"))

    def test_invalid_login_payload_is_rejected(self):
        response = _CLIENT.post("/auth/login", json={})
        self.assertEqual(response.status_code, 422)
        self.assertIn("detail", response.json())

    def test_invalid_fleet_payload_is_rejected(self):
        response = _CLIENT.post("/buses", json={"registration_number": "X"})
        self.assertEqual(response.status_code, 422)


class FleetEndpointTests(unittest.TestCase):
    def test_fleet_collections_are_served(self):
        for path in ("/buses", "/drivers", "/routes", "/geofences"):
            with self.subTest(path=path):
                response = _CLIENT.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIsInstance(response.json(), list)

    def test_device_inventory_is_served(self):
        response = _CLIENT.get("/devices")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, dict)
        self.assertIsInstance(payload["devices"], list)

    def test_telemetry_and_dashboard_reads_are_served(self):
        for path in ("/api/tracking/latest", "/api/dashboard/summary"):
            with self.subTest(path=path):
                response = _CLIENT.get(path)
                self.assertEqual(response.status_code, 200)

    def test_alerts_collection_is_served(self):
        response = _CLIENT.get("/alerts")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(isinstance(payload, (list, dict)))


class FleetServiceCrudTests(InMemoryDatabaseMixin, unittest.TestCase):
    def test_create_read_update_delete_cycle(self):
        from backend.python_services import fleet_service

        bus = fleet_service.create_record(
            self.db,
            Bus,
            vehicle_id="TEST-CRUD-01",
            registration_number="KA01TEST0001",
        )
        self.assertIsNotNone(bus.id)
        self.assertEqual([row.id for row in fleet_service.list_buses(self.db)], [bus.id])
        self.assertEqual(fleet_service.get_bus(self.db, bus.id).vehicle_id, "TEST-CRUD-01")

        updated = fleet_service.update_record(
            self.db, Bus, bus.id, driver_name="Test Driver"
        )
        self.assertEqual(updated.driver_name, "Test Driver")

        counts = fleet_service.fleet_counts(self.db)
        self.assertEqual(counts["vehicles"], 1)
        self.assertEqual(counts["drivers"], 0)

        self.assertTrue(fleet_service.delete_record(self.db, Bus, bus.id))
        self.assertIsNone(fleet_service.get_bus(self.db, bus.id))
        self.assertFalse(fleet_service.delete_record(self.db, Bus, bus.id))

    def test_duplicate_vehicle_rolls_back_without_corrupting_session(self):
        from backend.python_services import fleet_service

        fleet_service.create_record(
            self.db, Bus, vehicle_id="TEST-DUP-01", registration_number="KA01DUP0001"
        )
        with self.assertRaises(IntegrityError):
            fleet_service.create_record(
                self.db, Bus, vehicle_id="TEST-DUP-01", registration_number="KA01DUP0002"
            )
        self.assertEqual(len(fleet_service.list_buses(self.db)), 1)

    def test_database_connectivity_helper(self):
        self.assertTrue(backend_connection.database_reachable(self.engine))
        self.assertIs(backend_connection.init_database(self.engine), self.engine)


class TelemetryServiceTests(InMemoryDatabaseMixin, unittest.TestCase):
    def _frame(self) -> dict:
        return {
            "protocol_version": 1,
            "type": "telemetry",
            "message_id": str(uuid4()),
            "device_id": "TEST-DEVICE-1",
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "latitude": 12.9716,
            "longitude": 77.5946,
            "speed": 24.5,
            "course": 90.0,
            "ignition": True,
            "simulated": True,
        }

    def test_valid_frame_is_decoded_and_acknowledged(self):
        from backend.python_services import telemetry_service

        frame = self._frame()
        decoded = telemetry_service.decode_frame(
            telemetry_service.encode_message(frame)
        )
        self.assertEqual(decoded["device_id"], "TEST-DEVICE-1")
        self.assertAlmostEqual(decoded["latitude"], 12.9716)

        ack = telemetry_service.encode_ack(decoded["message_id"])
        self.assertTrue(ack.endswith(b"\n"))
        self.assertIn(b'"type":"ack"', ack)

    def test_invalid_frame_is_rejected(self):
        from backend.python_services import telemetry_service

        broken = self._frame()
        broken.pop("latitude")
        with self.assertRaises(MessageError) as context:
            telemetry_service.decode_frame(telemetry_service.encode_message(broken))
        self.assertEqual(context.exception.code, "missing_fields")

    def test_latest_points_and_device_history(self):
        now = datetime.now(timezone.utc)
        self.db.add_all(
            [
                LocationHistory(
                    device_id="TEST-DEVICE-1",
                    message_id=str(uuid4()),
                    timestamp=now - timedelta(minutes=2),
                    latitude=12.9,
                    longitude=77.5,
                    speed=10.0,
                    course=0.0,
                    simulated=True,
                ),
                LocationHistory(
                    device_id="TEST-DEVICE-1",
                    message_id=str(uuid4()),
                    timestamp=now,
                    latitude=12.91,
                    longitude=77.51,
                    speed=15.0,
                    course=45.0,
                    simulated=True,
                ),
            ]
        )
        self.db.commit()

        latest = latest_points(self.db, limit=10)
        self.assertEqual(len(latest), 2)
        self.assertAlmostEqual(latest[0].latitude, 12.91)
        self.assertEqual(len(history_for_device(self.db, "TEST-DEVICE-1")), 2)
        self.assertEqual(point_count(self.db, "TEST-DEVICE-1"), 2)
        self.assertEqual(point_count(self.db, "UNKNOWN"), 0)


class WebSocketTests(unittest.TestCase):
    def test_ping_pong_round_trip(self):
        with _CLIENT.websocket_connect("/ws/locations") as websocket:
            websocket.send_text("ping")
            message = websocket.receive_json()
        self.assertEqual(message.get("type"), "pong")


class TCPBridgeTests(unittest.TestCase):
    def test_bridge_sends_a_validated_frame_to_a_tcp_server(self):
        import asyncio

        from backend.python_asyncio.tcp.tcp_receiver import TCPTelemetryBridge
        from navic_tcp.protocol import acknowledgement, decode_telemetry, encode_message

        frame = {
            "protocol_version": 1,
            "type": "telemetry",
            "message_id": str(uuid4()),
            "device_id": "TEST-BRIDGE-1",
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "latitude": 12.9716,
            "longitude": 77.5946,
            "speed": 12.0,
            "course": 180.0,
            "ignition": True,
            "simulated": True,
        }

        async def scenario():
            received = {}

            async def handle(reader, writer):
                line = await reader.readuntil(b"\n")
                message = decode_telemetry(line)
                received["device_id"] = message["device_id"]
                writer.write(encode_message(acknowledgement(message["message_id"], False)))
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            server = await asyncio.start_server(handle, "127.0.0.1", 0)
            port = server.sockets[0].getsockname()[1]
            try:
                bridge = TCPTelemetryBridge(host="127.0.0.1", port=port, timeout=5)
                ack = await bridge.send(frame)
            finally:
                server.close()
                await server.wait_closed()
            return received, ack

        received, ack = asyncio.run(scenario())
        self.assertEqual(received["device_id"], "TEST-BRIDGE-1")
        self.assertEqual(ack["type"], "ack")
        self.assertEqual(ack["status"], "accepted")
        self.assertFalse(ack["duplicate"])


class SettingsTests(unittest.TestCase):
    def test_defaults_are_development_friendly(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ("APP_ENV", "DATABASE_URL", "PORT", "CORS_ORIGINS"):
                os.environ.pop(key, None)
            settings = backend_config.Settings.from_environment()
        self.assertTrue(settings.is_development)
        self.assertEqual(settings.database_url, backend_config.DEFAULT_DATABASE_URL)
        self.assertEqual(settings.websocket_url, "ws://localhost:8000/ws/locations")

    def test_environment_overrides_are_respected(self):
        env = {
            "APP_ENV": "production",
            "DATABASE_URL": "postgresql+psycopg://navic:secret@db:5432/navic",
            "BACKEND_URL": "https://navic.example.edu",
            "CORS_ORIGINS": "https://navic.example.edu,https://admin.example.edu",
            "TCP_ENABLED": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            settings = backend_config.Settings.from_environment()
        self.assertFalse(settings.is_development)
        self.assertEqual(
            settings.database_url,
            "postgresql+psycopg://navic:secret@db:5432/navic",
        )
        self.assertEqual(
            settings.cors_origins,
            ("https://navic.example.edu", "https://admin.example.edu"),
        )
        self.assertFalse(settings.tcp_enabled)
        self.assertEqual(settings.websocket_url, "wss://navic.example.edu/ws/locations")

    def test_apply_defaults_never_overrides_existing_values(self):
        with patch.dict(
            os.environ, {"DATABASE_URL": "sqlite:///./custom.db"}, clear=False
        ):
            backend_config.Settings.from_environment().apply_defaults()
            self.assertEqual(os.environ["DATABASE_URL"], "sqlite:///./custom.db")


if __name__ == "__main__":
    unittest.main()
