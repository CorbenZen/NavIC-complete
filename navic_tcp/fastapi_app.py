"""NavIC CBTMS FastAPI application.

Responsibilities:
- REST management APIs (vehicles, drivers, routes, devices, geofences)
- telemetry persistence and alert evaluation (called from the TCP receiver)
- live WebSocket fan-out
- dashboard, reports and GNSS diagnostics data
- authentication / authorisation for production deployments
"""

import asyncio
import csv
import hashlib
import hmac
import io
import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from math import isfinite
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, joinedload, selectinload

from . import auth as auth_service
from .db import SessionLocal, engine
from .demo_simulation import DemoSimulation
from .emailer import EmailConfigurationError, EmailDeliveryError, send_magic_link
from .emailer import delivery_status as email_delivery_status
from .env import load_env_file
from .models import (
    Alert,
    AlertIncident,
    AuditLog,
    Bus,
    DeviceGeofenceState,
    Driver,
    Feedback,
    Geofence,
    GeofenceIncident,
    LocationHistory,
    MagicLinkToken,
    Route,
    ShareToken,
    StudentBusPass,
    SupportTicket,
    SystemSetting,
    TrackingDevice,
    User,
    UserPreferences,
)
from .registry import DEFAULT_REGISTRY_PATH, DeviceRegistry
from .reporting import (
    distance_km,
    finite_number,
    idle_periods,
    ordered_points,
    stationary_periods,
    trip_distance_km,
    trip_groups,
    valid_coordinates,
)
from .schema import ensure_schema
from .security import (
    LoginRateLimiter,
    SlidingWindowRateLimiter,
    hash_password,
    new_secret,
    password_needs_rehash,
    verify_password,
    verify_token,
)
from .security import (
    issue_token as _issue_token,
)
from .server import TelemetryServer
from .store import TelemetryStore
from .vehicle_status import DEMO_FRESHNESS_SECONDS, FRESHNESS_SECONDS, STATUS_LABELS, classify_vehicle_status

LOG = logging.getLogger("navic_tcp.fastapi")
load_env_file(Path(__file__).resolve().parent.parent / ".env")
APP_ENV = os.getenv("APP_ENV", "production").strip().lower()
DEVELOPMENT_MODE = APP_ENV in {"development", "dev", "local"}


def demo_auth_bypass_enabled() -> bool:
    return DEVELOPMENT_MODE and os.getenv("DEMO_AUTH_BYPASS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


DEMO_AUTH_BYPASS = demo_auth_bypass_enabled()
_jwt_secret = os.getenv("JWT_SECRET")
SECRET = _jwt_secret.encode() if _jwt_secret else secrets.token_bytes(32)
JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", "3600"))
_login_limiter = LoginRateLimiter()
_magic_ip_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("MAGIC_LINK_IP_LIMIT", "8")),
    window_seconds=int(os.getenv("MAGIC_LINK_WINDOW_SECONDS", "600")),
)
_magic_email_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("MAGIC_LINK_EMAIL_LIMIT", "3")),
    window_seconds=int(os.getenv("MAGIC_LINK_WINDOW_SECONDS", "600")),
)


# ---------------------------------------------------------------------------
# WebSocket hub
# ---------------------------------------------------------------------------


class Hub:
    def __init__(self) -> None:
        self.clients: dict[WebSocket, bool] = {}

    @property
    def count(self) -> int:
        return len(self.clients)

    async def connect(self, ws: WebSocket, *, is_admin: bool = False) -> None:
        await ws.accept()
        self.clients[ws] = is_admin

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.pop(ws, None)

    async def _send(self, ws: WebSocket, message: dict[str, Any]) -> bool:
        try:
            await asyncio.wait_for(ws.send_json(message), timeout=1.5)
            return True
        except Exception:
            # A dead or stalled socket must not hold up telemetry.
            self.disconnect(ws)
            return False

    async def publish(self, message: dict[str, Any]) -> None:
        await asyncio.gather(*(self._send(ws, message) for ws in list(self.clients)))

    async def publish_admin(self, message: dict[str, Any]) -> None:
        await asyncio.gather(*(self._send(ws, message) for ws, is_admin in list(self.clients.items()) if is_admin))


hub = Hub()
_last_vehicle_status: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class RouteStop(BaseModel):
    name: str = Field(default="Stop", max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class BusIn(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=64)
    registration_number: str = Field(min_length=1, max_length=32)
    driver_name: str | None = None
    route_name: str | None = None
    driver_id: int | None = None
    route_id: int | None = None
    device_id: str | None = None


class BusOut(BaseModel):
    id: int
    vehicle_id: str
    bus_identifier: str
    name: str
    vehicle_name: str | None = None
    make: str | None = None
    model: str | None = None
    color: str | None = None
    registration_number: str
    registration: str
    driver_id: int | None = None
    driver_name: str = "Unassigned"
    driver_phone: str | None = None
    driver_email: str | None = None
    route_id: int | None = None
    route_name: str = "Unassigned"
    route_color: str | None = None
    device_id: str | None = None
    device_name: str | None = None
    device_model: str | None = None
    imei_no: str | None = None
    status: str | None = None
    last_seen: str | None = None
    speed: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    ignition: bool | None = None
    ignition_available: bool = False
    status_key: str | None = None
    last_seen_formatted: str | None = None
    simulated: bool | None = None
    data_source: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DeviceIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    device_type: str = Field(default="unknown", min_length=1, max_length=80)
    identifier_type: str = Field(default="serial", min_length=1, max_length=40)
    bus_id: int | None = None
    simulated: bool = False
    active: bool = True

    @field_validator("device_id")
    @classmethod
    def _device_id_shape(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", value):
            raise ValueError("device_id must use 1-64 safe identifier characters")
        return value

    @field_validator("identifier_type")
    @classmethod
    def _identifier_type(cls, value: str) -> str:
        allowed = {"simulated_imei", "simulated_serial", "imei", "serial", "iccid", "device_serial"}
        if value not in allowed:
            raise ValueError("identifier_type must be one of " + ", ".join(sorted(allowed)))
        return value


class DeviceOut(DeviceIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class DriverIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    license_number: str = Field(min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    active: bool = True

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("email must look like an email address")
        return value.lower()


class DriverOut(DriverIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class RouteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    identifier: str = Field(min_length=1, max_length=64)
    start_point: str | None = Field(default=None, max_length=160)
    destination: str | None = Field(default=None, max_length=160)
    color: str = Field(default="#0f766e", max_length=16)
    stops: list[RouteStop] = Field(default_factory=list, max_length=200)

    @field_validator("color")
    @classmethod
    def _color_shape(cls, value: str) -> str:
        if not value.startswith("#") or len(value) not in {4, 7}:
            raise ValueError("color must be a hex colour such as #0f766e")
        return value


class RouteOut(RouteIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class GeofenceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0, le=100000)
    active: bool = True


class GeofenceOut(GeofenceIn):
    id: int
    model_config = ConfigDict(from_attributes=True)


class SettingIn(BaseModel):
    overspeed_kmh: float = Field(gt=0, le=300)
    device_offline_minutes: float | None = Field(default=None, ge=1, le=1440)
    eta_enabled: bool | None = Field(default=None)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class AdminLoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class UserProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=7, max_length=32)
    department: str = Field(min_length=1, max_length=120)
    usn: str | None = Field(default=None, max_length=64)

    @field_validator("full_name", "phone", "department", "usn", mode="before")
    @classmethod
    def trim_profile_values(cls, value):
        if value is None:
            return None
        return value.strip() if isinstance(value, str) else value


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: int = Field(ge=1, le=5)
    category: Literal["Bus Service", "Driver Behaviour", "Route", "Tracking Accuracy", "Application Issue", "Other"]
    comments: str = Field(min_length=3, max_length=3000)

    @field_validator("comments", mode="before")
    @classmethod
    def trim_feedback(cls, value):
        return value.strip() if isinstance(value, str) else value


class SupportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=3, max_length=180)
    category: Literal["Account", "Bus Pass", "Tracking", "Safety", "Application", "Other"]
    description: str = Field(min_length=10, max_length=4000)
    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"
    contact: str | None = Field(default=None, max_length=254)

    @field_validator("subject", "description", "contact", mode="before")
    @classmethod
    def trim_support_values(cls, value):
        return value.strip() if isinstance(value, str) else value


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    in_app_notifications: bool = True
    emergency_alerts: bool = True
    bus_arrivals: bool = True
    route_deviations: bool = True
    default_map_view: Literal["streets", "satellite"] = "streets"
    default_map_zoom: int = Field(default=12, ge=4, le=19)
    theme: Literal["system", "light", "dark"] = "system"


class BusPassIssueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    bus_id: int = Field(gt=0)
    expires_at: datetime


class TicketStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MagicLinkIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class VerifyMagicLinkIn(BaseModel):
    token: str = Field(min_length=10, max_length=512)


# ---------------------------------------------------------------------------
# Authentication helpers
# ---------------------------------------------------------------------------


def issue_token(username: str) -> str:
    return _issue_token(SECRET, username, JWT_TTL_SECONDS)


def _user_from_token(token: str) -> dict:
    claims = verify_token(SECRET, token)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == claims["sub"], User.active.is_(True)))
        if not user:
            raise ValueError("inactive or missing user")
        if not (
            user.is_email_verified
            or user.email_verified_at is not None
            or user.user_id is not None
        ):
            raise ValueError("email address is not verified")
        return {
            "id": user.id,
            "username": user.username,
            "user_id": user.user_id,
            "role": user.role,
            "active": user.active,
            "email": user.email,
            "full_name": user.full_name,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "account_type": user.account_type,
            "avatar_url": user.avatar_url,
            "phone": user.phone,
            "department": user.department,
            "usn": user.usn,
            "is_profile_complete": user.is_profile_complete,
        }


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(401, "valid bearer token required", headers={"WWW-Authenticate": "Bearer"})
    try:
        scheme, token = authorization.split(" ", 1)
    except ValueError:
        raise HTTPException(401, "valid bearer token required", headers={"WWW-Authenticate": "Bearer"}) from None
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "valid bearer token required", headers={"WWW-Authenticate": "Bearer"})
    return token


def current_user(
    authorization: str | None = Header(default=None),
    navic_session: str | None = Cookie(default=None),
) -> dict:
    """Resolve a bearer token or the opaque browser session cookie."""
    if authorization and not isinstance(authorization, str):
        authorization = None
    if navic_session is not None and not isinstance(navic_session, str):
        navic_session = None
    if authorization:
        token = _bearer_token(authorization)
        try:
            return _user_from_token(token)
        except ValueError:
            raise HTTPException(401, "token is invalid or expired", headers={"WWW-Authenticate": "Bearer"}) from None
    if navic_session:
        with SessionLocal() as db:
            resolved = auth_service.resolve_session(db, navic_session)
        if resolved is not None:
            return resolved[0]
        raise HTTPException(401, "session is invalid or expired", headers={"WWW-Authenticate": "Cookie"})
    if DEMO_AUTH_BYPASS:
        # A real browser session takes precedence above so demo mode remains
        # convenient while an explicit sign-in replaces the synthetic user.
        return {
            "id": 0,
            "username": "demo",
            "user_id": None,
            "role": "admin",
            "email": "demo@local.invalid",
            "full_name": "Demo administrator",
            "first_name": None,
            "last_name": None,
            "account_type": None,
            "avatar_url": None,
            "phone": None,
            "department": None,
            "usn": None,
            "is_profile_complete": True,
        }
    raise HTTPException(401, "authentication required", headers={"WWW-Authenticate": "Bearer"})


def management_user(user: dict = Depends(current_user)) -> dict:
    if user.get("role") not in {"admin", "transport", "transport_department", "manager"}:
        raise HTTPException(403, "management role required")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "administrator role required")
    return user


# ---------------------------------------------------------------------------
# Small data helpers
# ---------------------------------------------------------------------------


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    stamp = _as_utc(value)
    return stamp.isoformat() if stamp else None


def speed_limit(db) -> float:
    row = db.get(SystemSetting, "overspeed_kmh")
    return float(row.value) if row else float(os.getenv("OVERSPEED_KMH", "80"))


def _json_safe(value: Any) -> Any:
    """Replace non-finite values with null before strict JSON responses; other values retain their type."""
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def device_offline_seconds(db) -> float:
    row = db.get(SystemSetting, "device_offline_minutes")
    if row:
        try:
            return max(1.0, float(row.value) * 60)
        except ValueError:
            pass
    return float(os.getenv("DEVICE_OFFLINE_SECONDS", "300"))


def _interval(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def _status_for(point: LocationHistory | None, now: datetime, offline_seconds: float = 300) -> tuple[str, str]:
    """Compatibility adapter around the shared fixed-threshold classifier."""
    result = classify_vehicle_status(
        point.speed if point else None,
        point.ignition if point else None,
        point.timestamp if point else None,
        now=now,
    )
    return STATUS_LABELS[result.status], result.status_key


def latest_points(db) -> list[LocationHistory]:
    """One latest record per device, including timestamp ties."""
    inner = aliased(LocationHistory)
    latest_id = (
        select(inner.id)
        .where(inner.device_id == LocationHistory.device_id, inner.fix_valid.is_not(False))
        .correlate(LocationHistory)
        .order_by(inner.timestamp.desc(), inner.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    return list(db.scalars(select(LocationHistory).where(LocationHistory.id == latest_id)).all())


def _device_map(db) -> dict[str, TrackingDevice]:
    return {device.device_id: device for device in db.scalars(select(TrackingDevice).order_by(TrackingDevice.id)).all()}


def _bus_map(db) -> dict[int, Bus]:
    return {bus.id: bus for bus in db.scalars(select(Bus)).all()}


def _point_payload(point: LocationHistory | None) -> dict | None:
    if point is None:
        return None
    return {
        "message_id": point.message_id,
        "timestamp": _iso(point.timestamp),
        "received_at": _iso(point.received_at),
        "latitude": point.latitude,
        "longitude": point.longitude,
        "speed": point.speed,
        "course": point.course,
        "ignition": point.ignition,
        "odometer": point.odometer,
        "simulated": point.simulated,
        "data_source": getattr(point, "data_source", None)
        or ("simulator" if point.simulated else "hardware"),
        "altitude_m": point.altitude_m,
        "fix_valid": point.fix_valid,
        "satellites_in_view": point.satellites_in_view,
        "satellites_used": point.satellites_used,
        "pdop": point.pdop,
        "hdop": point.hdop,
        "vdop": point.vdop,
        "gnss": point.gnss_metadata,
    }


def _registry_entry(device: TrackingDevice, bus: Bus | None) -> dict[str, Any]:
    return {
        "device_id": device.device_id,
        "device_type": device.device_type,
        "identifier_type": device.identifier_type or "serial",
        "vehicle_id": bus.vehicle_id if bus else f"UNASSIGNED-{device.device_id}",
        "registration_number": bus.registration_number if bus else "Unassigned",
        "driver_id": str(bus.driver_id) if bus and bus.driver_id else "unassigned",
        "driver_name": (bus.driver.name if bus and bus.driver else bus.driver_name if bus else "Unassigned") or "Unassigned",
        "sim_identifier": None,
    }


def _audit(db, user: dict | None, action: str, entity: str, entity_id: Any = None, detail: str | None = None) -> None:
    try:
        db.add(
            AuditLog(
                actor=(user or {}).get("username", "unknown"),
                actor_role=(user or {}).get("role", "unknown"),
                action=action,
                entity=entity,
                entity_id=str(entity_id) if entity_id is not None else None,
                detail=(detail or "")[:500] or None,
            )
        )
    except Exception:  # audit must never break the main operation
        LOG.exception("could not append audit record")


def _ensure_tables() -> None:
    ensure_schema(engine)


def ensure_registry(registry: DeviceRegistry) -> None:
    """Create missing tables and synchronise file + database devices into memory."""
    _ensure_tables()
    with SessionLocal() as db:
        for item in registry.list():
            bus = db.scalar(select(Bus).where(Bus.vehicle_id == item["vehicle_id"]))
            if not bus:
                bus = Bus(
                    vehicle_id=item["vehicle_id"],
                    registration_number=item["registration_number"],
                    driver_name=item["driver_name"],
                )
                db.add(bus)
                db.flush()
            device = db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == item["device_id"]))
            if not device:
                db.add(
                    TrackingDevice(
                        device_id=item["device_id"],
                        device_type=item["device_type"],
                        identifier_type=item["identifier_type"],
                        bus_id=bus.id,
                        simulated=True,
                    )
                )
        db.commit()
        active_ids: set[str] = set()
        for device in db.scalars(select(TrackingDevice)).all():
            if not device.active:
                registry.remove(device.device_id)
                continue
            bus = db.get(Bus, device.bus_id) if device.bus_id else None
            registry.upsert(_registry_entry(device, bus))
            active_ids.add(device.device_id)
    # File-only registry entries remain valid; DB devices no longer present are
    # left in the registry until explicit CRUD removal.


def sync_bus_registry(db, bus_id: int | None) -> None:
    if bus_id is None:
        return
    bus = db.get(Bus, bus_id)
    for device in db.scalars(select(TrackingDevice).where(TrackingDevice.bus_id == bus_id)).all():
        if device.active:
            registry.upsert(_registry_entry(device, bus))
        else:
            registry.remove(device.device_id)


def sync_unassigned_device(db, device_id: str) -> None:
    device = db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == device_id))
    if device and device.active and device.bus_id is None:
        registry.upsert(_registry_entry(device, None))


def sync_device_registry(db, device: TrackingDevice) -> None:
    if not device.active:
        registry.remove(device.device_id)
        return
    bus = db.get(Bus, device.bus_id) if device.bus_id else None
    registry.upsert(_registry_entry(device, bus))


# ---------------------------------------------------------------------------
# Telemetry ingestion
# ---------------------------------------------------------------------------


async def on_telemetry(message: dict[str, Any]) -> None:
    """Persist one validated, unique telemetry frame and broadcast accepted fixes."""
    persisted = False
    should_broadcast = False
    broadcast_payload: dict[str, Any] | None = None

    try:
        incoming_stamp = datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, TypeError, ValueError):
        LOG.warning("ignored telemetry with invalid timestamp")
        return
    incoming_stamp = _as_utc(incoming_stamp)
    now = datetime.now(timezone.utc)
    if incoming_stamp is None or (incoming_stamp - now).total_seconds() > 120:
        LOG.warning("ignored telemetry with timestamp beyond clock-skew tolerance device=%s", message.get("device_id", "unknown"))
        return

    with SessionLocal() as db:
        device = db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == message["device_id"]))
        if device is None:
            LOG.warning("telemetry for unknown device %s", message["device_id"])
            return
        previous = db.scalar(
            select(LocationHistory)
            .where(LocationHistory.device_id == device.device_id, LocationHistory.fix_valid.is_not(False))
            .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
            .limit(1)
        )
        gnss = message.get("gnss") or {}
        point = LocationHistory(
            device_id=device.device_id,
            message_id=message["message_id"],
            timestamp=incoming_stamp,
            latitude=message["latitude"],
            longitude=message["longitude"],
            speed=message["speed"],
            course=message["course"],
            ignition=message.get("ignition"),
            odometer=message.get("odometer"),
            simulated=message.get("simulated", False),
            data_source=message.get("data_source")
            or ("simulator" if message.get("simulated") else "hardware"),
            altitude_m=gnss.get("altitude_m"),
            fix_valid=gnss.get("fix_valid"),
            satellites_in_view=gnss.get("satellites_in_view"),
            satellites_used=gnss.get("satellites_used"),
            pdop=gnss.get("pdop"),
            hdop=gnss.get("hdop"),
            vdop=gnss.get("vdop"),
            gnss_metadata=gnss or None,
        )
        previous_time = _as_utc(previous.timestamp) if previous else None
        point_time = _as_utc(point.timestamp)
        should_broadcast = point.fix_valid is not False and (previous is None or (point_time is not None and previous_time is not None and point_time >= previous_time))
        db.add(point)
        try:
            db.flush()
            if should_broadcast:
                limit = speed_limit(db)
                if point.speed > limit and (previous is None or previous.speed is None or previous.speed <= limit):
                    db.add(
                        Alert(
                            event_type="overspeed",
                            device_id=device.device_id,
                            message=f"Speed {point.speed:.1f} km/h exceeded configured {limit:.1f} km/h limit",
                        )
                    )
                for fence in db.scalars(select(Geofence).where(Geofence.active.is_(True))).all():
                    delta = distance_km(
                        SimpleNamespace(latitude=point.latitude, longitude=point.longitude),
                        SimpleNamespace(latitude=fence.latitude, longitude=fence.longitude),
                    ) * 1000
                    inside = delta <= fence.radius_m
                    state = db.get(DeviceGeofenceState, (device.device_id, fence.id))
                    if state is None:
                        state = DeviceGeofenceState(
                            device_id=device.device_id,
                            geofence_id=fence.id,
                            inside=inside,
                            consecutive_inside=1 if inside else 0,
                            consecutive_outside=0 if inside else 1,
                        )
                        db.add(state)
                    else:
                        # Hysteresis: require 2 consecutive fixes in new state before transitioning
                        if inside:
                            state.consecutive_inside += 1
                            state.consecutive_outside = 0
                        else:
                            state.consecutive_outside += 1
                            state.consecutive_inside = 0
                        
                        # Check for transition (require 2 consecutive)
                        should_transition = False
                        new_state = state.inside
                        if inside and not state.inside and state.consecutive_inside >= 2:
                            should_transition = True
                            new_state = True
                        elif not inside and state.inside and state.consecutive_outside >= 2:
                            should_transition = True
                            new_state = False
                        
                        if should_transition:
                            # Create incident
                            incident = GeofenceIncident(
                                device_id=device.device_id,
                                geofence_id=fence.id,
                                state="inside" if new_state else "outside",
                                transitioned_at=now,
                            )
                            db.add(incident)
                            
                            # Also create alert for backward compatibility
                            event = "geofence_entry" if new_state else "geofence_exit"
                            db.add(
                                Alert(
                                    event_type=event,
                                    device_id=device.device_id,
                                    message=f"{device.device_id} {event.replace('_', ' ')}: {fence.name}",
                                )
                            )
                            
                            state.inside = new_state
                            state.consecutive_inside = 1 if new_state else 0
                            state.consecutive_outside = 0 if new_state else 1
                        else:
                            state.inside = state.inside  # No change, just update counters
            db.commit()
            persisted = True
            bus = db.get(Bus, device.bus_id) if device.bus_id else None
            status_point = point if point.fix_valid is not False else previous
            # Use shorter offline window for demo devices
            is_demo = message.get("scenario") == "demo"
            freshness = DEMO_FRESHNESS_SECONDS if is_demo else FRESHNESS_SECONDS
            classification = classify_vehicle_status(
                status_point.speed if status_point else None,
                status_point.ignition if status_point else None,
                status_point.timestamp if status_point else None,
                now=now,
                freshness_seconds=freshness,
            )
            if should_broadcast:
                _last_vehicle_status[device.device_id] = classification.status
            broadcast_payload = {
                "type": "location",
                "device_id": message["device_id"],
                "message_id": message["message_id"],
                "bus_id": bus.id if bus else None,
                "vehicle_id": bus.vehicle_id if bus else None,
                "registration_number": bus.registration_number if bus else None,
                "driver_name": (bus.driver.name if bus and bus.driver else bus.driver_name) if bus else None,
                "driver_phone": bus.driver.phone if bus and bus.driver else None,
                "driver_email": bus.driver.email if bus and bus.driver else None,
                "route_name": (bus.route.name if bus and bus.route else bus.route_name) if bus else None,
                "device_name": device.device_id,
                "device_model": device.device_type,
                "imei_no": device.device_id if device.identifier_type in {"imei", "simulated_imei"} else None,
                "timestamp": message["timestamp"],
                "latitude": message["latitude"],
                "longitude": message["longitude"],
                "speed": message["speed"],
                "course": message["course"],
                "ignition": message.get("ignition"),
                "ignition_available": message.get("ignition") is not None,
                "status": classification.status,
                "status_key": classification.status_key,
                "status_reason": classification.reason,
                "age_seconds": classification.age_seconds,
                "odometer": message.get("odometer"),
                "simulated": message.get("simulated", False),
                "data_source": point.data_source
                or ("simulator" if message.get("simulated") else "hardware"),
                "gnss": message.get("gnss"),
                "server_time": datetime.now(timezone.utc).isoformat(),
            }
        except IntegrityError:
            db.rollback()
            LOG.info("duplicate message id ignored device=%s", message["device_id"])
            return

    if persisted and should_broadcast and broadcast_payload is not None:
        await hub.publish(broadcast_payload)


def create_offline_alerts(db, now: datetime | None = None) -> int:
    """Create offline alert incidents: one incident per outage, with alerts linked to it.
    Returns the number of new alerts created (preserves old API contract for tests)."""
    now = now or datetime.now(timezone.utc)
    threshold = device_offline_seconds(db)
    created_alerts = 0
    
    for device in db.scalars(select(TrackingDevice)).all():
        if not device.active:
            continue
        point = db.scalar(
            select(LocationHistory)
            .where(LocationHistory.device_id == device.device_id)
            .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
            .limit(1)
        )
        if not point:
            continue
        stamp = _as_utc(point.timestamp)
        if stamp is None or (now - stamp).total_seconds() <= threshold:
            # Device has recent telemetry - check if there's an open incident to resolve
            open_incident = db.scalar(
                select(AlertIncident)
                .where(
                    AlertIncident.device_id == device.device_id,
                    AlertIncident.event_type == "device_offline",
                    AlertIncident.state == "open"
                )
                .order_by(AlertIncident.opened_at.desc())
                .limit(1)
            )
            if open_incident:
                open_incident.state = "resolved"
                open_incident.resolved_at = now
                open_incident.last_seen_at = stamp
                open_incident.updated_at = now
            continue
        
        # Device is offline - check for existing open incident
        open_incident = db.scalar(
            select(AlertIncident)
            .where(
                AlertIncident.device_id == device.device_id,
                AlertIncident.event_type == "device_offline",
                AlertIncident.state == "open"
            )
            .order_by(AlertIncident.opened_at.desc())
            .limit(1)
        )
        
        if open_incident:
            # Existing open incident - check 30-minute cooldown for new alert
            latest_alert = db.scalar(
                select(Alert)
                .where(Alert.incident_id == open_incident.id)
                .order_by(Alert.created_at.desc())
                .limit(1)
            )
            if latest_alert:
                alert_time = _as_utc(latest_alert.created_at)
                if alert_time and (now - alert_time).total_seconds() < 1800:
                    # Cooldown not expired - don't create new alert
                    continue
            
            # Cooldown expired - add new alert to existing incident
            open_incident.alert_count += 1
            open_incident.last_seen_at = stamp
            open_incident.updated_at = now
            incident = open_incident
        else:
            # New outage - create new incident
            incident = AlertIncident(
                device_id=device.device_id,
                event_type="device_offline",
                state="open",
                opened_at=now,
                last_seen_at=stamp,
                alert_count=1,
                is_read=False,
            )
            db.add(incident)
            db.flush()
        
        # Create alert linked to incident
        db.add(
            Alert(
                event_type="device_offline",
                device_id=device.device_id,
                incident_id=incident.id,
                message=f"No location telemetry received from {device.device_id} for more than {int(threshold / 60)} minutes",
            )
        )
        created_alerts += 1
    
    db.commit()
    return created_alerts


async def offline_alert_loop() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            with SessionLocal() as db:
                create_offline_alerts(db)
            await evaluate_vehicle_status_transitions()
        except Exception:
            LOG.exception("vehicle freshness and offline alert scan failed")


async def evaluate_vehicle_status_transitions(now: datetime | None = None) -> int:
    """Publish fresh-to-stale transitions using the existing periodic scan."""
    now = now or datetime.now(timezone.utc)
    outgoing: list[dict[str, Any]] = []
    with SessionLocal() as db:
        devices = list(db.scalars(select(TrackingDevice).where(TrackingDevice.active.is_(True))).all())
        points = {point.device_id: point for point in latest_points(db)}
        for device in devices:
            point = points.get(device.device_id)
            if point is None:
                continue
            result = classify_vehicle_status(point.speed, point.ignition, point.timestamp, now=now)
            previous = _last_vehicle_status.setdefault(device.device_id, result.status)
            if previous == result.status:
                continue
            _last_vehicle_status[device.device_id] = result.status
            bus = db.get(Bus, device.bus_id) if device.bus_id else None
            outgoing.append({
                "type": "vehicle_status",
                "device_id": device.device_id,
                "bus_id": bus.id if bus else None,
                "vehicle_id": bus.vehicle_id if bus else None,
                "registration_number": bus.registration_number if bus else None,
                "timestamp": _iso(point.timestamp),
                "server_time": now.isoformat(),
                "latitude": point.latitude,
                "longitude": point.longitude,
                "speed": point.speed,
                "ignition": point.ignition,
                "ignition_available": point.ignition is not None,
                "status": result.status,
                "status_key": result.status_key,
                "status_reason": result.reason,
                "age_seconds": result.age_seconds,
            })
    for event in outgoing:
        await hub.publish(event)
    return len(outgoing)


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app):
    if not DEVELOPMENT_MODE and not _jwt_secret:
        raise RuntimeError("JWT_SECRET must be configured outside development")
    ensure_schema(engine)
    ensure_registry(registry)
    app.state.started_at = datetime.now(timezone.utc)
    offline_task = asyncio.create_task(offline_alert_loop())
    
    # Initialize demo simulation (only in development or when explicitly enabled)
    demo_enabled = os.getenv("DEMO_SIMULATION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    if demo_enabled or DEVELOPMENT_MODE:
        app.state.demo_simulation = DemoSimulation(on_telemetry)
    else:
        app.state.demo_simulation = None
    
    try:
        if os.getenv("TCP_ENABLED", "true").lower() == "true":
            app.state.tcp = TelemetryServer(
                os.getenv("TCP_HOST", "127.0.0.1"),
                int(os.getenv("TCP_PORT", "5000")),
                store=TelemetryStore(registry=registry),
                on_telemetry=on_telemetry,
            )
            await app.state.tcp.start()
        yield
    finally:
        offline_task.cancel()
        await asyncio.gather(offline_task, return_exceptions=True)
        if hasattr(app.state, "tcp"):
            await app.state.tcp.close()
        if app.state.demo_simulation and app.state.demo_simulation.is_running:
            await app.state.demo_simulation.stop()


app = FastAPI(
    title="NavIC Fleet API",
    version="2.0.0",
    description="College Bus Tracking and Management System API",
    lifespan=lifespan,
)
_cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-CSRF-Token"],
)


def _allowed_browser_origins() -> set[str]:
    return {
        *[origin for origin in _cors_origins],
        auth_service.frontend_base_url(),
    }


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    """Double-submit CSRF protection for cookie-authenticated writes.

    Bearer-token clients are exempt because browsers do not attach bearer
    headers automatically.  Browser sessions additionally pass an Origin check
    and are checked against the CSRF hash stored on the session row.
    """
    if request.method in auth_service.SAFE_METHODS:
        return await call_next(request)
    public_auth_paths = {
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/verify-email",
        "/api/auth/resend-verification",
        "/auth/login",
        "/auth/admin-login",
        "/auth/login/id",
        "/auth/register",
        "/auth/magic-link",
        "/auth/magic-link/verify",
        "/auth/verify-email",
        "/auth/resend-verification",
    }
    if request.url.path in public_auth_paths:
        # Sign-in and other public auth requests must remain reachable when a
        # browser sends an expired session cookie. Check Origin when present,
        # but don't require a CSRF token tied to the session being replaced.
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in _allowed_browser_origins():
            return JSONResponse(status_code=403, content={"detail": "cross-origin request blocked"})
        return await call_next(request)
    session_cookie = request.cookies.get(auth_service.SESSION_COOKIE)
    if not session_cookie or request.headers.get("authorization"):
        return await call_next(request)

    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in _allowed_browser_origins():
        return JSONResponse(status_code=403, content={"detail": "cross-origin request blocked"})
    header_value = request.headers.get("x-csrf-token")
    cookie_value = request.cookies.get(auth_service.CSRF_COOKIE)
    if not header_value or not cookie_value or not hmac.compare_digest(header_value, cookie_value):
        return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})
    with SessionLocal() as db:
        resolved = auth_service.resolve_session(db, session_cookie)
        if resolved is None:
            return JSONResponse(status_code=401, content={"detail": "session is invalid or expired"})
        if not auth_service.csrf_matches(resolved[1], header_value):
            return JSONResponse(status_code=403, content={"detail": "CSRF token does not match the session"})
    return await call_next(request)


registry = DeviceRegistry.load(os.getenv("DEVICE_REGISTRY", str(DEFAULT_REGISTRY_PATH)))


# ---------------------------------------------------------------------------
# Health, metadata and authentication
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    database = "ok"
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        LOG.exception("database health check failed")
        database = "error"
    tcp = "disabled"
    if hasattr(app.state, "tcp"):
        tcp = "listening" if getattr(app.state.tcp, "_server", None) is not None else "stopped"
    payload = {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "tcp": tcp,
        "environment": APP_ENV,
        "version": app.version,
        "websocket_clients": hub.count,
    }
    return JSONResponse(status_code=200 if database == "ok" else 503, content=payload)


@app.get("/auth/csrf")
def csrf_token(request: Request):
    """Return the session's CSRF value to an allowed cross-origin frontend.

    CORS limits which browser origins can read this response; the value is
    still checked against the authenticated session before writes are allowed.
    """
    session_cookie = request.cookies.get(auth_service.SESSION_COOKIE)
    csrf_cookie = request.cookies.get(auth_service.CSRF_COOKIE)
    if not session_cookie or not csrf_cookie:
        raise HTTPException(401, "authenticated session required")
    with SessionLocal() as db:
        resolved = auth_service.resolve_session(db, session_cookie)
        if resolved is None:
            raise HTTPException(401, "session is invalid or expired")
        if not auth_service.csrf_matches(resolved[1], csrf_cookie):
            raise HTTPException(403, "CSRF token is invalid")
    return {"csrf_token": csrf_cookie}


@app.get("/api/meta")
def meta():
    return {
        "application": "NavIC CBTMS",
        "version": app.version,
        "environment": APP_ENV,
        "development_mode": DEVELOPMENT_MODE,
        "auth_required": not DEMO_AUTH_BYPASS,
        "dev_anonymous": DEMO_AUTH_BYPASS,
        "demo_auth_bypass": DEMO_AUTH_BYPASS,
        "device_auth_required": bool(os.getenv("DEVICE_AUTH_TOKEN")),
        "tcp": {
            "enabled": os.getenv("TCP_ENABLED", "true").lower() == "true",
            "host": os.getenv("TCP_HOST", "127.0.0.1"),
            "port": int(os.getenv("TCP_PORT", "5000")),
        },
        "reports": sorted(REPORT_ALIASES | {name: name for name in REPORT_TYPES}),
        "gnss_capability": "unverified",
        "simulation_notice": "The bundled simulator always sends simulated=true. No hardware is connected by this service.",
        "auth": {
            "methods": ["id_password", "email_magic_link", "admin_password", "bearer_token"],
            "admin_email": configured_admin_email(),
            "magic_link_ttl_minutes": auth_service.magic_link_ttl_minutes(),
            "session_ttl_minutes": auth_service.session_ttl_minutes(),
            "cookie_secure": auth_service.cookie_secure(),
            "cookie_samesite": auth_service.cookie_samesite(),
            "email": {
                "provider": email_delivery_status()["provider"],
                "configured": email_delivery_status()["configured"],
                "capture_file": email_delivery_status().get("capture_file"),
            },
        },
    }


@app.post("/auth/login")
def login(data: LoginIn, request: Request, response: Response):
    """Legacy password login retained for API clients; returns a bearer token and session cookie."""
    client = client_host = request.client.host if request.client else "unknown"
    key = f"{client}:{data.username.lower()}"
    if auth_service.normalize_email(data.username) == configured_admin_email():
        raise HTTPException(401, "Invalid email or password")
    wait = _login_limiter.retry_after(key)
    if wait:
        raise HTTPException(429, f"too many failed attempts; retry in {wait} seconds", headers={"Retry-After": str(wait)})
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == data.username, User.active.is_(True)))
        if not user and "@" in data.username:
            user = db.scalar(select(User).where(User.email == data.username.lower(), User.active.is_(True)))
        if not user or user.role == "admin" or not verify_password(data.password, user.password_hash):
            _login_limiter.fail(key)
            raise HTTPException(401, "Invalid email or password")
        if not (user.is_email_verified or user.email_verified_at is not None):
            raise HTTPException(403, "Verify your email address before signing in.")
        if password_needs_rehash(user.password_hash):
            user.password_hash = hash_password(data.password)
            _audit(db, {"username": user.username, "role": user.role}, "password_rehash", "user", user.id)
        _login_limiter.reset(key)
        user.last_login_at = auth_service.now_utc()
        _audit(db, {"username": user.username, "role": user.role}, "login", "user", user.id, f"method=password client={client_host}")
        db.commit()
        raw_session, csrf_token, _expires = auth_service.create_session(db, user, request)
        auth_service.set_session_cookies(response, raw_session, csrf_token)
        return {
            "access_token": issue_token(user.username),
            "token_type": "bearer",
            "expires_in": JWT_TTL_SECONDS,
            "csrf_token": csrf_token,
            "user": {"id": user.id, "username": user.username, "email": user.email, "role": user.role},
        }


def configured_admin_email() -> str:
    return auth_service.normalize_email(os.getenv("ADMIN_EMAIL", "admin@example.invalid"))


@app.post("/auth/admin-login")
def admin_login(data: AdminLoginIn, request: Request, response: Response):
    """Authenticate the one configured administrator and establish a normal session."""
    email = auth_service.normalize_email(data.email)
    if email != configured_admin_email():
        raise HTTPException(401, "Invalid email or password")
    client = auth_service.client_ip(request)
    key = f"admin:{client}:{email}"
    wait = _login_limiter.retry_after(key)
    if wait:
        raise HTTPException(429, f"too many failed attempts; retry in {wait} seconds", headers={"Retry-After": str(wait)})
    password_hash = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
    if not password_hash.startswith("scrypt$") or not verify_password(data.password, password_hash):
        _login_limiter.fail(key)
        raise HTTPException(401, "Invalid email or password")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is not None and not user.active:
            raise HTTPException(401, "Invalid email or password")
        if user is None:
            user = User(username=email, email=email, role="admin", active=True)
            db.add(user)
            db.flush()
        # The configured credential is the sole authority for this account's role.
        user.role = "admin"
        user.email_verified_at = user.email_verified_at or auth_service.now_utc()
        user.is_email_verified = True
        user.last_login_at = auth_service.now_utc()
        _audit(db, {"username": user.username, "role": "admin"}, "login", "user", user.id, f"method=admin_password client={client}")
        db.commit()
        raw_session, csrf_token, _expires = auth_service.create_session(db, user, request)
        auth_service.set_session_cookies(response, raw_session, csrf_token)
        payload = {"id": user.id, "username": user.username, "email": user.email, "role": "admin"}
    _login_limiter.reset(key)
    return {"user": payload, "csrf_token": csrf_token, "expires_in": auth_service.session_ttl_minutes() * 60}


@app.post("/auth/magic-link", status_code=202)
def request_magic_link(data: MagicLinkIn, request: Request):
    """Send a single-use sign-in link. The response never reveals whether the address exists."""
    email = auth_service.normalize_email(data.email)
    if not auth_service.valid_email(email):
        raise HTTPException(422, "Enter a valid email address.")
    if email == configured_admin_email():
        raise HTTPException(400, "Use administrator sign-in for this account.")
    ip = auth_service.client_ip(request)
    allowed_ip, retry_ip = _magic_ip_limiter.allow(f"ip:{ip}")
    allowed_email, retry_email = _magic_email_limiter.allow(f"email:{email}")
    if not allowed_ip or not allowed_email:
        retry = max(retry_ip, retry_email, 1)
        raise HTTPException(
            429,
            "Too many sign-in emails requested. Wait a few minutes and try again.",
            headers={"Retry-After": str(retry)},
        )
    status = email_delivery_status()
    if not status["configured"]:
        raise HTTPException(
            503,
            "Email sign-in is not configured on this server. Contact the transport department administrator.",
        )
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email, User.active.is_(True)))
        if user is not None:
            raw_token, _expires = auth_service.create_magic_link(db, user, request)
            link = auth_service.build_verify_link(raw_token)
            try:
                send_magic_link(user.email, link, auth_service.magic_link_ttl_minutes())
                _audit(db, {"username": user.username, "role": user.role}, "magic_link_sent", "user", user.id, f"client={ip}")
                db.commit()
            except (EmailConfigurationError, EmailDeliveryError):
                LOG.exception("could not deliver a sign-in email for user_id=%s", user.id)
                # Do not leave an undelivered credential usable or tell the UI
                # that mail was sent. The raw token is never logged or returned.
                db.execute(
                    update(MagicLinkToken)
                    .where(MagicLinkToken.token_hash == auth_service.token_hash(raw_token))
                    .values(used_at=auth_service.now_utc())
                )
                db.commit()
                raise HTTPException(
                    503,
                    "The sign-in email could not be delivered. Check the server email configuration and try again.",
                ) from None
        else:
            # Keep the same shape/timing class for unknown addresses; no token exists.
            LOG.info("magic-link requested for an address without an active account")
    return {
        "message": "If that address belongs to an authorised account, a sign-in link has been sent.",
        "expires_in": auth_service.magic_link_ttl_minutes() * 60,
    }


@app.post("/auth/magic-link/verify")
def verify_magic_link_endpoint(data: VerifyMagicLinkIn, request: Request, response: Response):
    """Consume one email token and establish an HttpOnly browser session."""
    with SessionLocal() as db:
        user = auth_service.verify_magic_link(db, data.token)
        if user is None:
            raise HTTPException(400, "This sign-in link is invalid, expired, or has already been used.")
        if auth_service.normalize_email(user.email) == configured_admin_email():
            raise HTTPException(400, "Use administrator sign-in for this account.")
        _audit(db, {"username": user.username, "role": user.role}, "login", "user", user.id, "method=magic_link")
        db.commit()
        raw_session, csrf_token, _expires = auth_service.create_session(db, user, request)
        auth_service.set_session_cookies(response, raw_session, csrf_token)
        payload = {"id": user.id, "username": user.username, "email": user.email, "role": user.role}
    return {
        "user": payload,
        "csrf_token": csrf_token,
        "expires_in": auth_service.session_ttl_minutes() * 60,
    }


@app.post("/auth/logout")
def logout(response: Response, navic_session: str | None = Cookie(default=None)):
    """Revoke the current browser session and clear both cookies."""
    with SessionLocal() as db:
        if navic_session:
            auth_service.revoke_session(db, navic_session)
    auth_service.clear_session_cookies(response)
    return {"signed_out": True}



@app.get("/auth/me")
def me(user=Depends(current_user)):
    return user


@app.get("/api/user/me")
def user_profile(user=Depends(current_user)):
    return {
        key: user.get(key)
        for key in ("email", "full_name", "avatar_url", "phone", "department", "usn", "role", "active", "is_profile_complete")
    }


@app.put("/api/user/profile")
def update_user_profile(data: UserProfileIn, user=Depends(current_user)):
    if not user.get("id"):
        raise HTTPException(404, "User profile not found")
    with SessionLocal() as db:
        account = db.get(User, user["id"])
        if account is None or not account.active:
            raise HTTPException(404, "User profile not found")
        account.full_name = data.full_name
        account.phone = data.phone
        account.department = data.department
        account.usn = data.usn or None
        account.is_profile_complete = True
        db.commit()
        db.refresh(account)
        return {
            "id": account.id,
            "username": account.username,
            "email": account.email,
            "full_name": account.full_name,
            "avatar_url": account.avatar_url,
            "phone": account.phone,
            "department": account.department,
            "usn": account.usn,
            "role": account.role,
            "active": account.active,
            "is_profile_complete": account.is_profile_complete,
        }


@app.post("/api/feedback", status_code=201)
def create_feedback(data: FeedbackIn, user=Depends(current_user)):
    with SessionLocal() as db:
        row = Feedback(user_id=user["id"], rating=data.rating, category=data.category, comments=data.comments)
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"id": row.id, "status": row.status, "created_at": _iso(row.created_at)}


@app.post("/api/support", status_code=201)
def create_support_ticket(data: SupportIn, user=Depends(current_user)):
    with SessionLocal() as db:
        row = SupportTicket(
            ticket_number=f"NAV-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(4).upper()}",
            user_id=user["id"], subject=data.subject, category=data.category,
            description=data.description, contact=data.contact, priority=data.priority, status="OPEN",
        )
        db.add(row)
        _audit(db, user, "create", "support_ticket", row.ticket_number, f"category={data.category};priority={data.priority}")
        db.commit()
        return {"ticket_id": row.ticket_number, "status": row.status, "created_at": _iso(row.created_at)}


@app.get("/api/support/info")
def support_info():
    return {"email": os.getenv("CBTMS_SUPPORT_EMAIL", "").strip() or None, "phone": os.getenv("CBTMS_SUPPORT_PHONE", "").strip() or None}


@app.get("/api/users/me/preferences")
def get_user_preferences(user=Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(UserPreferences, user["id"])
        return row.values if row else PreferencesIn().model_dump()


@app.put("/api/users/me/preferences")
def save_user_preferences(data: PreferencesIn, user=Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(UserPreferences, user["id"])
        if row is None:
            row = UserPreferences(user_id=user["id"], values=data.model_dump())
            db.add(row)
        else:
            row.values = data.model_dump()
            row.updated_at = datetime.now(timezone.utc)
        db.commit()
        return row.values


@app.get("/api/user/bus-pass")
def my_bus_pass(user=Depends(current_user)):
    with SessionLocal() as db:
        row = db.scalar(select(StudentBusPass).where(StudentBusPass.user_id == user["id"]).order_by(StudentBusPass.id.desc()).limit(1))
        if row is None:
            return {"pass": None}
        bus = db.get(Bus, row.bus_id)
        status = row.status
        if status == "ACTIVE" and auth_service.as_utc(row.expires_at) <= datetime.now(timezone.utc):
            status = "EXPIRED"
        route = db.get(Route, bus.route_id) if bus and bus.route_id else None
        return {"pass": {
            "id": row.id, "student_name": user.get("full_name"), "usn": user.get("usn"),
            "bus_id": row.bus_id,
            "college_name": os.getenv("COLLEGE_NAME", "NavIC College"),
            "bus_registration": bus.registration_number if bus else None,
            "route_name": route.name if route else (bus.route_name if bus else None),
            "status": status, "expires_at": _iso(row.expires_at),
            "verification_url": f"{(os.getenv('PUBLIC_API_URL', '').strip() or os.getenv('BACKEND_URL', '').strip() or auth_service.frontend_base_url()).rstrip('/')}/api/bus-pass/verify/{row.pass_token}",
        }}


@app.post("/api/admin/bus-passes", status_code=201)
def issue_bus_pass(data: BusPassIssueIn, user=Depends(admin_user)):
    email = auth_service.normalize_email(data.email)
    with SessionLocal() as db:
        account = db.scalar(select(User).where(func.lower(User.email) == email))
        bus = db.get(Bus, data.bus_id)
        if account is None or bus is None:
            raise HTTPException(404, "user or bus not found")
        expires = data.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires <= datetime.now(timezone.utc):
            raise HTTPException(422, "expiry must be in the future")
        prior = db.scalars(select(StudentBusPass).where(StudentBusPass.user_id == account.id, StudentBusPass.status == "ACTIVE")).all()
        for item in prior:
            item.status = "SUSPENDED"
        row = StudentBusPass(user_id=account.id, bus_id=bus.id, pass_token=new_secret(24), status="ACTIVE", expires_at=expires)
        db.add(row)
        _audit(db, user, "issue", "bus_pass", account.id, f"bus_id={bus.id}")
        db.commit()
        return {"user_id": account.id, "pass_id": row.id, "status": row.status}


@app.get("/api/bus-pass/verify/{token}")
def verify_bus_pass(token: str):
    if len(token) < 20 or len(token) > 64:
        raise HTTPException(404, "pass not found")
    with SessionLocal() as db:
        row = db.scalar(select(StudentBusPass).where(StudentBusPass.pass_token == token))
        if row is None:
            raise HTTPException(404, "pass not found")
        status = row.status
        if status == "ACTIVE" and auth_service.as_utc(row.expires_at) <= datetime.now(timezone.utc):
            status = "EXPIRED"
        return {"valid": status == "ACTIVE", "status": status, "college_name": os.getenv("COLLEGE_NAME", "NavIC College")}


@app.get("/api/user/terms")
def user_terms():
    return {"title": "CBTMS usage and privacy terms", "approval_required": True, "sections": [
        {"title": "Usage policy", "body": "Use CBTMS only for legitimate college transport and support purposes. Final institutional policy text requires approval."},
        {"title": "Privacy and GPS data", "body": "Vehicle location is collected from installed tracking devices."},
        {"title": "User responsibilities", "body": "Provide accurate information, protect account access and use emergency reporting only for genuine concerns."},
        {"title": "Acceptable use and reporting", "body": "Do not misuse, disrupt or attempt to access data outside your authorization. Use Support to report issues."},
    ]}


# ---------------------------------------------------------------------------
# Demo Simulation (admin only, development only)
# ---------------------------------------------------------------------------


class DemoSimStartIn(BaseModel):
    speed_multiplier: float = Field(default=1.0, ge=0.5, le=4.0)


class DemoSimStateOut(BaseModel):
    running: bool
    devices: list[str]
    speed_multiplier: float
    states: dict[str, str]
    last_changes: list[dict]
    auto_stop_at: str | None


@app.post("/api/admin/demo/simulation/start")
async def start_demo_simulation(config: DemoSimStartIn, user=Depends(admin_user)):
    """Start the demo simulation (admin only, development only)."""
    sim = app.state.demo_simulation
    if not sim:
        raise HTTPException(403, "Demo simulation is disabled. Set DEMO_SIMULATION_ENABLED=1 to enable.")
    if sim.is_running:
        raise HTTPException(409, "Simulation already running")
    task = asyncio.create_task(sim.start(speed_multiplier=config.speed_multiplier))
    app.state.simulation_task = task
    task.add_done_callback(lambda t: setattr(app.state, "simulation_task", None))
    return {"started": True, "speed_multiplier": config.speed_multiplier}


@app.post("/api/admin/demo/simulation/stop")
async def stop_demo_simulation(user=Depends(admin_user)):
    """Stop the demo simulation (admin only)."""
    sim = app.state.demo_simulation
    if not sim:
        raise HTTPException(403, "Demo simulation is disabled.")
    if not sim.is_running:
        raise HTTPException(409, "Simulation not running")
    await sim.stop()
    return {"stopped": True}


@app.get("/api/admin/demo/simulation/state", response_model=DemoSimStateOut)
async def demo_simulation_state(user=Depends(admin_user)):
    """Get current demo simulation state (admin only)."""
    sim = app.state.demo_simulation
    if not sim:
        return DemoSimStateOut(running=False, devices=[], speed_multiplier=1.0, states={}, last_changes=[], auto_stop_at=None)
    state = sim.get_state()
    return DemoSimStateOut(
        running=state["running"],
        devices=state["devices"],
        speed_multiplier=state["speed_multiplier"],
        states=state["states"],
        last_changes=state["last_changes"],
        auto_stop_at=state["auto_stop_at"],
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def _fleet_snapshot(db) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    offline_seconds = FRESHNESS_SECONDS
    buses = list(db.scalars(select(Bus).options(joinedload(Bus.driver), joinedload(Bus.route)).order_by(Bus.id)).all())
    devices = _device_map(db)
    active_device_by_bus: dict[int, TrackingDevice] = {}
    for candidate in devices.values():
        if candidate.active and candidate.bus_id is not None:
            active_device_by_bus.setdefault(candidate.bus_id, candidate)
    latest = latest_points(db)
    point_by_device = {point.device_id: point for point in latest}

    fleet = {"total": len(buses), "moving": 0, "on_move": 0, "stopped": 0, "idle": 0, "offline": 0, "no_data": 0, "toing": 0}
    recent: list[dict] = []
    bus_points: dict[int, LocationHistory] = {}
    for bus in buses:
        device = active_device_by_bus.get(bus.id)
        point = point_by_device.get(device.device_id) if device else None
        classification = classify_vehicle_status(point.speed if point else None, point.ignition if point else None, point.timestamp if point else None, now=now)
        status, key = STATUS_LABELS[classification.status], classification.status_key
        if point:
            bus_points[bus.id] = point
        if key == "on_move":
            fleet["on_move"] += 1
            fleet["moving"] += 1  # legacy summary key
        elif key in {"stopped", "idle", "toing"}:
            fleet[key] += 1
        elif key == "out_of_network":
            fleet["no_data" if point is None else "offline"] += 1
        recent.append(
            {
                "bus_id": bus.id,
                "vehicle_id": bus.vehicle_id,
                "registration_number": bus.registration_number,
                "driver_name": bus.driver.name if bus.driver else (bus.driver_name or "Unassigned"),
                "driver_phone": bus.driver.phone if bus.driver else None,
                "driver_email": bus.driver.email if bus.driver else None,
                "route_name": bus.route.name if bus.route else (bus.route_name or "Unassigned"),
                "device_id": device.device_id if device else None,
                "status": status,
                "status_key": key,
                "last_seen": _iso(point.timestamp) if point else None,
                "age_seconds": classification.age_seconds,
                "speed": point.speed if point else None,
                "latitude": point.latitude if point else None,
                "longitude": point.longitude if point else None,
                "ignition": point.ignition if point else None,
                "ignition_available": bool(point and point.ignition is not None),
                "status_reason": classification.reason,
                "simulated": point.simulated if point else None,
            }
        )
    recent.sort(key=lambda row: row["last_seen"] or "", reverse=True)

    all_devices = list(devices.values())
    device_rows = []
    for device in all_devices:
        point = point_by_device.get(device.device_id)
        stamp = _as_utc(point.timestamp) if point else None
        fresh = bool(stamp and (now - stamp).total_seconds() <= offline_seconds)
        runtime = app.state.tcp.store.get_device(device.device_id) if hasattr(app.state, "tcp") else None
        device_rows.append(
            {
                "device_id": device.device_id,
                "device_type": device.device_type,
                "active": device.active,
                "simulated": bool(device.simulated or (point and point.simulated)),
                "registry_simulated": device.simulated,
                "assigned": device.bus_id is not None,
                "tcp_online": bool(runtime and runtime.get("online")),
                "telemetry_fresh": fresh,
                "last_seen": _iso(point.timestamp) if point else None,
            }
        )

    # Seven-day activity, computed from persisted telemetry only.
    start_day = (now - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
    week_points = list(
        db.scalars(
            select(LocationHistory)
            .where(LocationHistory.timestamp >= start_day)
            .order_by(LocationHistory.device_id, LocationHistory.timestamp, LocationHistory.id)
            .limit(50000)
        ).all()
    )
    buckets: dict[str, dict[str, Any]] = {}
    for offset in range(7):
        day = (start_day + timedelta(days=offset)).date().isoformat()
        buckets[day] = {"date": day, "fixes": 0, "distance_km": 0.0, "vehicles": set()}
    previous_by_device: dict[str, LocationHistory] = {}
    for point in week_points:
        day = _as_utc(point.timestamp).date().isoformat() if _as_utc(point.timestamp) else None
        if day not in buckets:
            continue
        buckets[day]["fixes"] += 1
        buckets[day]["vehicles"].add(point.device_id)
        previous = previous_by_device.get(point.device_id)
        if previous is not None:
            seconds = (_as_utc(point.timestamp) - _as_utc(previous.timestamp)).total_seconds()
            segment = distance_km(previous, point)
            if 0 <= seconds <= 1800 and segment <= 100:
                buckets[day]["distance_km"] += segment
        previous_by_device[point.device_id] = point
    activity = [
        {
            "date": item["date"],
            "fixes": item["fixes"],
            "distance_km": round(item["distance_km"], 2),
            "vehicles": len(item["vehicles"]),
        }
        for item in buckets.values()
    ]

    unread = db.scalar(select(func.count(Alert.id)).where(Alert.is_read.is_(False))) or 0
    alerts = list(db.scalars(select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc()).limit(6)).all())
    routes = list(db.scalars(select(Route).order_by(Route.id)).all())
    driver_total = db.scalar(select(func.count(Driver.id))) or 0
    driver_active = db.scalar(select(func.count(Driver.id)).where(Driver.active.is_(True))) or 0

    assigned_bus_ids = {device.bus_id for device in all_devices if device.bus_id is not None and device.active}
    return {
        "generated_at": now.isoformat(),
        "offline_after_seconds": FRESHNESS_SECONDS,
        "fleet": fleet,
        "devices": {
            "total": len(device_rows),
            "tcp_online": sum(1 for item in device_rows if item["tcp_online"]),
            "telemetry_fresh": sum(1 for item in device_rows if item["telemetry_fresh"]),
            "inactive": sum(1 for item in device_rows if not item["active"]),
            "simulated": sum(1 for item in device_rows if item["simulated"]),
            "assigned": sum(1 for item in device_rows if item["assigned"]),
        },
        "drivers": {"total": driver_total, "active": driver_active},
        "routes": {
            "total": len(routes),
            "assigned_vehicles": len([bus_id for bus_id in assigned_bus_ids if bus_id]),
        },
        "alerts": {
            "unread": unread,
            "recent": [
                {
                    "id": alert.id,
                    "event_type": alert.event_type,
                    "message": alert.message,
                    "device_id": alert.device_id,
                    "created_at": _iso(alert.created_at),
                    "is_read": alert.is_read,
                }
                for alert in alerts
            ],
        },
        "activity": activity,
        "recent": recent[:8],
        "devices_list": sorted(device_rows, key=lambda item: item["last_seen"] or "", reverse=True)[:12],
        "simulation": {
            "simulated_devices": sum(
                1
                for device in all_devices
                if device.simulated or (point_by_device.get(device.device_id) and point_by_device[device.device_id].simulated)
            ),
            "simulator_registry_devices": sum(1 for device in all_devices if device.simulated),
            "simulated_fixes": sum(1 for point in latest if point.simulated),
        },
    }


@app.get("/api/dashboard/summary")
def dashboard_summary(user=Depends(current_user)):
    with SessionLocal() as db:
        return _fleet_snapshot(db)


@app.get("/api/dashboard/admin-summary")
def dashboard_admin_summary(user=Depends(admin_user)):
    """Return only the counts and navigation targets for admin dashboard panels."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        buses = list(db.scalars(select(Bus)).all())
        devices = list(db.scalars(select(TrackingDevice).where(TrackingDevice.active.is_(True))).all())
        latest_by_device = {point.device_id: point for point in latest_points(db)}

        offline_devices = 0
        stale_devices = 0
        for device in devices:
            runtime = app.state.tcp.store.get_device(device.device_id) if hasattr(app.state, "tcp") else None
            online = bool(runtime and runtime.get("online"))
            point = latest_by_device.get(device.device_id)
            stamp = _as_utc(point.timestamp) if point else None
            fresh = bool(stamp and (now - stamp).total_seconds() <= FRESHNESS_SECONDS)
            if not online:
                offline_devices += 1
            elif not fresh:
                stale_devices += 1

        assigned_bus_ids = {device.bus_id for device in devices if device.bus_id is not None}
        no_device = sum(1 for bus in buses if bus.id not in assigned_bus_ids)
        no_driver = sum(1 for bus in buses if bus.driver_id is None)
        no_route = sum(1 for bus in buses if bus.route_id is None)
        unread = db.scalar(select(func.count(Alert.id)).where(Alert.is_read.is_(False))) or 0
        multi_driver_count = db.scalar(
            select(func.count()).select_from(
                select(Bus.driver_id)
                .where(Bus.driver_id.is_not(None))
                .group_by(Bus.driver_id)
                .having(func.count(Bus.id) > 1)
                .subquery()
            )
        ) or 0
        test_like = sum(
            1 for bus in buses
            if re.match(r"^(test|demo|sim|bus\s*\d+$)", bus.vehicle_id or "", re.I)
            or re.match(r"^(test|demo|sim)", bus.registration_number or "", re.I)
        )

    # The client supplies labels/descriptions. The server returns no fleet rows or identifiers.
    return {
        "attention": [
            {"key": "offline-devices", "count": offline_devices, "target": "/devices?filter=offline"},
            {"key": "stale-telemetry", "count": stale_devices, "target": "/devices?filter=stale"},
            {"key": "unread-alerts", "count": unread, "target": "/alerts?unread=true"},
            {"key": "vehicles-no-device", "count": no_device, "target": "/vehicles"},
            {"key": "vehicles-no-driver", "count": no_driver, "target": "/vehicles"},
            {"key": "vehicles-no-route", "count": no_route, "target": "/vehicles"},
        ],
        "hygiene": [
            {"key": "vehicles-no-device", "count": no_device, "target": "/vehicles"},
            {"key": "multiple-driver-vehicles", "count": multi_driver_count, "target": "/drivers"},
            {"key": "test-like-vehicles", "count": test_like, "target": "/vehicles"},
            {"key": "vehicles-no-route", "count": no_route, "target": "/vehicles"},
        ],
    }


@app.get("/api/dashboard/stats")
def dashboard_stats(user=Depends(current_user)):
    """Backwards-compatible flat counters used by earlier clients/tests."""
    with SessionLocal() as db:
        summary = _fleet_snapshot(db)
        fleet = summary["fleet"]
        now = datetime.now(timezone.utc)
        limit = speed_limit(db)
        latest = latest_points(db)
        counts = {
            "all": fleet["total"],
            "on_move": fleet["on_move"],
            "stopped": fleet["stopped"],
            "idle": fleet["idle"],
            "out_of_network": fleet["offline"] + fleet["no_data"],
            "toing": fleet["toing"],
            "active_tracking_devices": sum(
                1
                for point in latest
                if classify_vehicle_status(point.speed, point.ignition, point.timestamp, now=now).status != "OUT_OF_NETWORK"
            ),
            "total_drivers": summary["drivers"]["total"],
            "active_alerts": sum(1 for point in latest if point.speed is not None and point.speed > limit),
            "unread_alerts": summary["alerts"]["unread"],
            "total_devices": summary["devices"]["total"],
            "connected_devices": summary["devices"]["tcp_online"],
            "simulated_devices": summary["simulation"]["simulated_devices"],
            "simulated_fixes": summary["simulation"]["simulated_fixes"],
            "total_routes": summary["routes"]["total"],
        }
        return counts


@app.get("/api/tracking/latest")
def tracking_latest(user=Depends(current_user)):
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        devices = _device_map(db)
        latest = latest_points(db)
        points = {point.device_id: point for point in latest}
        rows = []
        for device_id, device in devices.items():
            if not device.active:
                continue
            bus = db.get(Bus, device.bus_id) if device.bus_id else None
            point = points.get(device_id)
            classification = classify_vehicle_status(point.speed if point else None, point.ignition if point else None, point.timestamp if point else None, now=now)
            status, key = STATUS_LABELS[classification.status], classification.status_key
            runtime = app.state.tcp.store.get_device(device_id) if hasattr(app.state, "tcp") else None
            rows.append(
                {
                    "device_id": device_id,
                    "device_type": device.device_type,
                    "simulated": point.simulated if point else device.simulated,
                    "data_source": (
                        (getattr(point, "data_source", None) if point else None)
                        or ("simulator" if (point.simulated if point else device.simulated) else "hardware")
                    ),
                    "device_simulated": device.simulated,
                    "bus_id": bus.id if bus else None,
                    "vehicle_id": bus.vehicle_id if bus else None,
                    "registration_number": bus.registration_number if bus else None,
                    "driver_name": (bus.driver.name if bus.driver else bus.driver_name) if bus else "Unassigned",
                    "route_name": bus.route.name if bus and bus.route else "Unassigned",
                    "status": status,
                    "status_key": key,
                    "status_reason": classification.reason,
                    "tcp_online": bool(runtime and runtime.get("online")),
                    "latitude": point.latitude if point else None,
                    "longitude": point.longitude if point else None,
                    "speed": point.speed if point else None,
                    "ignition": point.ignition if point else None,
                    "ignition_available": bool(point and point.ignition is not None),
                    "course": point.course if point else None,
                    "timestamp": _iso(point.timestamp) if point else None,
                    "received_at": _iso(point.received_at) if point else None,
                    "latest": _point_payload(point),
                }
            )
        rows.sort(key=lambda row: (row["registration_number"] or row["device_id"]).lower())
        return {"generated_at": now.isoformat(), "offline_after_seconds": FRESHNESS_SECONDS, "vehicles": rows}


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


REPORT_TYPES = {
    "km",
    "consolidated",
    "trip",
    "trip-distance",
    "stoppage",
    "idle",
    "overspeed",
    "current-fleet",
    "history",
    "vehicle-trip-list",
    "daily-activity",
    "vehicle-activity",
    "vehicle-utilization",
    "route-activity",
    "device-connectivity",
}
REPORT_ALIASES = {
    "trips": "trip",
    "stoppages": "stoppage",
    "daily": "daily-activity",
    "activity": "vehicle-activity",
    "utilization": "vehicle-utilization",
    "connectivity": "device-connectivity",
    "route": "route-activity",
}


def _points_query(imei: str | None, vehicle_id: str | None, start_date: datetime | None, end_date: datetime | None, cap: int = 20000):
    query = (
        select(LocationHistory)
        .join(TrackingDevice, TrackingDevice.device_id == LocationHistory.device_id)
        .outerjoin(Bus, Bus.id == TrackingDevice.bus_id)
    )
    if imei:
        query = query.where(LocationHistory.device_id == imei)
    if vehicle_id:
        condition = or_(Bus.registration_number == vehicle_id, Bus.vehicle_id == vehicle_id)
        if vehicle_id.isdigit():
            condition = or_(condition, Bus.id == int(vehicle_id))
        query = query.where(condition)
    if start_date:
        query = query.where(LocationHistory.timestamp >= start_date)
    if end_date:
        query = query.where(LocationHistory.timestamp <= end_date)
    return query.order_by(LocationHistory.device_id, LocationHistory.timestamp, LocationHistory.id).limit(cap)


def _point_row(point: LocationHistory, bus: Bus | None) -> dict:
    return {
        "device_id": point.device_id,
        "vehicle_id": bus.vehicle_id if bus else None,
        "registration_number": bus.registration_number if bus else None,
        "timestamp": _iso(point.timestamp),
        "latitude": point.latitude,
        "longitude": point.longitude,
        "speed": point.speed,
        "course": point.course,
        "ignition": point.ignition,
        "odometer": point.odometer,
        "simulated": point.simulated,
        "data_source": getattr(point, "data_source", None)
        or ("simulator" if point.simulated else "hardware"),
        "altitude_m": point.altitude_m,
        "fix_valid": point.fix_valid,
        "satellites_in_view": point.satellites_in_view,
        "satellites_used": point.satellites_used,
        "pdop": point.pdop,
        "hdop": point.hdop,
        "vdop": point.vdop,
        "gnss": point.gnss_metadata,
    }


def _label(bus: Bus | None, device_id: str) -> tuple[str | None, str]:
    return (bus.registration_number if bus else None, bus.vehicle_id if bus else device_id)


def report_data(
    report_type: str,
    imei: str | None = None,
    vehicle_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(current_user),
):
    report_type = REPORT_ALIASES.get(report_type, report_type)
    if report_type not in REPORT_TYPES:
        raise HTTPException(404, "unsupported report type")
    if limit < 1 or limit > 5000 or offset < 0:
        raise HTTPException(422, "limit must be 1-5000 and offset nonnegative")
    # Query parameters may mix an explicit offset with a naive timestamp. Compare
    # the instants in UTC so Python never raises on aware/naive datetime pairs.
    if start_date and end_date and _as_utc(start_date) > _as_utc(end_date):
        raise HTTPException(422, "start_date must not be after end_date")

    with SessionLocal() as db:
        points = list(
            db.scalars(
                _points_query(imei, vehicle_id, _as_utc(start_date), _as_utc(end_date))
            ).all()
        )
        # Reports ignore corrupt coordinates and missing timestamps, then normalize ordering once.
        valid = ordered_points(point for point in points if valid_coordinates(point))
        devices = _device_map(db)
        bus_by_id = _bus_map(db)
        bus_for = lambda point: bus_by_id.get(devices[point.device_id].bus_id) if devices.get(point.device_id) else None
        rules: dict[str, Any] = {}
        rows: list[dict] = []

        if report_type == "km":
            total = sum(
                distance_km(first, second)
                for first, second in pairwise(valid)
                if first.device_id == second.device_id
                and 0 <= (_as_utc(second.timestamp) - _as_utc(first.timestamp)).total_seconds() <= 1800
                and distance_km(first, second) <= 100
            )
            rows = [{"distance_km": round(total, 3), "records": len(valid)}] if valid else []
            rules = {"distance": "great-circle distance between consecutive fixes; gaps over 30 min ignored"}

        elif report_type == "consolidated":
            rows = (
                [
                    {
                        "records": len(points),
                        "distance_km": round(
                            sum(trip_distance_km([p for p in valid if p.device_id == device]) for device in {p.device_id for p in valid}),
                            3,
                        ),
                        "devices": len({point.device_id for point in points}),
                        "simulated_records": sum(bool(point.simulated) for point in points),
                    }
                ]
                if points
                else []
            )

        elif report_type in {"trip", "trip-distance", "vehicle-trip-list"}:
            for index, group in enumerate(trip_groups(valid), 1):
                bus = bus_for(group[0])
                duration = (_as_utc(group[-1].timestamp) - _as_utc(group[0].timestamp)).total_seconds() / 60
                speeds = [speed for point in group if (speed := finite_number(point.speed)) is not None]
                sources = sorted({point.data_source or ("simulator" if point.simulated else "hardware") for point in group})
                rows.append(
                    {
                        "trip": index,
                        "device_id": group[0].device_id,
                        "vehicle_id": bus.vehicle_id if bus else None,
                        "registration_number": bus.registration_number if bus else None,
                        "start_time": _iso(group[0].timestamp),
                        "end_time": _iso(group[-1].timestamp),
                        "duration_minutes": round(duration, 1),
                        "distance_km": round(trip_distance_km(group), 3),
                        "max_speed_kmh": round(max(speeds), 1) if speeds else None,
                        "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
                        "records": len(group),
                    }
                )
            rules = {
                "trip_definition": "Consecutive fixes from one device separated by no more than 30 minutes.",
                        "simulated": all(bool(point.simulated) for point in group),
                        "data_sources": sources,
                "distance": "great-circle segments up to 30 minutes and 100 km",
            }

        elif report_type == "daily-activity":
            buckets: dict[str, dict[str, Any]] = {}
            previous: dict[str, LocationHistory] = {}
            for point in valid:
                day = _as_utc(point.timestamp).date().isoformat()
                item = buckets.setdefault(day, {"date": day, "fixes": 0, "distance_km": 0.0, "vehicles": set(), "simulated": 0})
                item["fixes"] += 1
                item["vehicles"].add(point.device_id)
                item["simulated"] += int(bool(point.simulated))
                prior = previous.get(point.device_id)
                if prior is not None:
                    seconds = (_as_utc(point.timestamp) - _as_utc(prior.timestamp)).total_seconds()
                    segment = distance_km(prior, point)
                    if 0 <= seconds <= 1800 and segment <= 100:
                        item["distance_km"] += segment
                previous[point.device_id] = point
            rows = [
                {
                    "date": item["date"],
                    "fixes": item["fixes"],
                    "active_vehicles": len(item["vehicles"]),
                    "distance_km": round(item["distance_km"], 3),
                    "simulated_fixes": item["simulated"],
                }
                for _, item in sorted(buckets.items())
            ]

        elif report_type in {"vehicle-activity", "vehicle-utilization"}:
            by_device: dict[str, list[LocationHistory]] = {}
            for point in valid:
                by_device.setdefault(point.device_id, []).append(point)
            period_start = start_date or min((_as_utc(p.timestamp) for p in valid), default=None)
            period_end = end_date or max((_as_utc(p.timestamp) for p in valid), default=None)
            period_days = max(1.0, ((period_end - period_start).total_seconds() / 86400) if period_start and period_end else 1.0)
            for device_id, group in sorted(by_device.items()):
                bus = bus_for(group[0])
                days = {_as_utc(p.timestamp).date().isoformat() for p in group}
                moving_minutes = 0.0
                for first, second in pairwise(group):
                    seconds = (_as_utc(second.timestamp) - _as_utc(first.timestamp)).total_seconds()
                    if 0 <= seconds <= 1800 and (finite_number(first.speed) or 0) > 3:
                        moving_minutes += seconds / 60
                rows.append(
                    {
                        "device_id": device_id,
                        "vehicle_id": bus.vehicle_id if bus else None,
                        "registration_number": bus.registration_number if bus else None,
                        "first_seen": _iso(group[0].timestamp),
                        "last_seen": _iso(group[-1].timestamp),
                        "active_days": len(days),
                        "fixes": len(group),
                        "distance_km": round(trip_distance_km(group), 3),
                        "moving_minutes": round(moving_minutes, 1),
                        "utilization_percent": round(min(100.0, len(days) / period_days * 100), 1),
                        "simulated": all(point.simulated for point in group),
                    }
                )
            rules = {
                "distance": "great-circle segments",
                "utilization": "active calendar days / period days (capped at 100%)",
                "moving_minutes": "time between fixes while previous speed > 3 km/h",
            }

        elif report_type == "route-activity":
            route_rows: dict[str, dict[str, Any]] = {}
            for point in valid:
                bus = bus_for(point)
                route = bus.route if bus else None
                name = route.name if route else "Unassigned route"
                item = route_rows.setdefault(
                    name,
                    {"route_name": name, "route_identifier": route.identifier if route else None, "vehicles": set(), "fixes": 0, "distance_km": 0.0},
                )
                item["vehicles"].add(point.device_id)
                item["fixes"] += 1
            previous: dict[str, LocationHistory] = {}
            for point in valid:
                bus = bus_for(point)
                route = bus.route if bus else None
                name = route.name if route else "Unassigned route"
                prior = previous.get(point.device_id)
                if prior is not None:
                    seconds = (_as_utc(point.timestamp) - _as_utc(prior.timestamp)).total_seconds()
                    segment = distance_km(prior, point)
                    if 0 <= seconds <= 1800 and segment <= 100:
                        route_rows[name]["distance_km"] += segment
                previous[point.device_id] = point
            rows = [
                {
                    "route_name": item["route_name"],
                    "route_identifier": item["route_identifier"],
                    "vehicles": len(item["vehicles"]),
                    "fixes": item["fixes"],
                    "distance_km": round(item["distance_km"], 3),
                }
                for _, item in sorted(route_rows.items())
            ]

        elif report_type == "device-connectivity":
            now = datetime.now(timezone.utc)
            offline_seconds = device_offline_seconds(db)
            latest = {point.device_id: point for point in latest_points(db)}
            for device in sorted(devices.values(), key=lambda item: item.device_id):
                if imei and device.device_id != imei:
                    continue
                bus = bus_by_id.get(device.bus_id) if device.bus_id else None
                point = latest.get(device.device_id)
                stamp = _as_utc(point.timestamp) if point else None
                age = int((now - stamp).total_seconds()) if stamp else None
                runtime = app.state.tcp.store.get_device(device.device_id) if hasattr(app.state, "tcp") else None
                rows.append(
                    {
                        "device_id": device.device_id,
                        "device_type": device.device_type,
                        "registration_number": bus.registration_number if bus else None,
                        "active": device.active,
                        "tcp_online": bool(runtime and runtime.get("online")),
                        "telemetry_status": "fresh" if age is not None and age <= offline_seconds else "stale" if age is not None else "no data",
                        "last_fix": _iso(point.timestamp) if point else None,
                        "last_received": _iso(point.received_at) if point else None,
                        "age_seconds": age,
                        "age_label": _interval(age) if age is not None else "never",
                        "fix_count": db.scalar(select(func.count(LocationHistory.id)).where(LocationHistory.device_id == device.device_id)) or 0,
                        "simulated": device.simulated,
                    }
                )
            rows.sort(key=lambda row: row["age_seconds"] if row["age_seconds"] is not None else 10**9)
            rules = {"stale_after_seconds": int(offline_seconds), "tcp_online": "current TCP session, independent of telemetry freshness"}

        elif report_type == "overspeed":
            threshold = speed_limit(db)
            rows = [_point_row(point, bus_for(point)) for point in valid if (speed := finite_number(point.speed)) is not None and speed > threshold]
            rules = {"threshold_kmh": threshold}

        elif report_type == "stoppage":
            minutes = int(os.getenv("STOPPAGE_MINUTES", "5"))
            for span in stationary_periods(points, minutes):
                device = devices.get(span["device_id"])
                bus = bus_by_id.get(device.bus_id) if device and device.bus_id else None
                span["registration_number"] = bus.registration_number if bus else None
                span["vehicle_id"] = bus.vehicle_id if bus else None
                rows.append(span)
            rules = {
                "stationary_speed_kmh_or_less": 1,
                "minimum_duration_minutes": minutes,
                "maximum_fix_gap_minutes": 5,
            }

        elif report_type == "idle":
            if not any(point.ignition is not None for point in points):
                rows = []
                rules = {
                    "supported": False,
                    "reason": "Ignition/run-state has not been recorded for these fixes. Idle cannot be distinguished from a stopped vehicle.",
                }
            else:
                minutes = int(os.getenv("STOPPAGE_MINUTES", "5"))
                for span in idle_periods(points, minutes):
                    device = devices.get(span["device_id"])
                    bus = bus_by_id.get(device.bus_id) if device and device.bus_id else None
                    span["registration_number"] = bus.registration_number if bus else None
                    span["vehicle_id"] = bus.vehicle_id if bus else None
                    rows.append(span)
                rules = {
                    "supported": True,
                    "definition": "ignition=true and speed <= 1 km/h, sustained for the minimum duration",
                    "minimum_duration_minutes": minutes,
                }

        elif report_type == "current-fleet":
            latest = latest_points(db)
            now = datetime.now(timezone.utc)
            offline_seconds = device_offline_seconds(db)
            for point in latest:
                if imei and point.device_id != imei:
                    continue
                device = devices.get(point.device_id)
                bus = bus_by_id.get(device.bus_id) if device and device.bus_id else None
                if vehicle_id and bus is not None and vehicle_id not in {str(bus.id), bus.vehicle_id, bus.registration_number}:
                    continue
                status, key = _status_for(point, now, offline_seconds)
                rows.append(
                    {
                        "device_id": point.device_id,
                        "vehicle_id": bus.vehicle_id if bus else None,
                        "registration_number": bus.registration_number if bus else None,
                        "status": status,
                        "status_key": key,
                        "timestamp": _iso(point.timestamp),
                        "latitude": point.latitude,
                        "longitude": point.longitude,
                        "speed": point.speed,
                        "simulated": point.simulated,
                    }
                )

        elif report_type == "history":
            rows = [_point_row(point, bus_for(point)) for point in points]
            rules = {"record_cap": 20000}

        total = len(rows)
        page = rows[offset : offset + limit]
        return _json_safe({
            "report_type": report_type,
            "period": {"start": start_date.isoformat() if start_date else None, "end": end_date.isoformat() if end_date else None},
            "sufficient_data": bool(page),
            "count": total,
            "limit": limit,
            "offset": offset,
            "rules": rules,
            "data": page,
        })


@app.get("/api/reports/{report_type}")
def report_endpoint(
    report_type: str,
    imei: str | None = None,
    vehicle_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(current_user),
):
    return report_data(
        report_type,
        imei=imei,
        vehicle_id=vehicle_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
        user=user,
    )


@app.get("/api/reports.csv")
def export_report_csv(
    report_type: str,
    imei: str | None = None,
    vehicle_id: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    user=Depends(current_user),
):
    result = report_data(
        report_type,
        imei=imei,
        vehicle_id=vehicle_id,
        start_date=start_date,
        end_date=end_date,
        limit=5000,
        offset=0,
        user=user,
    )
    rows = result["data"]
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{result["report_type"]}.csv"'},
    )


@app.get("/trips")
def list_trips(
    vehicle_id: str | None = None,
    imei: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(current_user),
):
    return report_data("trip", vehicle_id=vehicle_id, imei=imei, start_date=start_date, end_date=end_date, limit=limit, offset=offset, user=user)


@app.get("/api/reports/trip/{trip_id}/fixes")
def get_trip_fixes(
    trip_id: str,
    vehicle_id: str | None = None,
    imei: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    user=Depends(current_user),
):
    """Get the fixes for a specific trip for replay.
    
    trip_id format: device_id:trip_number (e.g., "IVTD_BUS_01:1")
    """
    try:
        device_id, trip_num_str = trip_id.split(":")
        trip_number = int(trip_num_str)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(422, "Invalid trip_id format. Use device_id:trip_number") from exc
    
    if trip_number < 1:
        raise HTTPException(422, "Trip number must be >= 1")
    
    with SessionLocal() as db:
        # Reuse the report_data logic to get trips, then extract the specific trip
        result = report_data("trip", vehicle_id=vehicle_id, imei=imei, start_date=start_date, end_date=end_date, limit=10000, offset=0, user=user)
        trips = result.get("data", [])
        
        # Find the matching trip
        target_trip = None
        for trip in trips:
            if trip.get("device_id") == device_id and trip.get("trip") == trip_number:
                target_trip = trip
                break
        
        if not target_trip:
            raise HTTPException(404, "Trip not found")
        
        # Get the fixes for this trip
        query = db.query(LocationHistory).filter(
            LocationHistory.device_id == device_id,
            LocationHistory.timestamp >= target_trip["start_time"],
            LocationHistory.timestamp <= target_trip["end_time"],
        ).order_by(LocationHistory.timestamp.asc())
        
        fixes = query.all()
        
        return {
            "trip": target_trip,
            "fixes": [
                {
                    "timestamp": _iso(f.timestamp),
                    "latitude": f.latitude,
                    "longitude": f.longitude,
                    "speed": f.speed,
                    "course": f.course,
                    "altitude_m": f.altitude_m,
                    "simulated": f.simulated,
                    "ignition": f.ignition,
                    "gnss_metadata": f.gnss_metadata,
                }
                for f in fixes
            ],
        }


# ---------------------------------------------------------------------------
# Settings and alerts
# ---------------------------------------------------------------------------


@app.get("/settings")
def get_settings(user=Depends(current_user)):
    with SessionLocal() as db:
        offline = db.get(SystemSetting, "device_offline_minutes")
        eta = db.get(SystemSetting, "eta_enabled")
        return {
            "overspeed_kmh": speed_limit(db),
            "device_offline_minutes": float(offline.value) if offline else device_offline_seconds(db) / 60,
            "eta_enabled": eta.value == "true" if eta else False,
        }


@app.put("/settings")
def update_settings(data: SettingIn, user=Depends(management_user)):
    with SessionLocal() as db:
        row = db.get(SystemSetting, "overspeed_kmh")
        if row is None:
            db.add(SystemSetting(key="overspeed_kmh", value=str(data.overspeed_kmh)))
        else:
            row.value = str(data.overspeed_kmh)
        if data.device_offline_minutes is not None:
            offline = db.get(SystemSetting, "device_offline_minutes")
            if offline is None:
                db.add(SystemSetting(key="device_offline_minutes", value=str(data.device_offline_minutes)))
            else:
                offline.value = str(data.device_offline_minutes)
        if data.eta_enabled is not None:
            eta = db.get(SystemSetting, "eta_enabled")
            if eta is None:
                db.add(SystemSetting(key="eta_enabled", value=str(data.eta_enabled).lower()))
            else:
                eta.value = str(data.eta_enabled).lower()
        _audit(db, user, "update", "settings", "overspeed_kmh", f"threshold={data.overspeed_kmh}")
        db.commit()
        return get_settings(user)


@app.get("/alerts")
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
        query = select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc())
        if unread_only:
            query = query.where(Alert.is_read.is_(False))
        if event_type:
            query = query.where(Alert.event_type == event_type)
        rows = list(db.scalars(query.limit(limit).offset(offset)).all())
        unread = db.scalar(select(func.count(Alert.id)).where(Alert.is_read.is_(False))) or 0
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


@app.patch("/alerts/read-all")
def mark_all_alerts_read(user=Depends(management_user)):
    with SessionLocal() as db:
        result = db.execute(text("UPDATE alerts SET is_read = :value WHERE is_read = :unread"), {"value": True if engine.dialect.name != "sqlite" else 1, "unread": False if engine.dialect.name != "sqlite" else 0})
        _audit(db, user, "update", "alerts", "all", "marked all alerts read")
        db.commit()
        return {"updated": result.rowcount or 0}


@app.patch("/alerts/{alert_id}")
def mark_alert_read(alert_id: int, user=Depends(management_user)):
    with SessionLocal() as db:
        row = db.get(Alert, alert_id)
        if not row:
            raise HTTPException(404, "alert not found")
        row.is_read = True
        _audit(db, user, "update", "alert", row.id, "marked read")
        db.commit()
        return {"id": row.id, "is_read": row.is_read}


# ---------------------------------------------------------------------------
# Alert Incidents
# ---------------------------------------------------------------------------


@app.get("/api/alerts/incidents")
def list_alert_incidents(
    state: str | None = None,  # open, resolved
    device_id: str | None = None,
    event_type: str | None = None,
    unread_only: bool = False,
    limit: int = 100,
    offset: int = 0,
    user=Depends(current_user),
):
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422, "invalid pagination")
    with SessionLocal() as db:
        query = select(AlertIncident).order_by(AlertIncident.opened_at.desc(), AlertIncident.id.desc())
        if state:
            query = query.where(AlertIncident.state == state)
        if device_id:
            query = query.where(AlertIncident.device_id == device_id)
        if event_type:
            query = query.where(AlertIncident.event_type == event_type)
        if unread_only:
            query = query.where(AlertIncident.is_read.is_(False))
        rows = list(db.scalars(query.limit(limit).offset(offset)).all())
        unread = db.scalar(select(func.count(AlertIncident.id)).where(AlertIncident.is_read.is_(False))) or 0
        return {
            "incidents": [
                {
                    "id": inc.id,
                    "device_id": inc.device_id,
                    "event_type": inc.event_type,
                    "state": inc.state,
                    "opened_at": _iso(inc.opened_at),
                    "resolved_at": _iso(inc.resolved_at) if inc.resolved_at else None,
                    "last_seen_at": _iso(inc.last_seen_at) if inc.last_seen_at else None,
                    "alert_count": inc.alert_count,
                    "is_read": inc.is_read,
                }
                for inc in rows
            ],
            "unread_count": unread,
        }


@app.get("/api/alerts/incidents/{incident_id}")
def get_alert_incident(incident_id: int, user=Depends(current_user)):
    with SessionLocal() as db:
        inc = db.get(AlertIncident, incident_id)
        if not inc:
            raise HTTPException(404, "incident not found")
        # Get linked alerts
        alerts = db.scalars(
            select(Alert)
            .where(Alert.incident_id == incident_id)
            .order_by(Alert.created_at.asc())
        ).all()
        return {
            "id": inc.id,
            "device_id": inc.device_id,
            "event_type": inc.event_type,
            "state": inc.state,
            "opened_at": _iso(inc.opened_at),
            "resolved_at": _iso(inc.resolved_at) if inc.resolved_at else None,
            "last_seen_at": _iso(inc.last_seen_at) if inc.last_seen_at else None,
            "alert_count": inc.alert_count,
            "is_read": inc.is_read,
            "alerts": [
                {
                    "id": a.id,
                    "event_type": a.event_type,
                    "message": a.message,
                    "device_id": a.device_id,
                    "created_at": _iso(a.created_at),
                    "is_read": a.is_read,
                }
                for a in alerts
            ],
        }


@app.patch("/api/alerts/incidents/{incident_id}/read")
def mark_incident_read(incident_id: int, user=Depends(management_user)):
    with SessionLocal() as db:
        inc = db.get(AlertIncident, incident_id)
        if not inc:
            raise HTTPException(404, "incident not found")
        inc.is_read = True
        # Also mark all linked alerts as read
        alerts = db.scalars(select(Alert).where(Alert.incident_id == incident_id)).all()
        for a in alerts:
            a.is_read = True
        _audit(db, user, "update", "alert_incident", inc.id, "marked incident read")
        db.commit()
        return {"id": inc.id, "is_read": inc.is_read, "alerts_updated": len(alerts)}


@app.patch("/api/alerts/incidents/read-all")
def mark_all_incidents_read(user=Depends(management_user)):
    with SessionLocal() as db:
        # Mark all incidents as read
        inc_result = db.execute(text("UPDATE alert_incidents SET is_read = :value WHERE is_read = :unread"), 
                               {"value": True if engine.dialect.name != "sqlite" else 1, "unread": False if engine.dialect.name != "sqlite" else 0})
        # Mark all alerts as read
        alert_result = db.execute(text("UPDATE alerts SET is_read = :value WHERE is_read = :unread"),
                                 {"value": True if engine.dialect.name != "sqlite" else 1, "unread": False if engine.dialect.name != "sqlite" else 0})
        _audit(db, user, "update", "alert_incidents", "all", "marked all incidents read")
        db.commit()
        return {"incidents_updated": inc_result.rowcount or 0, "alerts_updated": alert_result.rowcount or 0}


@app.get("/api/audit")
def audit_log(limit: int = 100, offset: int = 0, user=Depends(admin_user)):
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422, "invalid pagination")
    with SessionLocal() as db:
        rows = list(db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)).all())
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


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------


def bus_response(db, bus: Bus, *, preloaded: bool = False, points_by_device: dict[str, LocationHistory] | None = None) -> BusOut:
    if preloaded:
        driver = bus.driver
        route = bus.route
        device = next((item for item in sorted(bus.devices, key=lambda row: row.id) if item.active), None)
        point = points_by_device.get(device.device_id) if device and points_by_device else None
    else:
        driver = db.get(Driver, bus.driver_id) if bus.driver_id else None
        route = db.get(Route, bus.route_id) if bus.route_id else None
        device = db.scalar(
            select(TrackingDevice)
            .where(TrackingDevice.bus_id == bus.id, TrackingDevice.active.is_(True))
            .order_by(TrackingDevice.id)
            .limit(1)
        )
        point = None
        if device:
            point = db.scalar(
                select(LocationHistory)
                .where(LocationHistory.device_id == device.device_id, LocationHistory.fix_valid.is_not(False))
                .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
                .limit(1)
            )
    now = datetime.now(timezone.utc)
    classification = classify_vehicle_status(point.speed if point else None, point.ignition if point else None, point.timestamp if point else None, now=now)
    simulated = point.simulated if point is not None else (device.simulated if device is not None else None)
    data_source = (
        (getattr(point, "data_source", None) if point is not None else None)
        or ("simulator" if simulated else "hardware" if device is not None else None)
    )
    return BusOut(
        id=bus.id,
        vehicle_id=bus.vehicle_id,
        bus_identifier=bus.vehicle_id,
        name=bus.vehicle_id,
        vehicle_name=bus.vehicle_id,
        registration_number=bus.registration_number,
        registration=bus.registration_number,
        driver_id=driver.id if driver else None,
        driver_name=driver.name if driver else "Unassigned",
        driver_phone=driver.phone if driver else None,
        driver_email=driver.email if driver else None,
        route_id=route.id if route else None,
        route_name=route.name if route else "Unassigned",
        route_color=route.color if route else None,
        device_id=device.device_id if device else None,
        device_name=device.device_id if device else None,
        device_model=device.device_type if device else None,
        imei_no=device.device_id if device and device.identifier_type in {"imei", "simulated_imei"} else None,
        status=STATUS_LABELS[classification.status],
        status_key=classification.status_key,
        last_seen=_iso(point.timestamp) if point else None,
        last_seen_formatted=_iso(point.timestamp) if point else None,
        speed=point.speed if point else None,
        latitude=point.latitude if point else None,
        longitude=point.longitude if point else None,
        ignition=point.ignition if point else None,
        ignition_available=bool(point and point.ignition is not None),
        simulated=simulated,
        data_source=data_source,
    )


def apply_bus_relations(db, bus: Bus, data: BusIn):
    driver = db.get(Driver, data.driver_id) if data.driver_id is not None else None
    if data.driver_id is not None and driver is None:
        raise HTTPException(422, "driver_id does not reference a registered driver")
    route = db.get(Route, data.route_id) if data.route_id is not None else None
    if data.route_id is not None and route is None:
        raise HTTPException(422, "route_id does not reference a registered route")
    device = db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == data.device_id)) if data.device_id else None
    if data.device_id and device is None:
        raise HTTPException(422, "device_id does not reference a registered IVTD device")
    prior = [
        item
        for item in db.scalars(select(TrackingDevice).where(TrackingDevice.bus_id == bus.id)).all()
        if device is None or item.device_id != device.device_id
    ]
    unassigned_ids = [item.device_id for item in prior]
    affected_bus_ids = {bus.id}
    if device and device.bus_id is not None:
        affected_bus_ids.add(device.bus_id)
    bus.driver_id = driver.id if driver else None
    bus.driver_name = driver.name if driver else None
    bus.route_id = route.id if route else None
    bus.route_name = route.name if route else None
    for item in prior:
        item.bus_id = None
    if device:
        device.bus_id = bus.id
    return unassigned_ids, affected_bus_ids


@app.get("/api/vehicles", response_model=list[BusOut], include_in_schema=False)
@app.get("/buses", response_model=list[BusOut])
def buses(user=Depends(current_user)):
    with SessionLocal() as db:
        rows = list(db.scalars(
            select(Bus).options(joinedload(Bus.driver), joinedload(Bus.route), selectinload(Bus.devices)).order_by(Bus.id)
        ).all())
        points = {point.device_id: point for point in latest_points(db)}
        return [bus_response(db, bus, preloaded=True, points_by_device=points) for bus in rows]


@app.post("/api/vehicles", response_model=BusOut, status_code=201, include_in_schema=False)
@app.post("/buses", response_model=BusOut, status_code=201)
def create_bus(data: BusIn, user=Depends(management_user)):
    with SessionLocal() as db:
        row = Bus(vehicle_id=data.vehicle_id, registration_number=data.registration_number)
        db.add(row)
        try:
            db.flush()
            unassigned, affected = apply_bus_relations(db, row, data)
            _audit(db, user, "create", "vehicle", row.vehicle_id, data.registration_number)
            db.commit()
            db.refresh(row)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "vehicle_id or registration already exists") from None
        for bus_id in affected:
            sync_bus_registry(db, bus_id)
        for device_id in unassigned:
            sync_unassigned_device(db, device_id)
        return bus_response(db, row)


@app.get("/api/vehicles/{bus_id}", response_model=BusOut, include_in_schema=False)
@app.get("/buses/{bus_id}", response_model=BusOut)
def get_bus(bus_id: int, user=Depends(current_user)):
    with SessionLocal() as db:
        row = db.get(Bus, bus_id)
        if not row:
            raise HTTPException(404, "bus not found")
        return bus_response(db, row)


@app.put("/api/vehicles/{bus_id}", response_model=BusOut, include_in_schema=False)
@app.put("/buses/{bus_id}", response_model=BusOut)
def update_bus(bus_id: int, data: BusIn, user=Depends(management_user)):
    with SessionLocal() as db:
        row = db.get(Bus, bus_id)
        if not row:
            raise HTTPException(404, "bus not found")
        previous_device = db.scalar(select(TrackingDevice).where(TrackingDevice.bus_id == bus_id, TrackingDevice.active.is_(True)))
        old_bus_for_device = previous_device.bus_id if previous_device else None
        row.vehicle_id = data.vehicle_id
        row.registration_number = data.registration_number
        try:
            unassigned, affected = apply_bus_relations(db, row, data)
            affected.add(old_bus_for_device)
            _audit(db, user, "update", "vehicle", row.vehicle_id, data.registration_number)
            db.commit()
            db.refresh(row)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "vehicle_id or registration already exists") from None
        for related_bus_id in affected:
            sync_bus_registry(db, related_bus_id)
        for device_id in unassigned:
            sync_unassigned_device(db, device_id)
        return bus_response(db, row)


@app.delete("/api/vehicles/{bus_id}", status_code=204, include_in_schema=False)
@app.delete("/buses/{bus_id}", status_code=204)
def delete_bus(bus_id: int, user=Depends(management_user)):
    with SessionLocal() as db:
        row = db.get(Bus, bus_id)
        if not row:
            raise HTTPException(404, "bus not found")
        assigned = list(db.scalars(select(TrackingDevice).where(TrackingDevice.bus_id == bus_id)).all())
        for device in assigned:
            device.bus_id = None
        _audit(db, user, "delete", "vehicle", row.vehicle_id, row.registration_number)
        db.delete(row)
        db.commit()
        for device in assigned:
            sync_unassigned_device(db, device.device_id)


@app.get("/buses/{bus_id}/history")
def bus_history(
    bus_id: int,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    limit: int = 2000,
    user=Depends(current_user),
):
    if not 1 <= limit <= 10000:
        raise HTTPException(422, "limit must be from 1 to 10000")
    if start_time and end_time and start_time > end_time:
        raise HTTPException(422, "start_time must not be after end_time")
    with SessionLocal() as db:
        bus = db.get(Bus, bus_id)
        if not bus:
            raise HTTPException(404, "bus not found")
        device = db.scalar(select(TrackingDevice).where(TrackingDevice.bus_id == bus_id, TrackingDevice.active.is_(True)))
        if not device:
            return {"bus_id": bus_id, "history": [], "summary": None, "device_id": None}
        conditions = [LocationHistory.device_id == device.device_id]
        if start_time:
            conditions.append(LocationHistory.timestamp >= start_time)
        if end_time:
            conditions.append(LocationHistory.timestamp <= end_time)
        points = list(
            db.scalars(
                select(LocationHistory).where(and_(*conditions)).order_by(LocationHistory.timestamp, LocationHistory.id).limit(limit)
            ).all()
        )
        valid = [point for point in points if point.latitude is not None and point.longitude is not None]
        summary = None
        if valid:
            speeds = [point.speed for point in valid if point.speed is not None]
            summary = {
                "point_count": len(valid),
                "start_time": _iso(valid[0].timestamp),
                "end_time": _iso(valid[-1].timestamp),
                "duration_minutes": round((_as_utc(valid[-1].timestamp) - _as_utc(valid[0].timestamp)).total_seconds() / 60, 1),
                "distance_km": round(trip_distance_km(valid), 3),
                "max_speed_kmh": round(max(speeds), 1) if speeds else None,
                "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
                "stops": len(stationary_periods(valid, minimum_minutes=1)),
            }
        return {
            "bus_id": bus_id,
            "device_id": device.device_id,
            "summary": summary,
            "history": [
                {
                    "timestamp": _iso(point.timestamp),
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "speed": point.speed,
                    "course": point.course,
                    "ignition": point.ignition,
                    "odometer": point.odometer,
                    "altitude_m": point.altitude_m,
                    "fix_valid": point.fix_valid,
                    "satellites_in_view": point.satellites_in_view,
                    "satellites_used": point.satellites_used,
                    "pdop": point.pdop,
                    "hdop": point.hdop,
                    "vdop": point.vdop,
                    "gnss": point.gnss_metadata,
                }
                for point in points
            ],
        }


# ---------------------------------------------------------------------------
# Public Share Links (Share Tokens)
# ---------------------------------------------------------------------------


class ShareTokenCreate(BaseModel):
    name: str | None = None
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ShareTokenOut(BaseModel):
    id: int
    name: str | None
    token: str  # Only returned on creation
    expires_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


class ShareTokenListItem(BaseModel):
    id: int
    name: str | None
    expires_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


@app.post("/api/buses/{bus_id}/share", response_model=ShareTokenOut)
def create_share_token(bus_id: int, data: ShareTokenCreate, user=Depends(management_user)):
    """Create a public share link for a bus."""
    with SessionLocal() as db:
        bus = db.get(Bus, bus_id)
        if not bus:
            raise HTTPException(404, "bus not found")
        
        token = _generate_token()
        token_hash = _hash_token(token)
        
        expires_at = None
        if data.expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)
        
        share_token = ShareToken(
            bus_id=bus_id,
            token_hash=token_hash,
            name=data.name,
            created_by=user.get("id") or None,
            expires_at=expires_at,
        )
        db.add(share_token)
        db.commit()
        db.refresh(share_token)
        
        _audit(db, user, "create", "share_token", str(share_token.id), f"bus_id={bus_id}")
        
        return {
            "id": share_token.id,
            "name": share_token.name,
            "token": token,  # Only returned once!
            "expires_at": share_token.expires_at,
            "created_at": share_token.created_at,
            "revoked_at": share_token.revoked_at,
        }


@app.get("/api/buses/{bus_id}/share", response_model=list[ShareTokenListItem])
def list_share_tokens(bus_id: int, user=Depends(management_user)):
    """List all share tokens for a bus (without tokens)."""
    with SessionLocal() as db:
        bus = db.get(Bus, bus_id)
        if not bus:
            raise HTTPException(404, "bus not found")
        tokens = db.scalars(
            select(ShareToken)
            .where(ShareToken.bus_id == bus_id)
            .order_by(ShareToken.created_at.desc())
        ).all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "expires_at": t.expires_at,
                "created_at": t.created_at,
                "revoked_at": t.revoked_at,
            }
            for t in tokens
        ]


@app.delete("/api/buses/{bus_id}/share/{token_id}")
def revoke_share_token(bus_id: int, token_id: int, user=Depends(management_user)):
    """Revoke a share token."""
    with SessionLocal() as db:
        token = db.get(ShareToken, token_id)
        if not token or token.bus_id != bus_id:
            raise HTTPException(404, "share token not found")
        if token.revoked_at:
            raise HTTPException(400, "token already revoked")
        token.revoked_at = datetime.now(timezone.utc)
        db.commit()
        _audit(db, user, "revoke", "share_token", str(token_id), f"bus_id={bus_id}")
        return {"revoked": True}


# ---------------------------------------------------------------------------
# Public API (no auth)
# ---------------------------------------------------------------------------


_public_share_limiter = SlidingWindowRateLimiter(max_requests=120, window_seconds=60)

_PUBLIC_SOURCE_BADGES = {
    "hardware": "Device-reported",
    "simulator": "Simulated",
    "test_replay": "Test replay",
}


def _public_share_headers(response: Response) -> None:
    """Make sure a share URL is not cached or indexed by search engines."""
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    response.headers["Referrer-Policy"] = "no-referrer"


def _limit_public_share(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    allowed, retry_after = _public_share_limiter.allow(f"share:{client}")
    if not allowed:
        raise HTTPException(
            429,
            "too many requests; try again shortly",
            headers={"Retry-After": str(retry_after)},
        )


def _resolve_share_token(db, raw_token: str) -> ShareToken:
    """Look up a share token by hash and enforce revocation and expiry.

    The plaintext token is never stored, so an unknown or revoked token returns
    the same response and cannot be enumerated.
    """
    if not raw_token or len(raw_token) > 128:
        raise HTTPException(404, "invalid or revoked link")
    share = db.scalar(select(ShareToken).where(ShareToken.token_hash == _hash_token(raw_token)))
    if not share:
        raise HTTPException(404, "invalid or revoked link")
    if share.revoked_at is not None:
        raise HTTPException(410, "this link has been revoked")
    expires_at = _as_utc(share.expires_at)
    if expires_at is not None and expires_at < datetime.now(timezone.utc):
        raise HTTPException(410, "this link has expired")
    return share


def _public_bus_payload(db, bus: Bus) -> dict:
    """Minimal, non-identifying bus snapshot for a public share page.

    Deliberately excludes driver name/phone/email/licence, device IDs, IMEI,
    internal row IDs and share-token metadata.
    """
    device = db.scalar(
        select(TrackingDevice)
        .where(TrackingDevice.bus_id == bus.id, TrackingDevice.active.is_(True))
        .order_by(TrackingDevice.id)
    )
    latest = None
    if device:
        latest = db.scalar(
            select(LocationHistory)
            .where(LocationHistory.device_id == device.device_id)
            .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
            .limit(1)
        )
    simulated = latest.simulated if latest is not None else bool(device and device.simulated)
    source = (
        (getattr(latest, "data_source", None) if latest is not None else None)
        or ("simulator" if simulated else "hardware")
    )
    stamp = _as_utc(latest.timestamp) if latest else None
    age = int((datetime.now(timezone.utc) - stamp).total_seconds()) if stamp else None
    has_position = bool(
        latest is not None
        and latest.latitude is not None
        and latest.longitude is not None
        and latest.fix_valid is not False
    )
    return {
        "registration_number": bus.registration_number,
        "route_name": bus.route.name if bus.route else bus.route_name,
        "source": source,
        "source_badge": _PUBLIC_SOURCE_BADGES.get(source, "Device-reported"),
        "last_update": _iso(latest.timestamp) if latest else None,
        "age_seconds": age,
        "updated_ago": _humanize_ago(latest.timestamp) if latest else "never",
        "stale": age is None or age > device_offline_seconds(db),
        "position": (
            {"latitude": latest.latitude, "longitude": latest.longitude}
            if has_position
            else None
        ),
        "speed": latest.speed if latest else None,
        "course": latest.course if latest else None,
    }


@app.get("/public/bus/{token}")
def public_bus_page(token: str, request: Request, response: Response):
    """Public read-only bus share page (no authentication)."""
    _limit_public_share(request)
    _public_share_headers(response)
    with SessionLocal() as db:
        share = _resolve_share_token(db, token)
        bus = db.get(Bus, share.bus_id)
        if not bus:
            raise HTTPException(404, "bus not found")
        return _public_bus_payload(db, bus)


@app.get("/public/api/bus/{token}/status")
def public_bus_status(token: str, request: Request, response: Response):
    """Lightweight status endpoint for the share page auto-refresh."""
    _limit_public_share(request)
    _public_share_headers(response)
    with SessionLocal() as db:
        share = _resolve_share_token(db, token)
        bus = db.get(Bus, share.bus_id)
        if not bus:
            raise HTTPException(404, "bus not found")
        return _public_bus_payload(db, bus)


def _humanize_ago(dt: datetime) -> str:
    """Human-readable time ago string."""
    if dt is None:
        return "never"
    now = datetime.now(timezone.utc)
    dt_utc = _as_utc(dt)
    if dt_utc is None:
        return "unknown"
    diff = (now - dt_utc).total_seconds()
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)} min ago"
    if diff < 86400:
        return f"{int(diff // 3600)} hr ago"
    return f"{int(diff // 86400)} day ago"


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


GNSS_COMPATIBILITY = {
    "navic": "unsupported_or_unverified",
    "gps": "unsupported_or_unverified",
    "glonass": "unsupported_or_unverified",
    "galileo": "unsupported_or_unverified",
    "beidou": "unsupported_or_unverified",
    "qzss": "unsupported_or_unverified",
}


def _device_payload(db, device: TrackingDevice) -> dict:
    latest = db.scalar(
        select(LocationHistory)
        .where(LocationHistory.device_id == device.device_id)
        .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
        .limit(1)
    )
    runtime = app.state.tcp.store.get_device(device.device_id) if hasattr(app.state, "tcp") else None
    bus = db.get(Bus, device.bus_id) if device.bus_id else None
    stamp = _as_utc(latest.timestamp) if latest else None
    age = int((datetime.now(timezone.utc) - stamp).total_seconds()) if stamp else None
    fresh = age is not None and age <= device_offline_seconds(db)
    return {
        "id": device.id,
        "device_id": device.device_id,
        "device_type": device.device_type,
        "identifier_type": device.identifier_type,
        "bus_id": device.bus_id,
        "simulated": device.simulated,
        "data_source": "simulator" if device.simulated else "hardware",
        "active": device.active,
        "identity": {
            "device_id": device.device_id,
            "bus_id": bus.id if bus else None,
            "vehicle_id": bus.vehicle_id if bus else None,
            "registration_number": bus.registration_number if bus else None,
            "driver_name": (bus.driver.name if bus and bus.driver else bus.driver_name) if bus else "Unassigned",
            "route_name": bus.route.name if bus and bus.route else "Unassigned",
        },
        "latest": _point_payload(latest),
        "connection": "online" if runtime and runtime.get("online") else "no_tcp_session",
        "online": bool(runtime and runtime.get("online")),
        "telemetry_fresh": fresh,
        "last_communication": _iso(latest.received_at) if latest and latest.received_at else (_iso(latest.timestamp) if latest else None),
        "age_seconds": age,
        "age_label": _interval(age) if age is not None else "never",
        "gnss_compatibility": GNSS_COMPATIBILITY,
        "reported_constellations": (latest.gnss_metadata or {}).get("constellations", []) if latest else [],
    }


@app.get("/api/devices", include_in_schema=False)
@app.get("/devices")
def devices(user=Depends(current_user)):
    with SessionLocal() as db:
        rows = db.scalars(select(TrackingDevice).order_by(TrackingDevice.id)).all()
        return {"devices": [_device_payload(db, device) for device in rows]}


@app.get("/api/devices/{device_id}/telemetry/latest")
def device_telemetry_latest(device_id: str, user=Depends(current_user)):
    with SessionLocal() as db:
        device = db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == device_id))
        if not device:
            raise HTTPException(404, "device not found")
        latest = db.scalar(
            select(LocationHistory)
            .where(LocationHistory.device_id == device_id)
            .order_by(LocationHistory.timestamp.desc(), LocationHistory.id.desc())
            .limit(1)
        )
        return {
            "device_id": device_id,
            "identity": _device_payload(db, device)["identity"],
            "latest": _point_payload(latest),
            "gnss_compatibility": GNSS_COMPATIBILITY,
        }


@app.get("/api/devices/{device_id}/telemetry/observed-constellations")
def device_observed_constellations(device_id: str, limit: int = 100, user=Depends(current_user)):
    """Get observed constellations from historical telemetry for a device.
    
    Parses talker IDs from GNSS metadata in historical fixes.
    Excludes simulator data by default (use simulated=false to include).
    """
    with SessionLocal() as db:
        device = db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == device_id))
        if not device:
            raise HTTPException(404, "device not found")
        
        # Get historical fixes with GNSS metadata
        fixes = db.scalars(
            select(LocationHistory)
            .where(LocationHistory.device_id == device_id)
            .where(LocationHistory.gnss_metadata.is_not(None))
            .order_by(LocationHistory.timestamp.desc())
            .limit(limit)
        ).all()
        
        # Constellations are normalised by the NMEA adapter (navic_tcp/nmea.py,
        # _TALKERS: GP=GPS, GL=GLONASS, GA=Galileo, GB/BD=BeiDou, GQ=QZSS,
        # GI=NavIC) before they are stored in gnss_metadata, so no talker-ID
        # decoding is needed here.
        observed = {}
        simulator_count = 0
        hardware_count = 0
        
        for fix in fixes:
            if fix.simulated:
                simulator_count += 1
            else:
                hardware_count += 1
            
            gnss = fix.gnss_metadata or {}
            constellations = gnss.get('constellations', [])
            satellites = gnss.get('satellites', [])
            
            # Track from constellations array
            for const in constellations:
                if const not in observed:
                    observed[const] = {'count': 0, 'last_seen': fix.timestamp, 'simulated': fix.simulated}
                observed[const]['count'] += 1
                if fix.timestamp > observed[const]['last_seen']:
                    observed[const]['last_seen'] = fix.timestamp
            
            # Track from satellite details
            for sat in satellites:
                const = sat.get('constellation')
                if const:
                    if const not in observed:
                        observed[const] = {'count': 0, 'last_seen': fix.timestamp, 'simulated': fix.simulated}
                    observed[const]['count'] += 1
                    if fix.timestamp > observed[const]['last_seen']:
                        observed[const]['last_seen'] = fix.timestamp
        
        # Format results
        CONSTELLATION_NAMES = {
            'gps': 'GPS',
            'glonass': 'GLONASS',
            'galileo': 'Galileo',
            'beidou': 'BeiDou',
            'qzss': 'QZSS',
            'navic': 'NavIC',
            'mixed': 'Mixed/Unknown',
        }
        
        # Filter out constellations only observed in simulated data
        hardware_observed = {k: v for k, v in observed.items() if not v['simulated']}
        
        results = []
        for const_key, data in hardware_observed.items():
            name = CONSTELLATION_NAMES.get(const_key.lower(), const_key.upper())
            results.append({
                'constellation': name,
                'key': const_key,
                'fix_count': data['count'],
                'last_seen': data['last_seen'].isoformat() if data['last_seen'] else None,
                'observed_in_simulated': False,
            })
        
        # Sort by last_seen desc
        results.sort(key=lambda x: x['last_seen'] or '', reverse=True)
        
        return {
            "device_id": device_id,
            "total_fixes_analyzed": len(fixes),
            "hardware_fixes": hardware_count,
            "simulator_fixes": simulator_count,
            "constellations": results,
            "note": "Observed in receiver output; does not imply hardware support. Simulator data excluded from hardware evidence.",
        }


@app.post("/api/devices", response_model=DeviceOut, status_code=201, include_in_schema=False)
@app.post("/devices", response_model=DeviceOut, status_code=201)
def create_device(data: DeviceIn, user=Depends(management_user)):
    with SessionLocal() as db:
        if data.bus_id is not None and db.get(Bus, data.bus_id) is None:
            raise HTTPException(422, "bus_id does not reference a registered vehicle")
        row = TrackingDevice(**data.model_dump())
        db.add(row)
        try:
            db.flush()
            _audit(db, user, "create", "device", row.device_id, f"bus_id={row.bus_id}")
            db.commit()
            db.refresh(row)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "device_id already exists or bus_id is invalid") from None
        sync_device_registry(db, row)
        return row


@app.put("/api/devices/{device_pk}", response_model=DeviceOut, include_in_schema=False)
@app.put("/devices/{device_pk}", response_model=DeviceOut)
def update_device(device_pk: int, data: DeviceIn, user=Depends(management_user)):
    with SessionLocal() as db:
        if data.bus_id is not None and db.get(Bus, data.bus_id) is None:
            raise HTTPException(422, "bus_id does not reference a registered vehicle")
        row = db.get(TrackingDevice, device_pk)
        if not row:
            raise HTTPException(404, "device not found")
        old_device_id = row.device_id
        old_bus_id = row.bus_id
        for key, value in data.model_dump().items():
            setattr(row, key, value)
        try:
            _audit(db, user, "update", "device", row.device_id, f"bus_id={row.bus_id}")
            db.commit()
            db.refresh(row)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "device_id already exists or bus_id is invalid") from None
        if old_device_id != row.device_id:
            registry.remove(old_device_id)
        sync_device_registry(db, row)
        sync_bus_registry(db, old_bus_id)
        if row.bus_id:
            sync_bus_registry(db, row.bus_id)
        return row


@app.delete("/api/devices/{device_pk}", status_code=204, include_in_schema=False)
@app.delete("/devices/{device_pk}", status_code=204)
def delete_device(device_pk: int, user=Depends(management_user)):
    with SessionLocal() as db:
        row = db.get(TrackingDevice, device_pk)
        if not row:
            raise HTTPException(404, "device not found")
        history_count = db.scalar(select(func.count(LocationHistory.id)).where(LocationHistory.device_id == row.device_id)) or 0
        if history_count:
            raise HTTPException(
                409,
                f"device has {history_count} persisted telemetry records; deactivate it instead of deleting history",
            )
        device_id = row.device_id
        _audit(db, user, "delete", "device", device_id)
        db.delete(row)
        db.commit()
        registry.remove(device_id)


# ---------------------------------------------------------------------------
# Drivers, routes and geofences
# ---------------------------------------------------------------------------


def _route_payload(route: Route) -> dict:
    return {
        "id": route.id,
        "name": route.name,
        "identifier": route.identifier,
        "start_point": route.start_point,
        "destination": route.destination,
        "color": route.color or "#0f766e",
        "stops": route.stops or [],
        "vehicle_count": len(route.buses),
        "assigned_vehicles": [
            {"id": bus.id, "vehicle_id": bus.vehicle_id, "registration_number": bus.registration_number}
            for bus in route.buses
        ],
    }


def crud_routes(path: str, model, schema, alias: str | None = None):
    def listing(user=Depends(current_user)):
        with SessionLocal() as db:
            records = list(db.scalars(select(model).order_by(model.id)).all())
            if model is Driver:
                return [
                    {
                        "id": row.id,
                        "name": row.name,
                        "email": row.email,
                        "phone": row.phone,
                        "license_number": row.license_number,
                        "active": row.active,
                        "assigned_vehicles": [
                            {"id": bus.id, "registration_number": bus.registration_number, "vehicle_id": bus.vehicle_id}
                            for bus in row.buses
                        ],
                    }
                    for row in records
                ]
            if model is Route:
                return [_route_payload(row) for row in records]
            return records

    def creating(data: schema, user=Depends(management_user)):
        with SessionLocal() as db:
            if model is Driver:
                existing = db.scalar(select(Driver).where(Driver.email == data.email))
                if existing:
                    raise HTTPException(409, "a driver with this email already exists")
            payload = data.model_dump()
            if model is Route:
                payload["stops"] = [stop.model_dump() if hasattr(stop, "model_dump") else stop for stop in payload.get("stops", [])]
            row = model(**payload)
            db.add(row)
            try:
                db.flush()
                _audit(db, user, "create", model.__tablename__, row.id)
                db.commit()
                db.refresh(row)
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "duplicate value") from None
            return row

    def updating(item_id: int, data: schema, user=Depends(management_user)):
        with SessionLocal() as db:
            row = db.get(model, item_id)
            if not row:
                raise HTTPException(404, "record not found")
            payload = data.model_dump()
            if model is Route:
                payload["stops"] = [stop.model_dump() if hasattr(stop, "model_dump") else stop for stop in payload.get("stops", [])]
            for key, value in payload.items():
                setattr(row, key, value)
            try:
                _audit(db, user, "update", model.__tablename__, row.id)
                db.commit()
                db.refresh(row)
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "duplicate value") from None
            return row

    def deleting(item_id: int, user=Depends(management_user)):
        with SessionLocal() as db:
            row = db.get(model, item_id)
            if not row:
                raise HTTPException(404, "record not found")
            if model is Driver:
                assigned = list(db.scalars(select(Bus).where(Bus.driver_id == item_id)).all())
                if assigned:
                    raise HTTPException(
                        409,
                        "driver is assigned to vehicles; unassign them or set the driver inactive instead",
                    )
            if model is Route:
                for bus in db.scalars(select(Bus).where(Bus.route_id == item_id)).all():
                    bus.route_id = None
                    bus.route_name = None
            _audit(db, user, "delete", model.__tablename__, row.id)
            db.delete(row)
            db.commit()

    decorators = [app.get(path)]
    if alias:
        decorators.insert(0, app.get(alias, include_in_schema=False))
    for decorator in reversed(decorators):
        listing = decorator(listing)

    create_decorators = [app.post(path, status_code=201)]
    if alias:
        create_decorators.insert(0, app.post(alias, status_code=201, include_in_schema=False))
    for decorator in reversed(create_decorators):
        creating = decorator(creating)

    update_decorators = [app.put(path + "/{item_id}")]
    if alias:
        update_decorators.insert(0, app.put(alias + "/{item_id}", include_in_schema=False))
    for decorator in reversed(update_decorators):
        updating = decorator(updating)

    delete_decorators = [app.delete(path + "/{item_id}", status_code=204)]
    if alias:
        delete_decorators.insert(0, app.delete(alias + "/{item_id}", status_code=204, include_in_schema=False))
    for decorator in reversed(delete_decorators):
        deleting = decorator(deleting)


crud_routes("/drivers", Driver, DriverIn, alias="/api/drivers")
crud_routes("/routes", Route, RouteIn, alias="/api/routes")
crud_routes("/geofences", Geofence, GeofenceIn, alias="/api/geofences")


# ---------------------------------------------------------------------------
# Geofence Incidents
# ---------------------------------------------------------------------------


class GeofenceIncidentOut(BaseModel):
    id: int
    device_id: str
    geofence_id: int
    state: str  # inside, outside
    transitioned_at: datetime
    resolved_at: datetime | None
    is_read: bool
    geofence_name: str
    device_name: str | None
    vehicle_reg: str | None
    created_at: datetime


class GeofenceIncidentList(BaseModel):
    incidents: list[GeofenceIncidentOut]
    unread_count: int


@app.get("/api/geofences/incidents", response_model=GeofenceIncidentList)
def list_geofence_incidents(
    state: str | None = None,  # inside, outside, or all
    device_id: str | None = None,
    geofence_id: int | None = None,
    unread_only: bool = False,
    limit: int = 100,
    offset: int = 0,
    user=Depends(current_user),
):
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422, "invalid pagination")
    with SessionLocal() as db:
        query = select(GeofenceIncident).order_by(GeofenceIncident.transitioned_at.desc(), GeofenceIncident.id.desc())
        if state:
            query = query.where(GeofenceIncident.state == state)
        if device_id:
            query = query.where(GeofenceIncident.device_id == device_id)
        if geofence_id:
            query = query.where(GeofenceIncident.geofence_id == geofence_id)
        if unread_only:
            query = query.where(GeofenceIncident.is_read.is_(False))
        rows = list(db.scalars(query.limit(limit).offset(offset)).all())
        unread = db.scalar(select(func.count(GeofenceIncident.id)).where(GeofenceIncident.is_read.is_(False))) or 0
        
        # Enrich with geofence/device names
        results = []
        for inc in rows:
            fence = db.get(Geofence, inc.geofence_id)
            device = db.scalar(select(TrackingDevice).where(TrackingDevice.device_id == inc.device_id))
            bus = db.get(Bus, device.bus_id) if device and device.bus_id else None
            results.append({
                "id": inc.id,
                "device_id": inc.device_id,
                "geofence_id": inc.geofence_id,
                "state": inc.state,
                "transitioned_at": _iso(inc.transitioned_at),
                "resolved_at": _iso(inc.resolved_at) if inc.resolved_at else None,
                "is_read": inc.is_read,
                "created_at": _iso(inc.created_at),
                "geofence_name": fence.name if fence else f"Geofence {inc.geofence_id}",
                "device_name": device.device_id if device else inc.device_id,
                "vehicle_reg": bus.registration_number if bus else None,
            })
        return {"incidents": results, "unread_count": unread}


@app.patch("/api/geofences/incidents/{incident_id}/read")
def mark_geofence_incident_read(incident_id: int, user=Depends(management_user)):
    with SessionLocal() as db:
        inc = db.get(GeofenceIncident, incident_id)
        if not inc:
            raise HTTPException(404, "incident not found")
        inc.is_read = True
        db.commit()
        _audit(db, user, "update", "geofence_incident", str(incident_id), "marked read")
        return {"id": inc.id, "is_read": True}


@app.patch("/api/geofences/incidents/read-all")
def mark_all_geofence_incidents_read(user=Depends(management_user)):
    with SessionLocal() as db:
        result = db.execute(text("UPDATE geofence_incidents SET is_read = :value WHERE is_read = :unread"), 
                           {"value": True if engine.dialect.name != "sqlite" else 1, "unread": False if engine.dialect.name != "sqlite" else 0})
        _audit(db, user, "update", "geofence_incidents", "all", "marked all read")
        db.commit()
        return {"updated": result.rowcount or 0}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws/locations")
async def websocket_locations(ws: WebSocket, token: str | None = Query(default=None)):
    origin = ws.headers.get("origin")
    if origin and origin.rstrip("/") not in _allowed_browser_origins():
        await ws.close(code=4403)
        return
    principal = None
    bearer = ws.headers.get("authorization", "")
    if not token and bearer.lower().startswith("bearer "):
        token = bearer[7:]
    if token:
        try:
            principal = _user_from_token(token)
        except ValueError:
            principal = None
    if principal is None:
        session_cookie = ws.cookies.get(auth_service.SESSION_COOKIE)
        if session_cookie:
            with SessionLocal() as db:
                resolved = auth_service.resolve_session(db, session_cookie)
                principal = resolved[0] if resolved is not None else None
    if DEMO_AUTH_BYPASS:
        principal = {"role": "admin"}
    if principal is None:
        await ws.close(code=4401)
        return
    await hub.connect(ws, is_admin=principal.get("role") == "admin")
    try:
        while True:
            message = await ws.receive_text()
            if message == "ping":
                await ws.send_json({"type": "pong", "server_time": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        hub.disconnect(ws)
        LOG.exception("websocket client failed")


# ---------------------------------------------------------------------------
# Optional same-origin frontend hosting (single-service deployments)
# ---------------------------------------------------------------------------

_DIST = Path(
    os.getenv(
        "FRONTEND_DIST",
        str(Path(__file__).resolve().parent.parent / "frontend" / "vite" / "build"),
    )
)
# SPA paths that collide with API route prefixes.  A browser navigation must
# receive the app shell, while fetch/XHR calls (Accept: application/json) must
# still reach the API route.  Without this, refreshing /devices or /settings on
# a same-origin deployment would render the JSON API response instead of the UI.
_SPA_NAVIGATION_PATHS = {"/devices", "/drivers", "/routes", "/alerts", "/settings", "/trips"}

if _DIST.is_dir():

    @app.middleware("http")
    async def spa_navigation(request: Request, call_next):
        if (
            request.method == "GET"
            and request.url.path in _SPA_NAVIGATION_PATHS
            and "text/html" in request.headers.get("accept", "")
        ):
            return FileResponse(_DIST / "index.html")
        return await call_next(request)

    if (_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend_files(full_path: str):
        # The SPA handles this route so it can consume the token client-side and
        # immediately remove it from the address bar/history.
        if full_path in {"auth/verify", "auth/verify-email"}:
            return FileResponse(_DIST / "index.html")
        protected_prefixes = ("api/", "buses", "devices", "drivers", "routes", "alerts", "settings", "auth", "trips", "ws/")
        if full_path.startswith(protected_prefixes):
            raise HTTPException(404, "not found")
        candidate = _DIST / full_path
        if full_path and candidate.is_file() and _DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
