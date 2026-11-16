"""Pydantic schema exports for the NavIC backend.

Schema classes are defined next to the path operations in
``navic_tcp.fastapi_app`` and resolved lazily here.
"""

from __future__ import annotations

from backend.python_fastapi.application._lazy import make_getattr

__all__ = [
    "AdminLoginIn",
    "BusIn",
    "BusOut",
    "BusPassIssueIn",
    "DeviceIn",
    "DeviceOut",
    "DriverIn",
    "DriverOut",
    "FeedbackIn",
    "GeofenceIn",
    "GeofenceOut",
    "IdLoginIn",
    "LoginIn",
    "MagicLinkIn",
    "PreferencesIn",
    "RegisterAccountIn",
    "RegisterIn",
    "RouteIn",
    "RouteOut",
    "RouteStop",
    "SafetyAcknowledgeIn",
    "SafetyAlertIn",
    "SafetyResolveIn",
    "SettingIn",
    "SupportIn",
    "TicketStatusIn",
    "UserProfileIn",
    "VerifyMagicLinkIn",
]

_EXPORTS = {
    name: ("backend.python_pydantic.schemas.alert", name)
    for name in ("SafetyAcknowledgeIn", "SafetyAlertIn", "SafetyResolveIn")
}
_EXPORTS.update(
    {
        name: ("backend.python_pydantic.schemas.auth", name)
        for name in ("AdminLoginIn", "LoginIn", "MagicLinkIn", "VerifyMagicLinkIn")
    }
)
_EXPORTS.update({"RegisterIn": ("backend.python_pydantic.schemas.email_verification", "RegisterIn")})
_EXPORTS.update(
    {
        name: ("backend.python_pydantic.schemas.id_auth", name)
        for name in ("IdLoginIn", "RegisterAccountIn")
    }
)
_EXPORTS.update(
    {
        name: ("backend.python_pydantic.schemas.fleet", name)
        for name in (
            "BusIn",
            "BusOut",
            "DriverIn",
            "DriverOut",
            "GeofenceIn",
            "GeofenceOut",
            "RouteIn",
            "RouteOut",
            "RouteStop",
            "SettingIn",
        )
    }
)
_EXPORTS.update(
    {name: ("backend.python_pydantic.schemas.telemetry", name) for name in ("DeviceIn", "DeviceOut")}
)
_EXPORTS.update(
    {
        name: ("backend.python_pydantic.schemas.user", name)
        for name in (
            "BusPassIssueIn",
            "FeedbackIn",
            "PreferencesIn",
            "SupportIn",
            "TicketStatusIn",
            "UserProfileIn",
        )
    }
)

__getattr__ = make_getattr(__name__, _EXPORTS)
