"""Configurable reconnecting telemetry sender and simulated GNSS source."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
import random
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from .protocol import MAX_MESSAGE_BYTES, MessageError, encode_message, utc_now
from .registry import DEFAULT_REGISTRY_PATH, DeviceRegistry

LOG = logging.getLogger("navic_tcp.client")
DEFAULT_REGISTRY = DEFAULT_REGISTRY_PATH


def load_simulated_registry(path: str | Path = DEFAULT_REGISTRY) -> DeviceRegistry:
    return DeviceRegistry.load(path)


def simulator_device_ids(count: int, registry: DeviceRegistry | None = None) -> list[str]:
    if count < 1:
        raise ValueError("count must be positive")
    ids = (registry or load_simulated_registry()).device_ids
    if count > len(ids):
        raise ValueError(f"requested {count} devices, but registry contains {len(ids)}")
    return ids[:count]


def simulated_telemetry(
    device_id: str,
    sequence: int,
    base_latitude: float = 13.0435,
    base_longitude: float = 77.6200,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Return clearly marked synthetic data; no receiver or hardware is read.

    Each demo device follows a smooth, repeating elliptical path around the
    configured demo origin.  The paths are not surveyed roads and are not a
    claim about the college's real bus routes.  Short zero-speed windows model
    stops; different device indices use different radii, phases and directions.
    """
    # Demo IDs look like IVTD_BUS_01 (underscores), while legacy registry IDs
    # look like SIM-IMEI-000000000001.  In both cases the trailing digits
    # identify the vehicle, so do not split on "-" alone.
    suffix = re.search(r"(\d+)$", device_id)
    index = int(suffix.group(1)) if suffix else 0
    direction = -1.0 if index % 2 else 1.0
    phase = (sequence + index * 37) % 240
    angle = direction * (2.0 * math.pi * phase / 240.0)
    lat_radius = 0.0055 + (index % 3) * 0.0008
    lon_radius = 0.0070 + (index % 2) * 0.0010
    lat_offset = ((index % 3) - 1) * 0.0012
    lon_offset = (((index + 1) % 3) - 1) * 0.0012

    # Four short station stops per loop.  The vehicle holds its position and
    # reports zero speed while ignition stays on (a realistic idle at a stop).
    stop_centres = (0, 60, 120, 180)
    stopped = any(min(abs(phase - centre), 240 - abs(phase - centre)) <= 3 for centre in stop_centres)
    if stopped:
        nearest = min(stop_centres, key=lambda centre: min(abs(phase - centre), 240 - abs(phase - centre)))
        angle = direction * (2.0 * math.pi * nearest / 240.0)

    latitude = base_latitude + lat_offset + lat_radius * math.sin(angle)
    longitude = base_longitude + lon_offset + lon_radius * math.cos(angle)

    # Course is the tangent of the ellipse, converted to a compass bearing.
    dx = -lon_radius * math.sin(angle) * direction
    dy = lat_radius * math.cos(angle) * direction
    # Round first, then normalise: rounding can otherwise produce exactly
    # 360.0, which the protocol rejects (valid range is 0 <= course < 360).
    course = round((math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0, 2) % 360.0

    if stopped:
        speed = 0.0
    else:
        speed = 24.0 + 9.0 * math.sin(2.0 * angle + index) + 3.0 * math.sin(5.0 * angle)
    speed = max(0.0, round(speed, 2))

    message = {
        "protocol_version": 1,
        "type": "telemetry",
        "message_id": str(uuid4()),
        "device_id": device_id,
        "timestamp": utc_now(),
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "speed": speed,
        "course": course,
        "ignition": True,
        "odometer": round(12500.0 + sequence * 0.0075, 3),
        "simulated": True,
        "data_source": "simulator",
    }
    if auth_token:
        # The server only checks this when DEVICE_AUTH_TOKEN or a per-device
        # registry secret is configured; it is never a way to bypass identity.
        message["auth_token"] = auth_token
    return message


async def send_once(host: str, port: int, message: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port, limit=MAX_MESSAGE_BYTES), timeout)
    try:
        writer.write(encode_message(message))
        await asyncio.wait_for(writer.drain(), timeout)
        line = await asyncio.wait_for(reader.readuntil(b"\n"), timeout)
        if len(line) > MAX_MESSAGE_BYTES:
            raise MessageError("invalid_response", "server response exceeds the message limit")
        try:
            response = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise MessageError("invalid_response", "server returned invalid JSON") from None
        if not isinstance(response, dict):
            raise MessageError("invalid_response", "server response must be an object")
        if response.get("type") == "error":
            error = response.get("error") if isinstance(response.get("error"), dict) else {}
            raise MessageError(str(error.get("code", "server_error")), str(error.get("message", "server rejected telemetry")), response.get("message_id"))
        if (response.get("type") != "ack" or response.get("message_id") != message["message_id"]
                or response.get("status") not in {"accepted", "duplicate"}
                or not isinstance(response.get("duplicate"), bool)
                or not isinstance(response.get("received_at"), str)):
            raise MessageError("invalid_response", "server acknowledgement does not match the sent message")
        return response
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await writer.wait_closed()


async def run_interactive(
    host: str,
    port: int,
    stop: asyncio.Event | None = None,
    timeout: float = 10.0,
) -> None:
    """Open one connection and send each typed line to the server.

    Every non-blank line is sent with the protocol's existing newline framing,
    and the server's raw reply is printed.  ``quit`` and ``exit`` close the
    connection.  The default simulator CLI is unchanged; this mode is opt-in
    via ``--interactive``.
    """
    stop = stop or asyncio.Event()
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port, limit=MAX_MESSAGE_BYTES), timeout
    )
    print("Type a message and press Enter. Type quit or exit to close.")
    try:
        while not stop.is_set():
            try:
                line = await asyncio.to_thread(input, "> ")
            except EOFError:
                break
            if not line.strip():
                continue
            if line.strip() in {"quit", "exit"}:
                break
            writer.write((line + "\n").encode("utf-8"))
            await asyncio.wait_for(writer.drain(), timeout)
            reply = await asyncio.wait_for(reader.readuntil(b"\n"), timeout)
            text = reply.decode("utf-8", errors="replace").rstrip("\r\n")
            print(f"server received: {text}")
    finally:
        writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await writer.wait_closed()


async def send_with_retry(
    host: str,
    port: int,
    message: dict[str, Any],
    retry_base: float = 0.5,
    retry_max: float = 10.0,
    stop: asyncio.Event | None = None,
) -> dict[str, Any] | None:
    """Retry transient failures using the same message ID for deduplication."""
    attempt = 0
    stop = stop or asyncio.Event()
    while not stop.is_set():
        try:
            result = await send_once(host, port, message)
            LOG.info("ack received message_id=%s status=%s", message["message_id"], result["status"])
            return result
        except MessageError as exc:
            LOG.error("server rejected message_id=%s code=%s message=%s", message["message_id"], exc.code, exc.message)
            raise
        except (TimeoutError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            delay = min(retry_max, retry_base * (2 ** min(attempt, 8)))
            delay *= random.uniform(0.9, 1.1)
            attempt += 1
            LOG.warning("connection failed message_id=%s retry_in=%.2fs reason=%s", message["message_id"], delay, type(exc).__name__)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), delay)
    return None


async def run_simulator(
    host: str,
    port: int,
    device_id: str = "SIM-IMEI-000000000001",
    interval: float = 1.0,
    count: int | None = 1,
    retry_base: float = 0.5,
    retry_max: float = 10.0,
    stop: asyncio.Event | None = None,
    base_latitude: float = 13.0435,
    base_longitude: float = 77.6200,
    auth_token: str | None = None,
) -> int:
    sent = 0
    stop = stop or asyncio.Event()
    sequence = 0
    while not stop.is_set() and (count is None or sent < count):
        message = simulated_telemetry(device_id, sequence, base_latitude, base_longitude, auth_token)
        result = await send_with_retry(host, port, message, retry_base, retry_max, stop)
        if result is None:
            break
        sent += 1
        sequence += 1
        if count is None or sent < count:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), interval)
    return sent
