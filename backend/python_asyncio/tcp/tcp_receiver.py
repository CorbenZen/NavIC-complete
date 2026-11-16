"""Adapter for the independent ``navic_tcp`` telemetry application.

The backend does not re-implement the TCP server.  It talks to the existing
server over the real newline-delimited JSON protocol using the tested client in
``navic_tcp.client.send_once``, and validates frames with
``navic_tcp.protocol.decode_telemetry``.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any

from backend.python_fastapi.application.core.config import Settings, get_settings
from navic_tcp.client import send_once
from navic_tcp.protocol import (
    MAX_MESSAGE_BYTES,
    MessageError,
    decode_telemetry,
    encode_message,
)


@dataclass
class TCPTelemetryBridge:
    """Send validated telemetry to the shared TCP receiver and read its ack."""

    host: str = "127.0.0.1"
    port: int = 5000
    timeout: float = 10.0

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TCPTelemetryBridge:
        settings = settings or get_settings()
        return cls(host=settings.tcp_host, port=settings.tcp_port)

    def validate(self, message: dict[str, Any]) -> dict[str, Any]:
        """Round-trip a message through the real protocol validator."""
        return decode_telemetry(encode_message(message))

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Validate and send one telemetry message, returning the server ack."""
        validated = self.validate(message)
        return await send_once(self.host, self.port, validated, self.timeout)

    async def probe(self) -> bool:
        """Check that the TCP receiver accepts connections."""
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, limit=MAX_MESSAGE_BYTES),
                self.timeout,
            )
        except (TimeoutError, OSError):
            return False
        writer.close()
        with contextlib.suppress(ConnectionError, OSError):
            await writer.wait_closed()
        return True


def create_bridge(settings: Settings | None = None) -> TCPTelemetryBridge:
    """Create a bridge from backend settings."""
    return TCPTelemetryBridge.from_settings(settings)


__all__ = ["MessageError", "TCPTelemetryBridge", "create_bridge"]
