"""Alert controller: paginated alerts, read state and the audit trail."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select

from backend.python_fastapi.application.controllers.base import Controller
from backend.python_fastapi.application.core.dependencies import (
    admin_user,
    current_user,
    management_user,
)
from backend.python_services import alert_service
from backend.python_sqlalchemy.database.session import SessionLocal
from backend.python_sqlalchemy.models import AuditLog
from navic_tcp.fastapi_app import _audit, _iso


def list_alerts(
    unread_only: bool = False,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(current_user),
):
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422, "invalid pagination")
    with SessionLocal() as db:
        rows = alert_service.list_alerts(db, limit=limit, offset=offset, unread_only=unread_only, event_type=event_type)
        unread = alert_service.unread_count(db)
        return {
            "alerts": [
                {
                    "id": alert.id,
                    "event_type": alert.event_type,
                    "message": alert.message,
                    "device_id": alert.device_id,
                    "created_at": _iso(alert.created_at),
                    "is_read": alert.is_read,
                }
                for alert in rows
            ],
            "unread_count": unread,
        }


def mark_all_alerts_read(user=Depends(management_user)):
    with SessionLocal() as db:
        updated = alert_service.mark_all_read(db)
        _audit(db, user, "update", "alerts", "all", "marked all alerts read")
        db.commit()
        return {"updated": updated}


def mark_alert_read(alert_id: int, user=Depends(management_user)):
    with SessionLocal() as db:
        row = alert_service.mark_read(db, alert_id)
        if not row:
            raise HTTPException(404, "alert not found")
        _audit(db, user, "update", "alert", row.id, "marked read")
        db.commit()
        return {"id": row.id, "is_read": row.is_read}


def audit_log(limit: int = 100, offset: int = 0, user=Depends(admin_user)):
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422, "invalid pagination")
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(AuditLog)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
        return {
            "audit": [
                {
                    "id": row.id,
                    "actor": row.actor,
                    "actor_role": row.actor_role,
                    "action": row.action,
                    "entity": row.entity,
                    "entity_id": row.entity_id,
                    "detail": row.detail,
                    "created_at": _iso(row.created_at),
                }
                for row in rows
            ]
        }


class AlertController(Controller):
    operations = {
        "/alerts": list_alerts,
        "/alerts/read-all": mark_all_alerts_read,
        "/alerts/{alert_id}": mark_alert_read,
        "/api/audit": audit_log,
    }


__all__ = [
    "AlertController",
    "audit_log",
    "list_alerts",
    "mark_alert_read",
    "mark_all_alerts_read",
]
