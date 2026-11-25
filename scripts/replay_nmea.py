#!/usr/bin/env python3
"""
NMEA log replayer for CBTMS NavIC.

Reads a raw NMEA log (one sentence per line) and sends each sentence
as a telemetry message to the TCP ingestion endpoint.  The script is
intended for regression testing and demonstration with recorded data.

Usage:
    python scripts/replay_nmea.py fixtures/demo.nmea \
        --host 127.0.0.1 --port 5000 \
        --device-id IVTD_BUS_01 --interval 1.0
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from navic_tcp.nmea import NMEAParser
from navic_tcp.protocol import encode_message

LOG = logging.getLogger("replay_nmea")

# NMEA sentence pattern (starts with $ or !, ends with *XX checksum)
NMEA_LINE = re.compile(r"^[\$!]([A-Z]{2})([A-Z]{3}),(.*)\*([0-9A-Fa-f]{2})$")

# Talker ID to constellation mapping (per NMEA 0183)
_TALKERS = {
    "GP": "gps",
    "GL": "glonass",
    "GA": "galileo",
    "GB": "beidou",
    "BD": "beidou",
    "GQ": "qzss",
    "GI": "navic",
    "GN": "mixed",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay NMEA log to NavIC TCP endpoint")
    parser.add_argument("nmea_file", type=Path, help="Path to NMEA log file")
    parser.add_argument("--host", default="127.0.0.1", help="TCP host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="TCP port (default: 5000)")
    parser.add_argument("--device-id", default="REPLAY_DEVICE_01", help="Device ID to use")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between sentences (default: 1.0)")
    parser.add_argument("--simulated", action="store_true", help="Mark messages as simulated")
    parser.add_argument("--data-source", choices=["hardware", "simulator", "test_replay"], default="test_replay")
    parser.add_argument("--auth-token", help="Optional auth token")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return parser.parse_args()


def verify_checksum(line: str) -> bool:
    """Verify NMEA sentence checksum."""
    match = NMEA_LINE.match(line.strip())
    if not match:
        return False
    body = line[1:line.index("*")]
    expected = int(line[line.index("*") + 1 : line.index("*") + 3], 16)
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    return calc == expected


def nmea_to_telemetry(sentence: str, device_id: str, simulated: bool, data_source: str) -> dict[str, Any] | None:
    """Convert a valid NMEA sentence to a NavIC telemetry message."""
    try:
        parser = NMEAParser()
        result = parser.parse(sentence)
        if not result.get("fix_valid"):
            return None
        
        # Extract position, speed, course
        lat = result.get("latitude")
        lon = result.get("longitude")
        speed_kn = result.get("speed_knots")
        course = result.get("course")
        
        if lat is None or lon is None:
            return None
        
        # Convert knots to km/h
        speed_kmh = round(speed_kn * 1.852, 2) if speed_kn is not None else 0.0
        
        # Build gnss metadata
        constellations = result.get("constellations", [])
        satellites = []
        for sat in result.get("satellites", []):
            if sat.get("constellation"):
                satellites.append({
                    "constellation": sat["constellation"],
                    "satellite_id": sat.get("satellite_id"),
                    "cn0_db_hz": sat.get("cn0_db_hz"),
                    "elevation_deg": sat.get("elevation_deg"),
                    "azimuth_deg": sat.get("azimuth_deg"),
                })
        
        message = {
            "protocol_version": 1,
            "type": "telemetry",
            "message_id": str(uuid4()),
            "device_id": device_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "speed": speed_kmh,
            "course": round(course, 2) if course is not None else 0.0,
            "ignition": True,
            "odometer": 0.0,
            "simulated": simulated,
            "data_source": data_source,
        }
        
        if constellations or satellites:
            message["gnss"] = {}
            if constellations:
                message["gnss"]["constellations"] = constellations
            if satellites:
                message["gnss"]["satellites"] = satellites
        
        return message
        
    except Exception as exc:
        LOG.debug("Failed to convert NMEA to telemetry: %s", exc)
        return None


async def send_message(host: str, port: int, message: dict[str, Any]) -> bool:
    """Send a single telemetry message to the TCP endpoint."""
    try:
        reader, writer = await asyncio.open_connection(host, port)
        payload = encode_message(message)
        writer.write(payload)
        await writer.drain()
        
        # Read response (ack or error)
        try:
            response = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            LOG.debug("Response: %s", response.decode(errors="replace").strip())
        except TimeoutError:
            pass
        
        writer.close()
        await writer.wait_closed()
        return True
    except Exception as exc:
        LOG.error("Send failed: %s", exc)
        return False


async def main() -> int:
    args = parse_args()
    
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    
    if not args.nmea_file.is_file():
        LOG.error("File not found: %s", args.nmea_file)
        return 1
    
    LOG.info("Replaying %s to %s:%d (device=%s, source=%s)",
             args.nmea_file, args.host, args.port, args.device_id, args.data_source)
    
    sent = 0
    skipped = 0
    errors = 0
    
    with args.nmea_file.open("r") as fh:
        for line_num, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            if not verify_checksum(line):
                LOG.warning("Line %d: invalid checksum, skipping: %s", line_num, line[:80])
                errors += 1
                continue
            
            message = nmea_to_telemetry(line, args.device_id, args.simulated, args.data_source)
            if not message:
                LOG.debug("Line %d: not a usable fix sentence: %s", line_num, line[:80])
                skipped += 1
                continue
            
            ok = await send_message(args.host, args.port, message)
            if ok:
                sent += 1
                LOG.info("Sent message %s (fix: %.6f, %.6f)", message["message_id"], message["latitude"], message["longitude"])
            else:
                errors += 1
            
            if args.interval > 0:
                await asyncio.sleep(args.interval)
    
    LOG.info("Done: sent=%d skipped=%d errors=%d", sent, skipped, errors)
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
