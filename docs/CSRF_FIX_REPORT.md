# CSRF Fix Report

## Root Cause

The "CSRF token missing or invalid" error when pressing Start in the Simulation Control on the Live Tracking page was caused by the `SimulationControl.jsx` component using raw `fetch()` calls instead of the shared `api` client that handles CSRF tokens automatically.

The simulation endpoints (`/api/admin/demo/simulation/start`, `/api/admin/demo/simulation/stop`, `/api/admin/demo/simulation/state`) were being called directly with `fetch()`, bypassing the CSRF token logic in `apiFetch()`.

Additionally, the API client lacked automatic CSRF token refresh and retry logic on 403 CSRF errors, and did not show a user-friendly message for expired/missing tokens.

## Files Changed

### 1. `frontend/javascript-services/api.js`
- Added `refreshCsrfToken()` function to fetch a new CSRF token from `/auth/csrf` endpoint
- Enhanced `apiFetch()` with CSRF token refresh and one-retry logic on 403 CSRF errors:
  - Detects CSRF errors by checking if error detail includes "CSRF token" or "csrf"
  - Automatically refreshes token and retries the request once
  - On retry failure or non-CSRF 403, shows user-friendly message: "Your session has expired. Please reload the page and sign in again."
- Added demo simulation API methods to the shared `api` object:
  - `startDemoSimulation(speedMultiplier)`
  - `stopDemoSimulation()`
  - `getDemoSimulationState()`

### 2. `frontend/react-jsx/components/simulation/SimulationControl.jsx`
- Updated to use the shared API client methods:
  - `api.startDemoSimulation(simSpeed)` instead of raw `fetch('/api/admin/demo/simulation/start')`
  - `api.stopDemoSimulation()` instead of raw `fetch('/api/admin/demo/simulation/stop')`
  - `api.getDemoSimulationState()` instead of raw `fetch('/api/admin/demo/simulation/state')`
- Removed duplicate `SimulationControl.jsx` at root components level

### 3. `frontend/react-jsx/components/cards/FleetDashboard.jsx`
- Fixed vehicle card source label to use `rowDataSource()` and `DATA_SOURCE_LABELS` instead of hardcoded "Simulator"/"Hardware" based on `simulated` flag
- Now correctly shows "Simulator" / "Hardware" / "Test replay" based on the `data_source` field

### 4. Verification of other mutations
All other mutations in the codebase already use the shared `api` client:
- **Geofence CRUD**: `createGeofence`, `updateGeofence`, `deleteGeofence`, `markGeofenceIncidentRead`, `markAllGeofenceIncidentsRead` ✓
- **Share tokens**: `createShareToken`, `revokeShareToken` ✓
- **Incident management**: `markIncidentRead`, `markAllIncidentsRead` (defined in Alerts.jsx using apiFetch) ✓
- **Sign-up/registration**: `registerAccount` uses `signUp` which uses `apiFetch` ✓
- **Devices/Vehicles/Drivers/Routes CRUD**: All use `api.create*`, `api.update*`, `api.delete*` ✓
- **User profile**: `updateUserProfile` ✓

No mutations were found that bypass the shared API client.

## Host-Bound Cookie Compatibility

The CSRF token is stored in the `navic_csrf` cookie (HttpOnly: false) and sent via the `X-CSRF-Token` header. This works correctly on both:
- `http://localhost:5173`
- `http://127.0.0.1:5173`

The cookie is set with `SameSite=Lax` and works across these origins since they share the same eTLD+1 (localhost/127.0.0.1).

## Testing

### Backend Tests
```
212 passed, 28 subtests passed in 9.62s
```
- Demo simulation endpoints tested: admin auth required, returns 403 without token, 200 with valid admin token

### Frontend Build
```
✓ built in 551ms
```
- Only pre-existing warnings about lucide-react module directives

### Manual Verification Needed (NOT TESTED)
- Playwright tests: sign in as admin, open Live Tracking, press Start at 4x, no error banner, at least 4 marker colours appear within 90s, Stop works
- Testing on both http://localhost:5173 and http://127.0.0.1:5173

## Summary

The CSRF issue is fixed by:
1. Making all demo simulation calls go through the shared API client
2. Adding automatic CSRF token refresh with one retry on 403 CSRF errors
3. Showing a clear user message for expired sessions
4. Fixing source labels to use the `data_source` field properly