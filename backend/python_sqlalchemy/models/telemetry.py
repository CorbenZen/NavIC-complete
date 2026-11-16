"""Telemetry ORM models: stored fixes and per-device geofence state."""

from navic_tcp.models import DeviceGeofenceState, LocationHistory

__all__ = ["DeviceGeofenceState", "LocationHistory"]
