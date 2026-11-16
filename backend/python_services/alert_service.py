"""Alert service: offline/status evaluation and persisted alert access."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.python_sqlalchemy.models import Alert
from backend.python_utils.helpers import page_params
from navic_tcp.fastapi_app import (
    create_offline_alerts,
    evaluate_vehicle_status_transitions,
)


def generate_offline_alerts(db: Session, now: datetime | None = None) -> int:
    """Create device-offline alerts using the shared detector."""
    return create_offline_alerts(db, now)


async def evaluate_status_transitions(now: datetime | None = None) -> int:
    """Evaluate and publish vehicle status transitions."""
    return await evaluate_vehicle_status_transitions(now)


def list_alerts(
    db: Session,
    *,
    limit: int | None = 100,
    offset: int | None = 0,
    unread_only: bool = False,
    event_type: str | None = None,
) -> list[Alert]:
    """Return alerts newest-first with safe pagination and filtering."""
    safe_limit, safe_offset = page_params(limit, offset)
    statement = (
        select(Alert)
        .order_by(Alert.created_at.desc(), Alert.id.desc())
        .limit(safe_limit)
        .offset(safe_offset)
    )
    if unread_only:
        statement = statement.where(Alert.is_read.is_(False))
    if event_type:
        statement = statement.where(Alert.event_type == event_type)
    return list(db.scalars(statement).all())


def get_alert(db: Session, alert_id: int) -> Alert | None:
    return db.get(Alert, alert_id)


def mark_read(db: Session, alert_id: int, read: bool = True) -> Alert | None:
    """Set the read flag in a transaction."""
    alert = db.get(Alert, alert_id)
    if alert is None:
        return None
    alert.is_read = read
    try:
        db.commit()
        db.refresh(alert)
    except Exception:
        db.rollback()
        raise
    return alert


def mark_all_read(db: Session) -> int:
    """Mark every unread alert as read and return the number changed."""
    alerts = list(db.scalars(select(Alert).where(Alert.is_read.is_(False))).all())
    for alert in alerts:
        alert.is_read = True
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return len(alerts)


def unread_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(Alert).where(Alert.is_read.is_(False))
        )
        or 0
    )


def serialize_alert(alert: Alert) -> dict[str, Any]:
    """Plain-dict representation used by tooling and tests."""
    return {
        "id": alert.id,
        "event_type": alert.event_type,
        "message": alert.message,
        "device_id": alert.device_id,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "is_read": alert.is_read,
    }


__all__ = [
    "evaluate_status_transitions",
    "generate_offline_alerts",
    "get_alert",
    "list_alerts",
    "mark_all_read",
    "mark_read",
    "serialize_alert",
    "unread_count",
]
