from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from navic_tcp.api import TrackingApiServer
from navic_tcp.client import (
    load_simulated_registry,
    run_simulator,
    send_once,
    send_with_retry,
    simulated_telemetry,
    simulator_device_ids,
)
from navic_tcp.protocol import (
    MAX_MESSAGE_BYTES,
    MessageError,
    decode_telemetry,
    encode_message,
)
from navic_tcp.registry import DeviceRegistry
from navic_tcp.server import TelemetryServer


class MemoryWriter:
    def __init__(self, peer: asyncio.StreamReader, peername=("memory", 1)):
        self.peer = peer
        self.peername = peername
        self.closed = False

    def get_extra_info(self, name):
        return self.peername if name == "peername" else None

    def write(self, data: bytes):
        if not self.closed:
            self.peer.feed_data(data)

    async def drain(self):
        await asyncio.sleep(0)

    def close(self):
        if not self.closed:
            self.closed = True
            self.peer.feed_eof()

    async def wait_closed(self):
        await asyncio.sleep(0)


class TelemetrySystemTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = TelemetryServer("127.0.0.1", 9000, dedupe_limit=2)

    async def asyncTearDown(self) -> None:
        await self.server.close()

    def message(self, device: str = "TEST-DEVICE") -> dict:
        return simulated_telemetry(device, 0)

    async def run_handler(self, raw: bytes) -> tuple[list[dict], MemoryWriter]:
        reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        peer_reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        writer = MemoryWriter(peer_reader)
        reader.feed_data(raw)
        reader.feed_eof()
        await self.server._handle_client(reader, writer)
        records = [json.loads(frame) for frame in peer_reader._buffer.split(b"\n") if frame]
        return records, writer

    async def run_handler_raw(self, raw: bytes) -> tuple[bytes, MemoryWriter]:
        reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        peer_reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        writer = MemoryWriter(peer_reader)
        reader.feed_data(raw)
        reader.feed_eof()
        await self.server._handle_client(reader, writer)
        return peer_reader._buffer, writer

    async def test_simulated_client_gets_valid_server_ack_in_memory(self) -> None:
        message = self.message()
        client_reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        server_reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        client_writer = MemoryWriter(server_reader, ("memory-client", 42))
        server_writer = MemoryWriter(client_reader, ("memory-server", 9000))
        server_task = asyncio.create_task(self.server._handle_client(server_reader, server_writer))

        async def open_memory_connection(*args, **kwargs):
            return client_reader, client_writer

        with patch("navic_tcp.client.asyncio.open_connection", open_memory_connection):
            response = await send_once("127.0.0.1", 9000, message)
        await server_task
        self.assertEqual(response["type"], "ack")
        self.assertEqual(response["message_id"], message["message_id"])
        self.assertEqual(response["status"], "accepted")
        self.assertEqual(self.server.accepted_count, 1)
        self.assertEqual(self.server.store.get_device(message["device_id"])["latest"]["message_id"], message["message_id"])

    async def test_device_session_becomes_online_then_offline(self) -> None:
        message = self.message()
        client_reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        server_peer = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        server_writer = MemoryWriter(server_peer, ("memory-server", 9000))
        task = asyncio.create_task(self.server._handle_client(client_reader, server_writer))
        client_reader.feed_data(encode_message(message))
        reply = json.loads(await server_peer.readuntil(b"\n"))
        self.assertEqual(reply["status"], "accepted")
        self.assertTrue(self.server.store.get_device(message["device_id"])["online"])
        client_reader.feed_eof()
        await task
        self.assertFalse(self.server.store.get_device(message["device_id"])["online"])

    async def test_simulator_server_and_api_pipeline_in_memory(self) -> None:
        from navic_tcp.store import TelemetryStore

        registry = load_simulated_registry()
        self.server.store = TelemetryStore(history_limit=20, registry=registry)
        api = TrackingApiServer(self.server.store, port=8001)
        handlers: list[asyncio.Task] = []

        async def memory_connect(host, port, **kwargs):
            client_reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
            server_reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
            client_writer = MemoryWriter(server_reader, ("memory-client", 0))
            server_writer = MemoryWriter(client_reader, ("memory-server", 9000))
            handlers.append(asyncio.create_task(self.server._handle_client(server_reader, server_writer)))
            return client_reader, client_writer

        with patch("navic_tcp.client.asyncio.open_connection", memory_connect):
            sent = await asyncio.gather(*(
                run_simulator("127.0.0.1", 9000, device_id, interval=0, count=3)
                for device_id in registry.device_ids
            ))
        await asyncio.gather(*handlers)

        self.assertEqual(sent, [3, 3, 3])
        self.assertEqual(api.dispatch("GET", "/health"), (200, {"status": "ok", "devices": 3}))
        for device_id in registry.device_ids:
            status, detail = api.dispatch("GET", f"/devices/{device_id}")
            history_status, history = api.dispatch("GET", f"/devices/{device_id}/history?limit=20")
            self.assertEqual(status, 200)
            self.assertTrue(detail["latest"]["simulated"])
            self.assertEqual(detail["message_count"], 3)
            self.assertEqual((history_status, len(history["history"])), (200, 3))

    async def test_partial_frame_and_multiple_frames_on_one_stream(self) -> None:
        first, second = self.message(), self.message()
        raw = encode_message(first)
        reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        peer = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        writer = MemoryWriter(peer)
        reader.feed_data(raw[:17])
        task = asyncio.create_task(self.server._handle_client(reader, writer))
        await asyncio.sleep(0)
        reader.feed_data(raw[17:] + encode_message(second))
        reader.feed_eof()
        await task
        replies = [json.loads(item) for item in peer._buffer.split(b"\n") if item]
        self.assertEqual([reply["message_id"] for reply in replies], [first["message_id"], second["message_id"]])
        self.assertEqual(self.server.accepted_count, 2)

    async def test_duplicate_is_acknowledged_without_second_accept(self) -> None:
        message = self.message()
        first, _ = await self.run_handler(encode_message(message))
        duplicate, _ = await self.run_handler(encode_message(message))
        self.assertEqual(first[0]["status"], "accepted")
        self.assertEqual(duplicate[0]["status"], "duplicate")
        self.assertTrue(duplicate[0]["duplicate"])
        self.assertEqual(self.server.accepted_count, 1)
        self.assertEqual(self.server.store.get_device(message["device_id"])["message_count"], 1)

    async def test_malformed_json_is_echoed_and_next_frame_is_processed(self) -> None:
        raw = b"{bad json}\n"
        buffer, _ = await self.run_handler_raw(raw + encode_message(self.message()))
        self.assertEqual(buffer[:len(raw)], raw)
        self.assertEqual(json.loads(buffer[len(raw):])["type"], "ack")

    async def test_invalid_telemetry_is_echoed_without_being_accepted(self) -> None:
        missing = self.message()
        del missing["device_id"]
        invalid = self.message()
        invalid["latitude"] = 91
        raw = encode_message(missing) + encode_message(invalid)
        buffer, _ = await self.run_handler_raw(raw)
        self.assertEqual(buffer, raw)
        self.assertEqual(self.server.accepted_count, 0)

    async def test_protocol_version_timestamp_and_course_are_validated(self) -> None:
        valid = self.message()
        self.assertEqual(valid["protocol_version"], 1)
        self.assertTrue(valid["simulated"])
        self.assertNotIn("driver_name", valid)
        valid.pop("odometer")
        decoded = decode_telemetry(encode_message(valid).rstrip(b"\n"))
        self.assertNotIn("odometer", decoded)
        for field, value in (("protocol_version", 2), ("timestamp", "2026-11-04 16:30:00Z"), ("course", 360)):
            invalid = self.message()
            invalid[field] = value
            with self.subTest(field=field), self.assertRaises(MessageError):
                decode_telemetry(encode_message(invalid).rstrip(b"\n"))

    async def test_nonfinite_speed_and_nonboolean_ignition_rejected(self) -> None:
        bad_speed = self.message()
        bad_speed["speed"] = float("nan")
        with self.assertRaises(MessageError):
            decode_telemetry(json.dumps(bad_speed, allow_nan=True).encode())
        bad_ignition = self.message()
        bad_ignition["ignition"] = 1
        with self.assertRaises(MessageError):
            decode_telemetry(json.dumps(bad_ignition).encode())

    async def test_oversized_frame_is_rejected(self) -> None:
        frames, writer = await self.run_handler(b"{" + b" " * (MAX_MESSAGE_BYTES + 5) + b"}\n")
        self.assertEqual(frames[0]["error"]["code"], "message_too_large")
        self.assertTrue(writer.closed)

    async def test_unterminated_frame_is_rejected(self) -> None:
        frames, _ = await self.run_handler(b'{"type":"telemetry"}')
        self.assertEqual(frames[0]["error"]["code"], "unterminated_message")

    async def test_clean_client_disconnect_is_handled(self) -> None:
        _, writer = await self.run_handler(b"")
        self.assertTrue(writer.closed)

    async def test_arbitrary_text_is_echoed_and_connection_stays_open(self) -> None:
        message = self.message()
        raw = b"HI\r\nhello world 123\n12345\n{\"a\":1}\n"
        reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        peer = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        writer = MemoryWriter(peer)
        reader.feed_data(raw + encode_message(message))
        reader.feed_eof()
        await self.server._handle_client(reader, writer)
        buffer = peer._buffer
        self.assertEqual(buffer[:len(raw)], raw)
        self.assertEqual(json.loads(buffer[len(raw):])["type"], "ack")
        self.assertEqual(self.server.accepted_count, 1)

    async def test_echoes_are_sent_only_to_the_requesting_connection(self) -> None:
        peers = []
        handlers = []
        for text in (b"alpha\n", b"beta\n"):
            reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
            peer = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
            reader.feed_data(text)
            reader.feed_eof()
            peers.append(peer)
            handlers.append(asyncio.create_task(self.server._handle_client(reader, MemoryWriter(peer))))
        await asyncio.gather(*handlers)
        self.assertEqual([peer._buffer for peer in peers], [b"alpha\n", b"beta\n"])

    async def test_lowercase_hi_is_echoed_like_any_other_text(self) -> None:
        buffer, _ = await self.run_handler_raw(b"hi\n")
        self.assertEqual(buffer, b"hi\n")

    async def test_multiple_simultaneous_handlers(self) -> None:
        messages = [self.message(f"DEVICE-{n}") for n in range(8)]
        results = await asyncio.gather(*(self.run_handler(encode_message(message)) for message in messages))
        self.assertTrue(all(frames[0]["type"] == "ack" for frames, _ in results))
        self.assertEqual(self.server.accepted_count, len(messages))

    async def test_retry_uses_same_id_after_transient_connection_failure(self) -> None:
        message = self.message()
        calls = []

        async def flaky_send(host, port, outgoing):
            calls.append(outgoing["message_id"])
            if len(calls) == 1:
                raise ConnectionRefusedError("test refusal")
            return {"type": "ack", "message_id": outgoing["message_id"], "status": "accepted", "duplicate": False, "received_at": "2026-11-04T00:00:00Z"}

        with patch("navic_tcp.client.send_once", flaky_send), patch("navic_tcp.client.random.uniform", return_value=1.0):
            result = await send_with_retry("127.0.0.1", 9000, message, 0.001, 0.001)
        self.assertEqual(result["message_id"], message["message_id"])
        self.assertEqual(calls, [message["message_id"], message["message_id"]])

    async def test_ack_message_mismatch_is_rejected(self) -> None:
        client_reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES)
        client_reader.feed_data(encode_message({"type": "ack", "message_id": "wrong", "status": "accepted", "duplicate": False, "received_at": "2026-11-04T00:00:00Z"}))
        client_reader.feed_eof()
        writer = MemoryWriter(asyncio.StreamReader())

        async def open_memory_connection(*args, **kwargs):
            return client_reader, writer

        with patch("navic_tcp.client.asyncio.open_connection", open_memory_connection):
            with self.assertRaises(MessageError):
                await send_once("127.0.0.1", 9000, self.message())

    async def test_close_is_safe_without_opening_listener(self) -> None:
        await self.server.close()
        await self.server.close()
        self.assertIsNone(self.server._server)

    async def test_simulator_can_make_distinct_device_ids(self) -> None:
        registry = load_simulated_registry("config/devices.json")
        self.assertEqual(simulator_device_ids(3, registry), ["SIM-IMEI-000000000001", "SIM-IMEI-000000000002", "SIM-SERIAL-000003"])
        self.assertEqual(registry.get("SIM-IMEI-000000000001")["vehicle_id"], "VEH-SIM-001")
        self.assertEqual(registry.get("SIM-SERIAL-000003")["identifier_type"], "simulated_serial")
        self.assertTrue(all(simulated_telemetry(device_id, 0)["simulated"] for device_id in registry.device_ids))

    async def test_demo_registry_matches_seeded_fleet_and_produces_distinct_bengaluru_paths(self) -> None:
        # Regression: IVTD_BUS_01 uses underscores, so a "-" split previously
        # assigned every device the same index and the same path.
        registry = load_simulated_registry("config/devices.demo.json")
        self.assertEqual(
            simulator_device_ids(6, registry),
            [f"IVTD_BUS_{number:02d}" for number in range(1, 7)],
        )
        positions = {}
        for device_id in registry.device_ids:
            packet = simulated_telemetry(device_id, 0)
            self.assertTrue(packet["simulated"])
            self.assertGreaterEqual(packet["speed"], 0)
            self.assertLessEqual(packet["speed"], 400)
            self.assertGreaterEqual(packet["course"], 0)
            self.assertLess(packet["course"], 360)
            self.assertTrue(13.0 <= packet["latitude"] <= 13.1)
            self.assertTrue(77.55 <= packet["longitude"] <= 77.7)
            positions[device_id] = (packet["latitude"], packet["longitude"])
        self.assertEqual(len(set(positions.values())), 6)

        # Stops occur, but movement continues afterwards and remains smooth.
        speeds = [simulated_telemetry("IVTD_BUS_01", sequence)["speed"] for sequence in range(240)]
        self.assertIn(0.0, speeds)
        self.assertGreater(max(speeds), 5.0)
        first = simulated_telemetry("IVTD_BUS_01", 10)
        second = simulated_telemetry("IVTD_BUS_01", 11)
        self.assertLess(abs(first["latitude"] - second["latitude"]), 0.001)
        self.assertLess(abs(first["longitude"] - second["longitude"]), 0.001)

    async def test_configured_registry_rejects_unknown_device(self) -> None:
        from navic_tcp.store import TelemetryStore

        self.server.store = TelemetryStore(registry=load_simulated_registry())
        frames, _ = await self.run_handler(encode_message(self.message("UNREGISTERED")))
        self.assertEqual(frames[0]["error"]["code"], "unknown_device")
        self.assertEqual(self.server.accepted_count, 0)

    async def test_explicit_empty_registry_rejects_all_devices(self) -> None:
        from navic_tcp.store import TelemetryStore

        self.server.store = TelemetryStore(registry=DeviceRegistry([]))
        frames, _ = await self.run_handler(encode_message(self.message()))
        self.assertEqual(frames[0]["error"]["code"], "unknown_device")


if __name__ == "__main__":
    unittest.main()
