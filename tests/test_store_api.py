from __future__ import annotations

import asyncio
import json
import unittest

from navic_tcp.api import TrackingApiServer
from navic_tcp.client import load_simulated_registry, simulated_telemetry
from navic_tcp.store import TelemetryStore


class CaptureWriter:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def get_extra_info(self, name):
        return ("memory", 8000) if name == "peername" else None

    def write(self, data):
        self.data.extend(data)

    async def drain(self):
        await asyncio.sleep(0)

    def close(self):
        self.closed = True

    async def wait_closed(self):
        await asyncio.sleep(0)


class StoreAndApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.store = TelemetryStore(history_limit=2, registry=load_simulated_registry())
        self.api = TrackingApiServer(self.store)

    def test_store_exposes_latest_and_bounded_history(self) -> None:
        device_id = "SIM-IMEI-000000000001"
        first = simulated_telemetry(device_id, 0)
        second = simulated_telemetry(device_id, 1)
        third = simulated_telemetry(device_id, 2)
        self.store.record(first)
        self.store.record(second)
        self.store.record(third)

        device = self.store.get_device(device_id)
        history = self.store.get_history(device_id)
        self.assertEqual(device["message_count"], 3)
        self.assertEqual(device["latest"]["message_id"], third["message_id"])
        self.assertEqual(len(history), 2)
        self.assertEqual([point["message_id"] for point in history], [second["message_id"], third["message_id"]])
        self.assertIsNone(self.store.get_device("missing"))
        self.assertIsNone(self.store.get_history("missing"))

    def test_out_of_order_fix_does_not_regress_latest_state(self) -> None:
        device_id = "SIM-IMEI-000000000001"
        newer = simulated_telemetry(device_id, 0)
        older = simulated_telemetry(device_id, 1)
        newer["timestamp"] = "2026-11-04T10:02:00.000Z"
        older["timestamp"] = "2026-11-04T10:01:00.000Z"
        self.store.record(newer)
        self.store.record(older)
        state = self.store.get_device(device_id)
        self.assertEqual(state["latest"]["message_id"], newer["message_id"])
        self.assertEqual(state["last_message_timestamp"], older["timestamp"])
        self.assertIsNotNone(state["last_received_at"])
        self.assertEqual([point["timestamp"] for point in self.store.get_history(device_id)], [older["timestamp"], newer["timestamp"]])

    def test_online_state_tracks_multiple_sessions(self) -> None:
        device_id = "SIM-IMEI-000000000001"
        self.store.record(simulated_telemetry(device_id, 0))
        self.store.connect_device(device_id)
        self.store.connect_device(device_id)
        self.assertTrue(self.store.get_device(device_id)["online"])
        self.store.disconnect_device(device_id)
        self.assertTrue(self.store.get_device(device_id)["online"])
        self.store.disconnect_device(device_id)
        self.assertFalse(self.store.get_device(device_id)["online"])

    def test_api_routes_health_devices_detail_and_history(self) -> None:
        for index in range(3):
            self.store.record(simulated_telemetry("SIM-IMEI-000000000001", index))

        status, payload = self.api.dispatch("GET", "/health")
        self.assertEqual((status, payload["status"], payload["devices"]), (200, "ok", 3))
        status, payload = self.api.dispatch("GET", "/devices")
        self.assertEqual((status, len(payload["devices"])), (200, 3))
        status, payload = self.api.dispatch("GET", "/devices/SIM-IMEI-000000000001")
        self.assertEqual((status, payload["message_count"]), (200, 3))
        self.assertEqual(payload["identity"]["vehicle_id"], "VEH-SIM-001")
        self.assertEqual(payload["identity"]["identifier_type"], "simulated_imei")
        self.assertIn("last_received_at", payload)
        status, payload = self.api.dispatch("GET", "/devices/SIM-IMEI-000000000001/history?limit=1")
        self.assertEqual((status, len(payload["history"])), (200, 1))
        self.assertEqual(payload["history"][0]["message_id"], self.store.get_device("SIM-IMEI-000000000001")["latest"]["message_id"])

    def test_api_reports_unknown_devices_invalid_limits_and_methods(self) -> None:
        self.assertEqual(self.api.dispatch("GET", "/devices/missing")[0], 404)
        self.assertEqual(self.api.dispatch("GET", "/devices/missing/history")[0], 404)
        self.assertEqual(self.api.dispatch("GET", "/devices/any/history?limit=0")[0], 400)
        self.assertEqual(self.api.dispatch("POST", "/health")[0], 405)
        self.assertEqual(self.api.dispatch("GET", "/unknown")[0], 404)

    async def test_http_handler_parses_request_and_serializes_json(self) -> None:
        self.store.record(simulated_telemetry("SIM-IMEI-000000000001", 0))
        reader = asyncio.StreamReader()
        reader.feed_data(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        reader.feed_eof()
        writer = CaptureWriter()
        await self.api._handle_client(reader, writer)

        headers, body = bytes(writer.data).split(b"\r\n\r\n", 1)
        self.assertTrue(headers.startswith(b"HTTP/1.1 200 OK"))
        self.assertEqual(json.loads(body), {"status": "ok", "devices": 3})
        self.assertTrue(writer.closed)


if __name__ == "__main__":
    unittest.main()
