"""Command line entry point: python -m navic_tcp.client_main"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow direct execution: python navic_tcp/client_main.py
# (or running this file from inside the navic_tcp folder).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "navic_tcp"

import argparse
import asyncio
import contextlib
import logging
import os
import signal

from .client import (
    load_simulated_registry,
    run_interactive,
    run_simulator,
    simulator_device_ids,
)
from .env import load_env_file

# The FastAPI application is seeded with IVTD_BUS_01..06, so the demo CLI
# defaults to the matching registry.  Pass --registry config/devices.json for
# the older SIM-* demo.
DEFAULT_SIM_REGISTRY = Path(__file__).resolve().parent.parent / "config" / "devices.demo.json"


async def _run(args: argparse.Namespace) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    if args.interactive:
        if args.devices != 1:
            raise SystemExit("--interactive can only be used with --devices 1")
        await run_interactive(args.host, args.port, stop)
        return
    registry = load_simulated_registry(args.registry)
    if args.device_id:
        if args.devices != 1:
            raise SystemExit("--device-id can only be used with --devices 1")
        if registry.get(args.device_id) is None:
            raise SystemExit("--device-id must exist in the selected fictional registry")
        ids = [args.device_id]
    else:
        try:
            ids = simulator_device_ids(args.devices, registry)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    default_token = args.auth_token or os.getenv("DEVICE_AUTH_TOKEN") or None
    await asyncio.gather(*(
        run_simulator(
            args.host,
            args.port,
            device_id,
            args.interval,
            args.count,
            args.retry_base,
            args.retry_max,
            stop,
            args.base_lat,
            args.base_lon,
            (registry.get(device_id) or {}).get("device_secret") or default_token,
        )
        for device_id in ids
    ))


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="Send simulated NavIC/GNSS telemetry over TCP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--device-id", help="select one ID from the fictional device registry (requires --devices 1)")
    parser.add_argument("--registry", default=str(DEFAULT_SIM_REGISTRY), help="demo device registry JSON")
    parser.add_argument("--devices", type=int, default=1, help="number of concurrent simulated clients")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--count", type=int, default=1, help="messages to send; omit for continuous simulation")
    parser.add_argument("--continuous", action="store_true", help="run until interrupted")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="open one connection and send each typed line (quit/exit to close)",
    )
    parser.add_argument("--retry-base", type=float, default=0.5)
    parser.add_argument("--retry-max", type=float, default=10.0)
    parser.add_argument("--base-lat", type=float, default=13.0435, help="synthetic loop centre latitude (HKBK campus demo area)")
    parser.add_argument("--base-lon", type=float, default=77.6200, help="synthetic loop centre longitude (HKBK campus demo area)")
    parser.add_argument(
        "--auth-token",
        default=None,
        help="optional shared device auth token (falls back to DEVICE_AUTH_TOKEN)",
    )
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    if args.interval < 0 or args.retry_base <= 0 or args.retry_max < args.retry_base:
        parser.error("interval must be >= 0; retry-max must be >= retry-base > 0")
    if not (-90 <= args.base_lat <= 90 and -180 <= args.base_lon <= 180):
        parser.error("base-lat/base-lon must be valid WGS-84 coordinates")
    if args.count is not None and args.count < 1:
        parser.error("count must be positive")
    if args.devices < 1:
        parser.error("devices must be positive")
    if args.continuous:
        args.count = None
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run(args))


if __name__ == "__main__":
    main()
