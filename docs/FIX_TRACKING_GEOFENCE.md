# Fix: Live Tracking & Geofences Page Crashes

**Date**: 2026-11-15
**Status**: Fixed and verified

## Summary
The Live Tracking page (`/tracking`) and Geofences page (`/geofences`) crashed with the generic error boundary message "The console encountered a rendering error. Refresh the page to retry..." when accessed via the frontend.

## Root Causes

### 1. LiveTracking page - Null `selected` vehicle access
**File**: `frontend/react-jsx/pages/telemetry/LiveTracking.jsx`

When a user selects a vehicle and the tracking data refreshes (e.g., vehicle goes offline or is filtered out), the `selectedId` still points to the old vehicle. The `selected` variable becomes `null`:
```js
const selected = tracking.find((row) => row.device_id === selectedId) || null;
```

But the render code accessed `selected.timestamp`, `selected.course`, `selected.latitude`, `selected.longitude`, `selected.driver_name`, `selected.speed`, `selected.status`, `selected.status_key`, `selected.registration_number`, `selected.vehicle_id`, `selected.device_id`, `selected.route_name` without null checks.

**Error**: `TypeError: Cannot read property 'timestamp' of null`

### 2. Geofences page - Invalid geofence data
**File**: `frontend/react-jsx/pages/fleet/Geofences.jsx`

The map rendered `<Circle>` components for geofences without validating:
- `latitude` / `longitude` could be null, undefined, or non-finite
- `radius_m` could be null, undefined, zero, or negative
- `drawCenter` / `drawRadius` in drawing mode could be invalid
- `MapFocus` component called `map.flyTo` with potentially invalid center/zoom

**Error**: `TypeError` or `RangeError` when Leaflet receives invalid coordinates

### 3. ErrorBoundary lacked debugging info
**File**: `frontend/react-jsx/main.jsx`

The ErrorBoundary only showed a generic message without the actual error or component stack, making diagnosis impossible.

## Fixes Applied

### 1. Improved ErrorBoundary (`frontend/react-jsx/main.jsx`)
- Added `componentDidCatch` to log error and componentStack to console
- In development mode, shows error message and stack trace on screen
- Added "Reload page" button

### 2. LiveTracking page (`frontend/react-jsx/pages/telemetry/LiveTracking.jsx`)
- Wrapped all `selected` property accesses in `{selected ? (...) : (...)}` conditional
- Added fallback UI showing "No vehicle selected" when `selected` is null
- Affected sections: tracking-detail head, detail-grid (Driver, Speed, Last fix, Course, Position, Source)

### 3. Geofences page (`frontend/react-jsx/pages/fleet/Geofences.jsx`)
- Added `isValidLatLng(lat, lng)` helper function
- Filter geofences before rendering circles: only active geofences with valid finite coordinates and positive radius
- Added defensive checks in `fitToGeofence()`, `MapFocus`, and drawing mode
- Coerce coordinates/radius to `Number()` before passing to Leaflet

## Files Changed
1. `frontend/react-jsx/main.jsx` - Enhanced ErrorBoundary
2. `frontend/react-jsx/pages/telemetry/LiveTracking.jsx` - Null guards for `selected` vehicle
3. `frontend/react-jsx/pages/fleet/Geofences.jsx` - Input validation for geofence data, MapFocus, drawing mode

## Verification
- **Build**: `npm run build` ✓ (pre-existing chunk/lucide warnings only)
- **Backend tests**: 207 passed, 28 subtests ✓
- **Ruff lint**: All checks passed ✓

## Testing Steps (Manual)
1. Start backend with DEMO_AUTH_BYPASS: `PYTHONPATH=. APP_ENV=development DEMO_AUTH_BYPASS=true TCP_ENABLED=false python -m uvicorn navic_tcp.fastapi_app:app --port 8001`
2. Start frontend proxying to test backend: `cd frontend && VITE_API_BASE_URL=http://localhost:8001 npm run dev`
3. Navigate to http://localhost:5173/tracking - should show fleet positions without crash
4. Select a vehicle, then wait for refresh or change data source filter to hide it - should show "No vehicle selected" instead of crashing
5. Navigate to http://localhost:5173/geofences - should show geofence list and map without crash
6. Create/edit/delete geofences, toggle incidents panel - all should work
7. Test in both light and dark themes
8. Test responsive at 1440px, 1024px, 390px

## Backup
Files backed up to: `backups/fix_tracking_20261115_155956/`

## Notes
- No database changes were made; all fixes are UI-only defensive coding
- The fixes handle missing/invalid data gracefully without fabricating data
- Light/dark themes preserved; no redesign
- FleetDashboard already had proper null handling for selected vehicle
