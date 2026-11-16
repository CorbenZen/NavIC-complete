"""Versioned newline-delimited JSON telemetry protocol."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

MAX_MESSAGE_BYTES = 64 * 1024
_DEVICE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_REQUIRED = {
    "protocol_version",
    "type",
    "message_id",
    "device_id",
    "timestamp",
    "latitude",
    "longitude",
    "speed",
    "course",
    "ignition",
    "simulated",
}
_OPTIONAL = {"odometer", "gnss", "auth_token", "data_source"}
_DATA_SOURCES = {"hardware", "simulator", "test_replay"}
_CONSTELLATIONS = {"navic", "gps", "glonass", "galileo", "beidou", "qzss"}


class MessageError(ValueError):
    """A safe-to-return protocol validation error."""

    def __init__(self, code: str, message: str, message_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.message_id = message_id


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(value: Any, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MessageError("invalid_field", f"{field} must be a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise MessageError("invalid_field", f"{field} is outside its allowed range")
    return float(value)


def decode_telemetry(line: bytes) -> dict[str, Any]:
    """Decode one framed telemetry object and enforce the public schema."""
    if len(line) > MAX_MESSAGE_BYTES:
        raise MessageError("message_too_large", "message exceeds the 65536-byte limit")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MessageError("invalid_json", "message must be valid UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise MessageError("invalid_message", "message must be a JSON object")

    message_id = value.get("message_id") if isinstance(value.get("message_id"), str) else None
    missing = _REQUIRED - value.keys()
    unknown = value.keys() - (_REQUIRED | _OPTIONAL)
    if missing:
        raise MessageError("missing_fields", f"missing required fields: {', '.join(sorted(missing))}", message_id)
    if unknown:
        raise MessageError("unknown_fields", f"unsupported fields: {', '.join(sorted(unknown))}", message_id)
    if value["protocol_version"] != 1 or isinstance(value["protocol_version"], bool):
        raise MessageError("unsupported_protocol", "protocol_version must be 1", message_id)
    if value["type"] != "telemetry":
        raise MessageError("invalid_message", "type must be telemetry", message_id)

    try:
        canonical_id = str(UUID(value["message_id"]))
    except (ValueError, TypeError, AttributeError):
        raise MessageError("invalid_field", "message_id must be a UUID", message_id) from None
    if canonical_id != value["message_id"].lower():
        raise MessageError("invalid_field", "message_id must use canonical UUID form", message_id)

    device_id = value["device_id"]
    if not isinstance(device_id, str) or not _DEVICE_ID.fullmatch(device_id):
        raise MessageError("invalid_field", "device_id must be 1-64 safe identifier characters", canonical_id)

    timestamp = value["timestamp"]
    if not isinstance(timestamp, str) or not _TIMESTAMP.fullmatch(timestamp):
        raise MessageError("invalid_field", "timestamp must be an RFC 3339 UTC value ending in Z", canonical_id)
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError:
        raise MessageError("invalid_field", "timestamp must be a valid RFC 3339 UTC value", canonical_id) from None
    if parsed_timestamp.utcoffset() != timezone.utc.utcoffset(parsed_timestamp):
        raise MessageError("invalid_field", "timestamp must be UTC", canonical_id)

    latitude = _number(value["latitude"], "latitude", -90, 90)
    longitude = _number(value["longitude"], "longitude", -180, 180)
    speed = _number(value["speed"], "speed", 0, 400)
    course = _number(value["course"], "course", 0, 360)
    if course >= 360:
        raise MessageError("invalid_field", "course must be less than 360 degrees", canonical_id)
    if not isinstance(value["ignition"], bool):
        raise MessageError("invalid_field", "ignition must be a boolean", canonical_id)
    if not isinstance(value["simulated"], bool):
        raise MessageError("invalid_field", "simulated must be a boolean", canonical_id)
    data_source = value.get("data_source")
    if data_source is None:
        # Older senders only set ``simulated``. Derive the explicit provenance
        # from it instead of guessing from device names.
        data_source = "simulator" if value["simulated"] else "hardware"
    elif not isinstance(data_source, str) or data_source not in _DATA_SOURCES:
        raise MessageError(
            "invalid_field",
            "data_source must be one of hardware, simulator, test_replay",
            canonical_id,
        )
    elif value["simulated"] != (data_source != "hardware"):
        raise MessageError(
            "invalid_field",
            "simulated must be true for simulator/test_replay and false for hardware",
            canonical_id,
        )

    normalized = dict(value)
    normalized["message_id"] = canonical_id
    normalized["data_source"] = data_source
    normalized["latitude"] = latitude
    normalized["longitude"] = longitude
    normalized["speed"] = speed
    normalized["course"] = course
    if "odometer" in value:
        normalized["odometer"] = _number(value["odometer"], "odometer", 0, 10_000_000)
    if "auth_token" in value:
        token = value["auth_token"]
        if not isinstance(token, str) or not 1 <= len(token) <= 128:
            raise MessageError("invalid_field", "auth_token must be a string of 1-128 characters", canonical_id)
        normalized["auth_token"] = token
    if "gnss" in value:
        gnss=value["gnss"]
        if not isinstance(gnss,dict):
            raise MessageError("invalid_field", "gnss must be an object", canonical_id)
        allowed={"altitude_m","fix_valid","satellites_in_view","satellites_used","pdop","hdop","vdop","constellations","satellites"}
        if gnss.keys()-allowed:
            raise MessageError("invalid_field", "gnss contains unsupported fields", canonical_id)
        clean=dict(gnss)
        if "fix_valid" in gnss and not isinstance(gnss["fix_valid"],bool):
            raise MessageError("invalid_field", "gnss.fix_valid must be boolean", canonical_id)
        if gnss.get("fix_valid") is False:
            raise MessageError("no_fix", "telemetry without a valid GNSS fix cannot be stored as a location", canonical_id)
        for key,low,high in (("altitude_m",-1000,100000),("pdop",0,999),("hdop",0,999),("vdop",0,999)):
            if key in gnss:clean[key]=_number(gnss[key],f"gnss.{key}",low,high)
        for key in ("satellites_in_view","satellites_used"):
            if key in gnss:
                n=gnss[key]
                if isinstance(n,bool) or not isinstance(n,int) or not 0<=n<=255:
                    raise MessageError("invalid_field",f"gnss.{key} must be an integer from 0 to 255",canonical_id)
        if "constellations" in gnss:
            values=gnss["constellations"]
            if not isinstance(values,list) or any(not isinstance(x,str) or x not in _CONSTELLATIONS for x in values):
                raise MessageError("invalid_field","gnss.constellations contains an unsupported value",canonical_id)
            clean["constellations"]=sorted(set(values))
        if "satellites" in gnss:
            sats=gnss["satellites"]
            if not isinstance(sats,list) or len(sats)>255:
                raise MessageError("invalid_field","gnss.satellites must be a list of at most 255 records",canonical_id)
            normalized_sats=[]
            for sat in sats:
                if not isinstance(sat,dict) or sat.keys()-{"constellation","satellite_id","signal_id","cn0_db_hz","elevation_deg","azimuth_deg"}:
                    raise MessageError("invalid_field","invalid GNSS satellite record",canonical_id)
                constellation=sat.get("constellation")
                sid=sat.get("satellite_id")
                if (constellation is not None and (not isinstance(constellation,str) or constellation not in _CONSTELLATIONS)) or isinstance(sid,bool) or not isinstance(sid,int) or not 1<=sid<=999:
                    raise MessageError("invalid_field","invalid GNSS satellite identity",canonical_id)
                item={"satellite_id":sid}
                if constellation is not None:item["constellation"]=constellation
                if "signal_id" in sat:item["signal_id"]=str(sat["signal_id"])
                if "cn0_db_hz" in sat:item["cn0_db_hz"]=_number(sat["cn0_db_hz"],"gnss.cn0_db_hz",0,99)
                for key in ("elevation_deg","azimuth_deg"):
                    if key in sat:item[key]=_number(sat[key],f"gnss.{key}",-90 if key=="elevation_deg" else 0,90 if key=="elevation_deg" else 360)
                normalized_sats.append(item)
            clean["satellites"]=normalized_sats
        normalized["gnss"]=clean
    return normalized


def encode_message(message: dict[str, Any]) -> bytes:
    return (json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def acknowledgement(message_id: str, duplicate: bool) -> dict[str, Any]:
    return {
        "type": "ack",
        "message_id": message_id,
        "status": "duplicate" if duplicate else "accepted",
        "duplicate": duplicate,
        "received_at": utc_now(),
    }


def error_response(error: MessageError) -> dict[str, Any]:
    return {
        "type": "error",
        "message_id": error.message_id,
        "error": {"code": error.code, "message": error.message},
    }
