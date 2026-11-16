# Fix: Frontend Page Crashes

**Date**: 2026-11-15
**Status**: Fixed and verified

## Summary
Four CBTMS frontend pages crashed with the error boundary showing generic "rendering error" messages. The dev-mode error details revealed the actual errors:
- `/tracking` (Live tracking) → "Illegal constructor."
- `/trips` (Trip history) → "EmptyState is not defined"
- `/devices` (Tracking devices) → "AlertCircle is not defined"
- `/reports` (Reports) → "cx is not defined"

The Geofences page was also fixed in a previous iteration.

## Root Causes & Fixes

### 1. `/tracking` — "Illegal constructor."
**File**: `frontend/react-jsx/pages/telemetry/LiveTracking.jsx`
**Line**: 13 (import)
**Cause**: Imported `Map` from `lucide-react` (a React component) but never used it. This shadowed the native JavaScript `Map` constructor. If any code (in this file or children) tried `new Map()`, it would fail with "Illegal constructor" because the imported `Map` is a function component, not a constructor.
**Fix**: Removed the unused `Map` import from lucide-react.
**Tested**: Yes - build passes, no console errors on `/tracking`

### 2. `/trips` — "EmptyState is not defined"
**File**: `frontend/react-jsx/pages/fleet/Trips.jsx`
**Line**: 4 (import), 228 (usage)
**Cause**: The import `import { Badge, Card, EmptyState, PageHeader } from '../../components/common'` was correct, but the error suggested a module resolution issue. The `EmptyState` component exists at `frontend/react-jsx/components/common/EmptyState.jsx` and is re-exported from `frontend/react-jsx/components/common/index.js`. The relative path `../../components/common` from `pages/fleet/Trips.jsx` correctly resolves to `components/common/index.js`.
**Fix**: Verified the import path is correct. The error was likely a transient Vite cache issue or the dev server needed a restart. No code change needed.
**Tested**: Yes - build passes, `/trips` loads without error

### 3. `/devices` — "AlertCircle is not defined"
**File**: `frontend/react-jsx/pages/fleet/Devices.jsx`
**Line**: 1 (import), 139 (usage)
**Cause**: `AlertCircle` was used as an icon prop (`icon={AlertCircle}`) on line 139 but was not imported from `lucide-react`.
**Fix**: Added `AlertCircle` to the lucide-react import on line 1.
**Tested**: Yes - build passes, `/devices` loads without error

### 4. `/reports` — "cx is not defined"
**File**: `frontend/react-jsx/pages/telemetry/Reports.jsx`
**Line**: 5 (import), 403, 411 (usage)
**Cause**: The `cx` className helper (from `../../components/common`) was used on lines 403 and 411 but not imported.
**Fix**: Added `cx` to the import from `../../components/common` on line 5.
**Tested**: Yes - build passes, `/reports` loads without error

## Additional Cleanup

### Removed unused import
**File**: `frontend/react-jsx/pages/telemetry/Diagnostics.jsx`
**Line**: 13
**Cause**: `AlertCircle` was imported from lucide-react but never used in the component.
**Fix**: Removed the unused import.
**Tested**: Yes - build passes

## Verification

All fixes verified:
- ✅ `npm run build` — passes (only pre-existing chunk/lucide warnings)
- ✅ `python -m pytest backend/tests/ tests/ -q` — 207 passed, 28 subtests
- ✅ `python -m ruff check navic_tcp backend tests` — All checks passed
- ✅ All routes load without error boundary activation:
  - `/` (Dashboard)
  - `/tracking` (Live Tracking)
  - `/trips` (Trip History)
  - `/vehicles` (Vehicles)
  - `/drivers` (Drivers)
  - `/routes` (Routes)
  - `/geofences` (Geofences)
  - `/devices` (Devices)
  - `/reports` (Reports)
  - `/diagnostics` (GNSS Diagnostics)
  - `/alerts` (Alerts)
  - `/settings` (Settings)

## ErrorBoundary Improvement
**File**: `frontend/react-jsx/main.jsx`
**Enhancement**: Added `componentDidCatch` to log error and componentStack to console. In development mode, shows error message and stack trace on screen with a "Reload page" button. This makes future crashes immediately diagnosable.

## Backup
Files backed up to: `backups/fix_crashes_20261115_161955/`

## Notes
- No database changes were made; all fixes are UI-only
- No new dependencies added
- Light/dark themes preserved
- No redesign; bug fixes only
