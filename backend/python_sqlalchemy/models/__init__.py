"""SQLAlchemy model exports for the NavIC backend.

Models are defined once in ``navic_tcp.models`` so the TCP application and the
website share the same schema.  Domain modules re-export them and this package
resolves the names lazily.
"""

from __future__ import annotations

from backend.python_fastapi.application._lazy import make_getattr

__all__ = [
    "Alert",
    "AlertIncident",
    "AuditLog",
    "AuthSession",
    "Bus",
    "DeviceGeofenceState",
    "Driver",
    "Feedback",
    "Geofence",
    "GeofenceIncident",
    "LocationHistory",
    "MagicLinkToken",
    "Route",
    "SafetyAlert",
    "ShareToken",
    "StudentBusPass",
    "SupportTicket",
    "SystemSetting",
    "TrackingDevice",
    "User",
    "UserPreferences",
]

_EXPORTS = {
    "Alert": ("backend.python_sqlalchemy.models.alert", "Alert"),
    "AlertIncident": ("backend.python_sqlalchemy.models.alert", "AlertIncident"),
    "SafetyAlert": ("backend.python_sqlalchemy.models.alert", "SafetyAlert"),
    "Bus": ("backend.python_sqlalchemy.models.fleet", "Bus"),
    "Driver": ("backend.python_sqlalchemy.models.fleet", "Driver"),
    "Geofence": ("backend.python_sqlalchemy.models.fleet", "Geofence"),
    "GeofenceIncident": ("backend.python_sqlalchemy.models.fleet", "GeofenceIncident"),
    "Route": ("backend.python_sqlalchemy.models.fleet", "Route"),
    "TrackingDevice": ("backend.python_sqlalchemy.models.fleet", "TrackingDevice"),
    "ShareToken": ("backend.python_sqlalchemy.models.fleet", "ShareToken"),
    "AuditLog": ("backend.python_sqlalchemy.models.system", "AuditLog"),
    "SystemSetting": ("backend.python_sqlalchemy.models.system", "SystemSetting"),
    "DeviceGeofenceState": ("backend.python_sqlalchemy.models.telemetry", "DeviceGeofenceState"),
    "LocationHistory": ("backend.python_sqlalchemy.models.telemetry", "LocationHistory"),
    "AuthSession": ("backend.python_sqlalchemy.models.user", "AuthSession"),
    "Feedback": ("backend.python_sqlalchemy.models.user", "Feedback"),
    "MagicLinkToken": ("backend.python_sqlalchemy.models.user", "MagicLinkToken"),
    "StudentBusPass": ("backend.python_sqlalchemy.models.user", "StudentBusPass"),
    "SupportTicket": ("backend.python_sqlalchemy.models.user", "SupportTicket"),
    "User": ("backend.python_sqlalchemy.models.user", "User"),
    "UserPreferences": ("backend.python_sqlalchemy.models.user", "UserPreferences"),
}

__getattr__ = make_getattr(__name__, _EXPORTS)
