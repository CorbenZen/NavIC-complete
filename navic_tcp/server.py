"""Concurrent asyncio TCP server for local telemetry demonstrations."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
from collections import OrderedDict

from .protocol import (
    MAX_MESSAGE_BYTES,
    MessageError,
    acknowledgement,
    decode_telemetry,
    encode_message,
    error_response,
)
from .store import TelemetryStore

LOG = logging.getLogger("navic_tcp.server")


class TelemetryServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9000,
        dedupe_limit: int = 10_000,
        store: TelemetryStore | None = None,
        on_telemetry=None,
    ):
        if dedupe_limit < 1:
            raise ValueError("dedupe_limit must be positive")
        self.host = host
        self.port = port
        self.dedupe_limit = dedupe_limit
        self._seen: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.store = store or TelemetryStore()
        self.accepted_count = 0
        self.on_telemetry = on_telemetry
        self.idle_timeout = float(os.getenv("TCP_IDLE_TIMEOUT_SECONDS", "0") or 0)
        # A shared secret is optional: the firmware contract only carries a
        # registered device_id today.  Set DEVICE_AUTH_TOKEN (or a per-device
        # device_secret in the registry) to require the optional auth_token field.
        self.shared_secret = os.getenv("DEVICE_AUTH_TOKEN") or None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            self.host,
            self.port,
            limit=MAX_MESSAGE_BYTES,
        )
        sockets = self._server.sockets or []
        if sockets:
            bound_host, bound_port = sockets[0].getsockname()[:2]
            LOG.info("listening host=%s port=%s", bound_host, bound_port)

    async def serve_forever(self) -> None:
        if self._server is None:
            await self.start()
        assert self._server is not None
        async with self._server:
            await self._server.serve_forever()

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        writers = list(self._writers)
        for writer in writers:
            writer.close()
        if writers:
            await asyncio.gather(*(writer.wait_closed() for writer in writers), return_exceptions=True)
        LOG.info("server stopped")

    async def _send_error(self, writer: asyncio.StreamWriter, error: MessageError) -> None:
        writer.write(encode_message(error_response(error)))
        await writer.drain()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        peer_label = f"{peer[0]}:{peer[1]}" if isinstance(peer, tuple) and len(peer) > 1 else "unknown"
        self._writers.add(writer)
        identified_devices: set[str] = set()
        LOG.info("client connected peer=%s", peer_label)
        try:
            while True:
                try:
                    if self.idle_timeout > 0:
                        frame = await asyncio.wait_for(reader.readuntil(b"\n"), timeout=self.idle_timeout)
                    else:
                        frame = await reader.readuntil(b"\n")
                except TimeoutError:
                    await self._send_error(writer, MessageError("idle_timeout", "no complete message received within the idle timeout"))
                    LOG.info("closing idle connection peer=%s", peer_label)
                    break
                except asyncio.LimitOverrunError:
                    await self._send_error(writer, MessageError("message_too_large", "message exceeds the 65536-byte limit"))
                    LOG.warning("rejected oversized frame peer=%s", peer_label)
                    break
                except asyncio.IncompleteReadError as exc:
                    if not exc.partial:
                        break
                    code = "message_too_large" if len(exc.partial) > MAX_MESSAGE_BYTES else "unterminated_message"
                    detail = "message exceeds the 65536-byte limit" if code == "message_too_large" else "message must end with a newline"
                    await self._send_error(writer, MessageError(code, detail))
                    break

                payload = frame[:-1]
                if payload.endswith(b"\r"):
                    payload = payload[:-1]
                LOG.info("[peer %s] received: %s", peer_label, payload.decode("utf-8", errors="replace"))
                try:
                    message = decode_telemetry(payload)
                except MessageError:
                    # Arbitrary text/JSON is not a telemetry packet. Echo the
                    # original frame unchanged so the client can confirm the
                    # round trip. This is normal plain-message input, not a
                    # protocol error.
                    writer.write(frame)
                    await writer.drain()
                    LOG.info("plain message echoed peer=%s", peer_label)
                    continue

                if self.store.registry_enforced and self.store.registry.get(message["device_id"]) is None:
                    await self._send_error(writer, MessageError("unknown_device", "device_id is not present in the configured registry", message["message_id"]))
                    LOG.warning("rejected telemetry peer=%s code=unknown_device", peer_label)
                    continue

                entry = self.store.registry.get(message["device_id"]) or {}
                required_secret = self.shared_secret or entry.get("device_secret")
                if required_secret:
                    provided = message.get("auth_token")
                    if not isinstance(provided, str) or not hmac.compare_digest(provided, str(required_secret)):
                        await self._send_error(writer, MessageError("unauthorized_device", "a valid auth_token is required for this device", message["message_id"]))
                        LOG.warning("rejected telemetry peer=%s code=unauthorized_device", peer_label)
                        continue

                key = (message["device_id"], message["message_id"])
                duplicate = key in self._seen
                if duplicate:
                    self._seen.move_to_end(key)
                else:
                    self._seen[key] = None
                    self.accepted_count += 1
                    self.store.record(message)
                    if self.on_telemetry is not None:
                        result = self.on_telemetry(message)
                        if asyncio.iscoroutine(result):
                            await result
                    while len(self._seen) > self.dedupe_limit:
                        self._seen.popitem(last=False)
                if message["device_id"] not in identified_devices:
                    self.store.connect_device(message["device_id"])
                    identified_devices.add(message["device_id"])
                if not duplicate:
                    LOG.info("telemetry processed simulated=%s known_devices=%s peer=%s",
                             message["simulated"], self.store.device_count, peer_label)
                writer.write(encode_message(acknowledgement(message["message_id"], duplicate)))
                await writer.drain()
        except (ConnectionError, OSError) as exc:
            LOG.info("client disconnected peer=%s reason=%s", peer_label, type(exc).__name__)
        finally:
            for device_id in identified_devices:
                self.store.disconnect_device(device_id)
            self._writers.discard(writer)
            writer.close()
            with contextlib.suppress(ConnectionError, OSError):
                await writer.wait_closed()
            LOG.info("client closed peer=%s", peer_label)
