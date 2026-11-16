# Demo Simulation Implementation Plan

## Backend Tasks

### 1. Create Demo Simulation Module (`navic_tcp/demo_simulation.py`)
- [x] Create `DemoSimulation` class that runs as asyncio task
- [x] Use existing `simulated_telemetry` from `client.py` as base
- [x] Implement state machine: moving → idle → moving → stopped → signal lost → resume
- [x] Only emit for devices with `simulated=True` in registry
- [x] Add `scenario: "demo"` tag to telemetry
- [x] Per-vehicle looping script (~60s at 1x): moving (25-45 km/h, ignition on) → idle (speed 0, ignition on) → moving → stopped (speed 0, ignition off) → signal lost (Out of N/W) → resume
- [x] Stagger phase offsets so several colours visible
- [x] Shorter offline window (20s) for demo devices only
- [x] Throttle: ~1 fix per vehicle per 2s
- [x] Auto-stop after 10 minutes
- [x] One run at a time

### 2. Add Demo Endpoints to `navic_tcp/fastapi_app.py`
- [x] `POST /api/admin/demo/simulation/start` - Start simulation with speed multiplier
- [x] `POST /api/admin/demo/simulation/stop` - Stop simulation
- [x] `GET /api/admin/demo/simulation/state` - Get simulation state
- [x] Admin only (use `admin_user` dependency)
- [x] Gated by `DEMO_SIMULATION_ENABLED` env flag
- [x] Auto-stop after 10 minutes
- [x] One run at a time

### 3. Add Environment Variable
- [x] Add `DEMO_SIMULATION_ENABLED` to `.env.example`
- [x] Document in `.env.example`

### 4. Alert/Incident Handling
- [x] Ensure demo alerts stay labelled "Simulated"
- [x] One incident per outage (use existing logic)
- [x] No flood (use existing cooldown logic)
- [x] Demo rows labelled simulator data

### 5. Lifespan Fix
- [x] Fixed `backend_lifespan` in `backend/python_fastapi/application/main.py` to copy `demo_simulation` from shared app state to modular app state

## Frontend Tasks

### 5. Create Simulation Control Component
- [x] Compact "Simulation" row in LiveTracking left panel under "Fit all vehicles"
- [x] Start/Stop button, speed 1x/2x/4x, state text "Running, 6 vehicles"
- [x] Mini list of last 5 status changes with color dots
- [ ] Respect prefers-reduced-motion

### 6. Marker Transitions
- [x] Smooth color transition (400ms) on status change
- [x] One short pulse ring on status change
- [ ] List row pill updates and flashes once
- [ ] Dashboard status cards update
- [ ] Respect prefers-reduced-motion (instant change, no pulse)
- [ ] Faded styling only for genuinely stale devices

### 7. Topbar Simulation Mode Indicator
- [x] Pulsing dot and "Simulation running" text
- [x] All demo vehicles show Source "Simulator"

### 8. Bug Fixes
- [x] Fix vehicle card source label: derive from data-source field (Simulator/Hardware/Test replay)
- [x] Fix magnifier icon above search input - use SearchInput component
- [x] Check Dashboard side panel and Devices page for same source label bug
- [x] Check GNSS diagnostics for raw icon + input pair

## Verification
- [x] pytest: demo start/stop, refuses non-simulated devices, admin only, flag off returns 403/404, auto-stop, each status reached
- [ ] Playwright: start at 4x, within 90s at least 4 status colours appear on markers, the change list gets entries, the Dashboard counts change, stop restores normal behaviour
- [ ] Screenshots in docs/screenshots/demo/
- [ ] Report docs/DEMO_SIM_REPORT.md including Toing meaning and offline-window approach