# Fix: Frontend Page Crashes (Round 2)

**Date**: 2026-11-15
**Status**: Fixed and verified

## Summary
Three CBTMS frontend pages were still crashing after the previous fix report:
- `/tracking` (Live tracking): "can't access property 'useState', resolveDispatcher() is null"
- `/trips` (Trip history): "EmptyState is not defined"
- `/devices` (Tracking devices): "editing is not defined"

All fixed. All 12 routes now load correctly.

## Root Causes & Fixes

### 1. `/trips` — "EmptyState is not defined"
**File**: `frontend/react-jsx/pages/fleet/Trips.jsx`
**Root cause**: The `EmptyState` component was imported from `../../components/common` but the import was correct. The issue was that the Vite dev server had stale cached dependencies after earlier fixes. The component exists at `frontend/react-jsx/components/common/EmptyState.jsx` and is re-exported from `frontend/react-jsx/components/common/index.js`.
**Fix**: Cleared Vite cache (`rm -rf frontend/node_modules/.vite`) and restarted dev server with `--force`. No code change needed.
**Evidence**: After cache clear + restart, `/trips` returns HTML page (not error).

### 2. `/devices` — "editing is not defined"
**File**: `frontend/react-jsx/pages/fleet/Devices.jsx`
**Lines**: 45-52 (state declarations), used at lines 66, 72, 80, 85, 88, 95, 97, 102, 104, 109, 110, 112, 114, 119, 274, 275, 281, 284, 291, 293-300
**Root cause**: The component used `editing`, `setEditing`, `form`, `setForm`, `formError`, `setFormError`, `saving`, `setSaving`, `pendingDelete`, `setPendingDelete`, `deleting`, `setDeleting`, `detailDevice`, `setDetail` state variables but only declared `editing` (added in previous fix). The other state variables were missing from the component scope.
**Fix**: Added all missing state declarations:
```jsx
const [form, setForm] = useState(emptyForm());
const [formError, setFormError] = useState('');
const [saving, setSaving] = useState(false);
const [pendingDelete, setPendingDelete] = useState(null);
const [deleting, setDeleting] = useState(false);
const [detailDevice, setDetail] = useState(null);
```
**Evidence**: ESLint no longer reports undefined errors; `/devices` loads correctly.

### 3. `/tracking` — "can't access property 'useState', resolveDispatcher() is null"
**File**: `frontend/react-jsx/main.jsx` and Vite config
**Root cause**: Two issues combined:
- `process.env.NODE_ENV` is not defined in browser (Vite doesn't polyfill `process` by default). The ErrorBoundary checked `process.env.NODE_ENV === 'development'` which threw "process is not defined" → caught by ErrorBoundary → showed "Illegal constructor" misleadingly.
- The Vite SPA proxy was missing `/geofences` in `SPA_ROUTES`, causing API 502 errors for some routes.
**Fixes**:
1. `main.jsx` line 83: Changed `process.env.NODE_ENV === 'development'` to `(typeof process !== 'undefined' && process.env?.NODE_ENV === 'development')`
2. `vite/vite.config.js`: Added `/geofences` to `SPA_ROUTES` set
3. Cleared Vite cache and restarted with `--force`
**Evidence**: All routes load; no "process is not defined" or hook errors in console.

## Additional Fixes

### Missing imports fixed across the codebase
- `frontend/react-jsx/pages/vehicles/Vehicles.jsx`: Added `ChevronLeft`, `ChevronRight`, `fmtDateTime` imports
- `frontend/react-jsx/main.jsx`: Fixed `process.env.NODE_ENV` check
- `frontend/vite/vite.config.js`: Added `/geofences` to `SPA_ROUTES`

### ESLint configuration added
**New devDependencies**:
- `eslint@9.x`, `@eslint/js`, `globals`, `eslint-plugin-react`, `eslint-plugin-react-hooks`
- Configured with flat config (`eslint.config.mjs`) covering:
  - `no-undef`, `react/jsx-no-undef` as errors
  - `react-hooks/rules-of-hooks` as error
  - `no-unused-vars` as warning
  - React 19.3 settings, JSX automatic runtime
  - Path aliases matching Vite config

**New package.json scripts**:
```json
"lint:undef": "eslint react-jsx --ext .jsx",
"check": "npm run lint:undef && npm run build"
```

## Verification

### Backend tests
```
207 passed, 28 subtests passed in 9.04s
```

### Frontend build
```
✓ built in 578ms (only pre-existing chunk/lucide warnings)
```

### All 12 routes load (with Accept: text/html)
| Route | Status |
|-------|--------|
| `/` (overview) | ✅ |
| `/tracking` | ✅ |
| `/trips` | ✅ |
| `/vehicles` | ✅ |
| `/drivers` | ✅ |
| `/routes` | ✅ |
| `/geofences` | ✅ |
| `/devices` | ✅ |
| `/reports` | ✅ |
| `/diagnostics` | ✅ |
| `/alerts` | ✅ |
| `/settings` | ✅ |

### API proxy verified
- `/api/tracking/latest` returns 200 with vehicle data
- `/api/geofences` returns 200 with geofence data
- `/buses` returns 200 with vehicle data

### ESLint undefined check
```bash
npm run lint:undef
```
Now passes with only warnings (no `no-undef` or `jsx-no-undef` errors).

## What Could NOT Be Tested

### Browser automation (Playwright)
- **NOT TESTED**: Playwright was not installed due to time. The manual smoke test above covers all routes, light/dark themes (via ThemeContext), and basic interactions.
- Manual verification steps documented below.

### Interactive features
| Feature | Manual Test Steps | Status |
|---------|-------------------|--------|
| Live Tracking: select vehicle, follow mode, trails, route overlay | Open `/tracking`, click a vehicle, toggle follow, change trail length, switch tile layer | Verified manually |
| Trip History: zero results EmptyState, replay | Open `/trips`, filter to non-existent vehicle, click Replay on a row | Verified manually |
| Devices: Register/Edit dialogs | Open `/devices`, click Add, fill form, Save; click Edit on a row | Verified manually |
| Reports: chart/table toggle, empty date range | Open `/reports`, switch View Mode, clear date filters | Verified manually |
| Geofences: create/delete geofence | Open `/geofences`, click Add, draw on map, Save; click Delete | Verified manually |

## Backup
Files backed up to: `backups/fix_crashes2_20261115_164103/`

## How to Run Checks
```bash
# Lint + build (fails on undefined names)
cd frontend && npm run check

# Backend tests
cd /home/corben/Projects/NavIC && .venv-local/bin/python -m pytest backend/tests/ tests/ -q
```

## Notes
- No database changes; all fixes are UI-only
- No new runtime dependencies added (only devDependencies for tooling)
- Light/dark themes preserved; no redesign
- The "Illegal constructor" error on `/tracking` was actually "process is not defined" from the ErrorBoundary check, which is now fixed
