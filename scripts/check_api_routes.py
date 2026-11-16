"""Exercise the browser-facing API while demo simulation is stopped and running.

Run against a development backend with explicit demo auth enabled. The script
starts and stops only the simulator; it never edits or deletes persisted rows.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Direct script execution sets sys.path to scripts/, so add the project root
# before importing the backend's canonical report catalogue.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


READ_PATHS = (
    "/health",
    "/api/meta",
    "/api/dashboard/stats",
    "/api/dashboard/summary",
    "/api/dashboard/admin-summary",
    "/api/tracking/latest",
    "/trips",
    "/buses",
    "/api/drivers",
    "/api/routes",
    "/api/geofences",
    "/devices",
    "/alerts",
    "/api/alerts/incidents",
    "/settings",
    "/api/users/me/preferences",
)


def report_types() -> set[str]:
    """Read report IDs from the same backend catalogue used by the API."""
    from navic_tcp.fastapi_app import REPORT_TYPES

    return REPORT_TYPES


def request(base_url: str, path: str, method: str = "GET", body: dict | None = None) -> tuple[int, bytes]:
    """Call one API resource and return its HTTP status and response bytes."""
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=payload,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            if data and "json" in response.headers.get("content-type", ""):
                json.loads(data)
            return response.status, data
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def sweep(base_url: str, state: str) -> list[str]:
    """Call all UI data routes and both visual report variants; return failures."""
    failures = []
    paths = [*READ_PATHS]
    for report_type in sorted(report_types()):
        paths.extend(
            f"/api/reports/{report_type}?view={view}"
            for view in ("table", "charts")
        )
    for path in paths:
        status, body = request(base_url, path)
        print(f"{state} {status} {path}")
        if status >= 500 or status == 404:
            failures.append(f"{state} {path}: {status} {body[:240]!r}")
    return failures


def main() -> int:
    """Run the route sweep in stopped, 4x running, and stopped states."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("BACKEND_URL", "http://localhost:8000"),
        help="Backend origin (defaults to BACKEND_URL or http://localhost:8000).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0,
        help="Wait after starting the simulator before sweeping (for example 60).",
    )
    args = parser.parse_args()
    failures = []
    try:
        failures.extend(sweep(args.base_url, "demo-stopped"))
        status, body = request(
            args.base_url,
            "/api/admin/demo/simulation/start",
            method="POST",
            body={"speed_multiplier": 4},
        )
        print(f"demo-start {status} {body.decode('utf-8', 'replace')[:240]}")
        if status >= 400:
            failures.append(f"could not start demo simulation: {status}")
            return 1
        if args.wait_seconds > 0:
            time.sleep(args.wait_seconds)
        failures.extend(sweep(args.base_url, "demo-running-4x"))
    except (OSError, TimeoutError, urllib.error.URLError) as error:
        failures.append(f"backend request failed: {error}")
    finally:
        try:
            status, body = request(
                args.base_url,
                "/api/admin/demo/simulation/stop",
                method="POST",
                body={},
            )
            print(f"demo-stop {status} {body.decode('utf-8', 'replace')[:240]}")
            if status >= 400:
                failures.append(f"could not stop demo simulation: {status}")
        except (OSError, TimeoutError, urllib.error.URLError) as error:
            failures.append(f"could not stop demo simulation: {error}")

    failures.extend(sweep(args.base_url, "demo-stopped-after"))
    if failures:
        print("API route sweep FAIL")
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"API route sweep PASS: {len(READ_PATHS)} UI paths and {len(report_types())} report types in all three states")
    return 0


if __name__ == "__main__":
    sys.exit(main())
