"""Command line entry point: python -m navic_tcp.server_main"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow direct execution: python navic_tcp/server_main.py
# (or running this file from inside the navic_tcp folder).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "navic_tcp"

import argparse
import asyncio
import contextlib
import errno
import logging
import signal

from .api import TrackingApiServer
from .registry import DEFAULT_REGISTRY_PATH, DeviceRegistry
from .server import TelemetryServer
from .store import TelemetryStore


class StartupError(RuntimeError):
    """A listener could not bind to its requested address."""


def _listener_error(label: str, host: str, port: int, exc: OSError) -> StartupError:
    detail = str(exc)
    detail_lower = detail.lower()
    option = "--api-port" if label == "HTTP API" else "--port"
    if exc.errno == errno.EADDRINUSE or "address already in use" in detail_lower:
        reason = "address already in use"
        action = f"Choose another port with {option}."
    elif exc.errno == errno.EACCES or "permission denied" in detail_lower:
        reason = "permission denied"
        action = "Check local permissions or sandbox socket restrictions."
    else:
        reason = exc.strerror or detail
        action = f"Check the bind address and select an available port with {option}."
    return StartupError(f"Could not start {label} at {host}:{port}: {reason}. {action}")


async def _run(args: argparse.Namespace) -> None:
    store = TelemetryStore(args.history_limit, DeviceRegistry.load(args.registry))
    server = TelemetryServer(args.host, args.port, args.dedupe_limit, store)
    api = TrackingApiServer(store, args.api_host, args.api_port)
    try:
        await server.start()
    except OSError as exc:
        raise _listener_error("TCP server", args.host, args.port, exc) from None
    try:
        await api.start()
    except OSError as exc:
        await server.close()
        raise _listener_error("HTTP API", args.api_host, args.api_port, exc) from None
    except BaseException:
        await server.close()
        raise
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await asyncio.gather(server.close(), api.close())


def main() -> None:
    parser = argparse.ArgumentParser(description="Local TCP server for newline-delimited NavIC/GNSS telemetry")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: loopback only)")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--dedupe-limit", type=int, default=10_000, help="in-memory recent message IDs retained")
    parser.add_argument("--history-limit", type=int, default=100, help="recent points retained per device")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH), help="fictional device/vehicle/driver registry JSON")
    parser.add_argument("--api-host", default="127.0.0.1", help="HTTP API bind address (loopback by default)")
    parser.add_argument("--api-port", type=int, default=8001, help="HTTP API port (default: 8001)")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        asyncio.run(_run(args))
    except KeyboardInterrupt:
        pass
    except StartupError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
