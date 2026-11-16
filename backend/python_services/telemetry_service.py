"""Telemetry decoding, ingestion and read helpers.

Incoming frames keep the existing newline-delimited JSON protocol.  Validation
and persistence delegate to the shared implementation so the TCP receiver, the
REST API and WebSocket clients all observe exactly the same data.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.python_sqlalchemy.models import LocationHistory
from navic_tcp.protocol import (
    MAX_MESSAGE_BYTES,
    MessageError,
    acknowledgement,
    decode_telemetry,
    encode_message,
    error_response,
)


def decode_frame(line: bytes) -> dict[str, Any]:
    """Validate and decode one NDJSON telemetry frame."""
    return decode_telemetry(line)


def encode_ack(message_id: str, duplicate: bool = False) -> bytes:
    """Encode an acknowledgement frame for a decoded message."""
    return encode_message(acknowledgement(message_id, duplicate))


def encode_error(error: MessageError) -> bytes:
    """Encode a protocol error frame."""
    return encode_message(error_response(error))


async def ingest(message: dict[str, Any]) -> None:
    """Process a decoded telemetry message through the shared pipeline.

    This persists the fix, updates device status and publishes live WebSocket
    updates via the shared ``on_telemetry`` implementation.
    """
    from navic_tcp.fastapi_app import on_telemetry

    await on_telemetry(message)


def latest_points(db: Session, limit: int = 50) -> list[LocationHistory]:
    """Most recent stored fixes across all devices."""
    statement = (
        select(LocationHistory)
        .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def history_for_device(db: Session, device_id: str, limit: int = 100) -> list[LocationHistory]:
    """Most recent stored fixes for a single device."""
    statement = (
        select(LocationHistory)
        .where(LocationHistory.device_id == device_id)
        .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def latest_for_device(db: Session, device_id: str) -> LocationHistory | None:
    """Most recent stored fix for one device, including invalid fixes."""
    statement = (
        select(LocationHistory)
        .where(LocationHistory.device_id == device_id)
        .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
        .limit(1)
    )
    return db.scalar(statement)


def point_count(db: Session, device_id: str | None = None) -> int:
    """Count stored fixes, optionally for one device."""
    statement = select(func.count()).select_from(LocationHistory)
    if device_id is not None:
        statement = statement.where(LocationHistory.device_id == device_id)
    return int(db.scalar(statement) or 0)


__all__ = [
    "MAX_MESSAGE_BYTES",
    "MessageError",
    "decode_frame",
    "encode_ack",
    "encode_error",
    "history_for_device",
    "ingest",
    "latest_for_device",
    "latest_points",
    "point_count",
]
