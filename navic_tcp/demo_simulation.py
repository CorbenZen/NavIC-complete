"""Demo simulation: runs inside the FastAPI process and emits telemetry through the normal ingestion pipeline."""

from __future__ import annotations

import asyncio
import logging
import random
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from .client import simulated_telemetry
from .registry import DEFAULT_REGISTRY_PATH, DeviceRegistry

LOG = logging.getLogger("navic_tcp.demo_simulation")

# Demo configuration
DEFAULT_DEMO_DEVICES = [
    "IVTD_BUS_01",
    "IVTD_BUS_02",
    "IVTD_BUS_03",
    "IVTD_BUS_04",
    "IVTD_BUS_05",
    "IVTD_BUS_06",
]
DEFAULT_INTERVAL_SECONDS = 2.0
DEFAULT_MAX_DURATION_MINUTES = 10
DEMO_OFFLINE_WINDOW_SECONDS = 20.0  # Shorter window for demo devices


class DemoSimulation:
    """Runs a demo simulation that emits telemetry through the normal ingestion pipeline."""

    def __init__(self, on_telemetry_callback):
        self._on_telemetry = on_telemetry_callback
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._interval = DEFAULT_INTERVAL_SECONDS
        self._speed_multiplier = 1.0
        self._device_ids: list[str] = []
        self._sequences: dict[str, int] = {}
        self._phases: dict[str, float] = {}  # Track phase for each vehicle
        self._state: dict[str, str] = {}  # Current state per vehicle
        self._state_start: dict[str, datetime] = {}
        self._last_status_change: list[dict] = []  # For frontend status change log
        self._max_duration = timedelta(minutes=DEFAULT_MAX_DURATION_MINUTES)
        self._start_time: datetime | None = None

        # State durations at 1x speed (seconds)
        self._state_durations = {
            "moving": 20.0,    # Moving at 25-45 km/h
            "idle": 10.0,      # Speed 0, ignition on
            "stopped": 10.0,   # Speed 0, ignition off
            "outage": 25.0,    # Signal lost (no fixes) - longer than DEMO_OFFLINE_WINDOW_SECONDS
        }

        # Speed ranges for moving state (km/h)
        self._speed_range = (25.0, 45.0)

        # Phase offsets for staggered start (0-360 degrees)
        self._phase_offsets = [0, 60, 120, 180, 240, 300]

    def _get_demo_devices(self) -> list[str]:
        """Get list of simulated device IDs from registry."""
        try:
            registry = DeviceRegistry.load(DEFAULT_REGISTRY_PATH)
            simulated_devices = [
                entry["device_id"]
                for entry in registry.list()
                if entry.get("identifier_type", "").startswith("simulated")
            ]
            return simulated_devices[:6]  # Max 6 vehicles
        except Exception:
            LOG.warning("Could not load demo devices from registry, using defaults")
            return DEFAULT_DEMO_DEVICES

    async def start(self, device_ids: list[str] | None = None, speed_multiplier: float = 1.0) -> None:
        """Start the demo simulation."""
        if self._task and not self._task.done():
            raise RuntimeError("Simulation already running")

        self._device_ids = device_ids or self._get_demo_devices()
        if not self._device_ids:
            raise RuntimeError("No simulated devices available")

        self._speed_multiplier = max(0.5, min(4.0, speed_multiplier))
        self._interval = DEFAULT_INTERVAL_SECONDS / self._speed_multiplier
        self._sequences = {did: 0 for did in self._device_ids}
        self._phases = {did: float(self._phase_offsets[i % len(self._phase_offsets)]) for i, did in enumerate(self._device_ids)}
        self._state = {did: "moving" for did in self._device_ids}
        self._state_start = {did: datetime.now(timezone.utc) for did in self._device_ids}
        self._last_status_change = []
        self._start_time = datetime.now(timezone.utc)

        self._stop.clear()
        self._task = asyncio.create_task(self._run())
        LOG.info("Demo simulation started for %d devices at %.1fx speed", len(self._device_ids), self._speed_multiplier)

    async def stop(self) -> None:
        """Stop the demo simulation."""
        if self._task and not self._task.done():
            self._stop.set()
            await self._task
            self._task = None
            self._last_status_change = []
            LOG.info("Demo simulation stopped")

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def get_state(self) -> dict:
        """Get current simulation state for API."""
        return {
            "running": self.is_running,
            "devices": self._device_ids,
            "speed_multiplier": self._speed_multiplier,
            "states": self._state.copy(),
            "last_changes": self._last_status_change[-5:],  # Last 5 changes
            "auto_stop_at": (self._start_time + self._max_duration).isoformat() if self._start_time else None,
        }

    def _record_status_change(self, device_id: str, old_state: str, new_state: str) -> None:
        """Record a status change for the frontend log."""
        change = {
            "device_id": device_id,
            "from": old_state,
            "to": new_state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._last_status_change.append(change)
        if len(self._last_status_change) > 50:
            self._last_status_change = self._last_status_change[-50:]

    def _next_state(self, current_state: str) -> str:
        """Determine next state in the cycle."""
        cycle = ["moving", "idle", "moving", "stopped", "outage"]
        try:
            idx = cycle.index(current_state)
            return cycle[(idx + 1) % len(cycle)]
        except ValueError:
            return "moving"

    def _get_state_duration(self, state: str) -> float:
        """Get duration for a state at current speed multiplier."""
        base = self._state_durations.get(state, 10.0)
        return base / self._speed_multiplier

    async def _emit_telemetry(self, device_id: str, sequence: int, state: str) -> None:
        """Emit a single telemetry message for a device in a given state."""
        # Get base telemetry from existing simulator
        message = simulated_telemetry(device_id, sequence)
        
        # Override with demo-specific values
        message["data_source"] = "simulator"
        message["simulated"] = True
        message["scenario"] = "demo"
        
        # Set ignition and speed based on state
        if state == "moving":
            message["ignition"] = True
            # Speed 25-45 km/h with jitter
            base_speed = random.uniform(*self._speed_range)
            message["speed"] = round(base_speed + random.uniform(-2.0, 2.0), 1)
        elif state == "idle":
            message["ignition"] = True
            message["speed"] = 0.0
        elif state == "stopped":
            message["ignition"] = False
            message["speed"] = 0.0
        elif state == "outage":
            # No fixes emitted during outage - we just skip emission
            return
        
        # Add demo offline window tag for special handling
        message["demo_offline_window_seconds"] = DEMO_OFFLINE_WINDOW_SECONDS
        
        try:
            await self._on_telemetry(message)
        except Exception:
            LOG.exception("Failed to emit telemetry for %s", device_id)

    async def _run(self) -> None:
        """Main simulation loop."""
        auto_stop_time = datetime.now(timezone.utc) + self._max_duration
        
        while not self._stop.is_set():
            # Check auto-stop
            if datetime.now(timezone.utc) >= auto_stop_time:
                LOG.info("Demo simulation auto-stopped after %d minutes", DEFAULT_MAX_DURATION_MINUTES)
                break
            
            # Check for state transitions
            now = datetime.now(timezone.utc)
            for device_id in self._device_ids:
                current_state = self._state[device_id]
                state_start = self._state_start[device_id]
                elapsed = (now - state_start).total_seconds()
                state_duration = self._get_state_duration(current_state)
                
                if elapsed >= state_duration:
                    # Transition to next state
                    old_state = current_state
                    new_state = self._next_state(current_state)
                    self._state[device_id] = new_state
                    self._state_start[device_id] = now
                    self._record_status_change(device_id, old_state, new_state)
                    LOG.info("Device %s: %s -> %s", device_id, old_state, new_state)
            
            # Emit telemetry for each device based on current state
            for device_id in self._device_ids:
                state = self._state[device_id]
                if state == "outage":
                    # Skip emission to simulate signal loss
                    continue
                
                sequence = self._sequences[device_id]
                await self._emit_telemetry(device_id, sequence, state)
                self._sequences[device_id] = sequence + 1
            
            # Wait for next interval
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), self._interval)


# Global instance (set up in lifespan)
demo_simulation: DemoSimulation | None = None