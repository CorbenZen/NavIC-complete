"""SQLAlchemy models for the NavIC college bus tracking system."""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Bus(Base):
    __tablename__ = "buses"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    registration_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    driver_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    route_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id", ondelete="SET NULL"), nullable=True)
    route_id: Mapped[int | None] = mapped_column(ForeignKey("routes.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now, nullable=True)

    driver: Mapped["Driver | None"] = relationship(back_populates="buses")
    route: Mapped["Route | None"] = relationship(back_populates="buses")
    devices: Mapped[list["TrackingDevice"]] = relationship(back_populates="bus")
    share_tokens: Mapped[list["ShareToken"]] = relationship(back_populates="bus")


class TrackingDevice(Base):
    __tablename__ = "tracking_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_type: Mapped[str] = mapped_column(String(80), default="unknown")
    identifier_type: Mapped[str] = mapped_column(String(40), default="serial")
    bus_id: Mapped[int | None] = mapped_column(ForeignKey("buses.id", ondelete="SET NULL"), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now, nullable=True)

    bus: Mapped[Bus | None] = relationship(back_populates="devices")


class LocationHistory(Base):
    __tablename__ = "location_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("tracking_devices.device_id"), index=True)
    message_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    speed: Mapped[float] = mapped_column(Float)
    course: Mapped[float] = mapped_column(Float)
    simulated: Mapped[bool] = mapped_column(Boolean)
    # Provenance of this fix: "hardware" | "simulator" | "test_replay".
    # ``simulated`` is kept for compatibility; ``data_source`` is the value the
    # UI filter uses. Rows written before this column existed were backfilled
    # from ``simulated`` (true -> simulator, false -> hardware).
    data_source: Mapped[str] = mapped_column(String(24), default="hardware", server_default="hardware")
    ignition: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    odometer: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    fix_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    satellites_in_view: Mapped[int | None] = mapped_column(Integer, nullable=True)
    satellites_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pdop: Mapped[float | None] = mapped_column(Float, nullable=True)
    hdop: Mapped[float | None] = mapped_column(Float, nullable=True)
    vdop: Mapped[float | None] = mapped_column(Float, nullable=True)
    gnss_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)


Index("ix_location_device_time", LocationHistory.device_id, LocationHistory.timestamp)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("account_type IS NULL OR account_type IN ('student', 'teacher')", name="ck_users_account_type"),
        CheckConstraint("account_type IS NULL OR account_type != 'student' OR usn IS NOT NULL", name="ck_users_student_usn_required"),
        CheckConstraint("account_type IS NULL OR account_type != 'teacher' OR usn IS NULL", name="ck_users_teacher_usn_null"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    # Password accounts sign in with ``user_id``; email remains optional for
    # administrator and legacy magic-link accounts.
    user_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True, nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # ``second_name`` is the account form's field; ``last_name`` remains for
    # older profile and email-auth consumers, with both kept in sync at signup.
    second_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    usn: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_profile_complete: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(40), default="transport")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str] = mapped_column(String(256), default="")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    email_verification_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    email_verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verification_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(40), index=True)
    comments: Mapped[str] = mapped_column(String(3000))
    status: Mapped[str] = mapped_column(String(20), default="NEW", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    subject: Mapped[str] = mapped_column(String(180))
    category: Mapped[str] = mapped_column(String(48), index=True)
    description: Mapped[str] = mapped_column(String(4000))
    contact: Mapped[str | None] = mapped_column(String(254), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="NORMAL", index=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class StudentBusPass(Base):
    __tablename__ = "student_bus_passes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    bus_id: Mapped[int] = mapped_column(ForeignKey("buses.id", ondelete="RESTRICT"), index=True)
    pass_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


Index("uq_users_user_id_normalized", func.lower(func.trim(User.user_id)), unique=True)
Index("uq_users_email_normalized", func.lower(func.trim(User.email)), unique=True)
Index(
    "uq_users_student_usn_normalized",
    func.lower(func.trim(User.usn)),
    unique=True,
    sqlite_where=(User.account_type == "student") & User.usn.is_not(None),
    postgresql_where=(User.account_type == "student") & User.usn.is_not(None),
)


class MagicLinkToken(Base):
    """Single-use, hashed email sign-in token. Raw values are never stored."""

    __tablename__ = "magic_link_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    requested_ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthSession(Base):
    """Opaque browser session; only the SHA-256 token hash is persisted."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    license_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now, nullable=True)

    buses: Mapped[list[Bus]] = relationship(back_populates="driver")


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    identifier: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    start_point: Mapped[str | None] = mapped_column(String(160), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(160), nullable=True)
    color: Mapped[str] = mapped_column(String(16), default="#0f766e")
    # Ordered stop sequence: [{"name": str, "latitude": float, "longitude": float}, ...]
    stops: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=now, nullable=True)

    buses: Mapped[list[Bus]] = relationship(back_populates="route")


class Geofence(Base):
    __tablename__ = "geofences"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_m: Mapped[float] = mapped_column(Float)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(String(300))
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("tracking_devices.device_id", ondelete="SET NULL"), nullable=True, index=True
    )
    incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("alert_incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    incident: Mapped["AlertIncident | None"] = relationship(back_populates="alerts")


class AlertIncident(Base):
    """Incident grouping for alerts (e.g., device offline outages)."""

    __tablename__ = "alert_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("tracking_devices.device_id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), default="device_offline", index=True)
    state: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open, resolved
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    alert_count: Mapped[int] = mapped_column(default=1)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    alerts: Mapped[list["Alert"]] = relationship(back_populates="incident")


class SafetyAlert(Base):
    """A user-reported safety/SOS event associated with a tracked bus."""

    __tablename__ = "safety_alerts"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_safety_alerts_idempotency_key"),
        Index("ix_safety_alerts_created_at", "created_at"),
        Index("ix_safety_alerts_reason", "reason"),
        Index("ix_safety_alerts_status", "status"),
        Index("ix_safety_bus_status", "bus_id", "status"),
        Index("ix_safety_alerts_bus_id", "bus_id"),
        Index("ix_safety_status_created", "status", "created_at"),
        Index("ix_safety_alerts_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    bus_id: Mapped[int] = mapped_column(ForeignKey("buses.id", ondelete="RESTRICT"))
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_source: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(String(48))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    acknowledged_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeviceGeofenceState(Base):
    __tablename__ = "device_geofence_state"

    device_id: Mapped[str] = mapped_column(
        ForeignKey("tracking_devices.device_id", ondelete="CASCADE"), primary_key=True
    )
    geofence_id: Mapped[int] = mapped_column(ForeignKey("geofences.id", ondelete="CASCADE"), primary_key=True)
    inside: Mapped[bool] = mapped_column(Boolean, default=False)
    # Hysteresis counters
    consecutive_inside: Mapped[int] = mapped_column(default=0)
    consecutive_outside: Mapped[int] = mapped_column(default=0)


class GeofenceIncident(Base):
    """Geofence transition incidents (entry/exit with hysteresis)."""

    __tablename__ = "geofence_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("tracking_devices.device_id", ondelete="CASCADE"), index=True
    )
    geofence_id: Mapped[int] = mapped_column(ForeignKey("geofences.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(20), index=True)  # inside, outside
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    device: Mapped["TrackingDevice"] = relationship()
    geofence: Mapped["Geofence"] = relationship()


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(300))


class ShareToken(Base):
    """Cryptographically random, hashed share token for public bus page."""

    __tablename__ = "share_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    bus_id: Mapped[int] = mapped_column(ForeignKey("buses.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    bus: Mapped["Bus"] = relationship(back_populates="share_tokens")
    creator: Mapped["User | None"] = relationship()


class AuditLog(Base):
    """Small append-only trail for important management operations."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(120), default="unknown")
    actor_role: Mapped[str] = mapped_column(String(40), default="unknown")
    action: Mapped[str] = mapped_column(String(40), index=True)
    entity: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
