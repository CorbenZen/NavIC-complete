# UI Fix 6 report

## Changes

- Collapsed Devices and Alerts badges are now 10px solid circles with a 2px ring matching the rail surface and a subtle danger-colour shadow. The solid count fill is shared with the expanded badges.
- The count description is part of the link's accessible name and collapsed tooltip. The decorative badge itself is hidden from assistive technology.
- Added theme tokens for the rail surface, count fill, and footer status dots. The dark danger fill is `#c02626` so the dot has the required contrast against the dark rail while staying in the existing red family.
- The contrast script now checks the collapsed count dot, expanded badge text, and footer connection states.

## Evidence

- `cd frontend && npm run contrast`: PASS in light and dark. Count-dot contrast is 6.28:1 (light) and 3.06:1 (dark); footer connected-dot contrast is 4.79:1 and 10.39:1. All script checks passed.
- `cd frontend && npm run check`: exit 0; build passed and lint reported 0 errors (35 existing warnings).
- `cd frontend && npm run smoke`: NOT TESTED. Chromium could not launch (`Target page, context or browser has been closed`); Firefox failed navigating to `http://localhost:5173/` with `NS_ERROR_OUT_OF_MEMORY`. No browser screenshots were produced.
- Local browser access was unavailable, so the requested visual screenshots and computed browser bounding-box check are NOT TESTED.

## Files and backup

- Changed: `frontend/css-styles/global/styles.css`, `frontend/react-jsx/components/navigation/Sidebar.jsx`, `frontend/scripts/check_contrast.mjs`.
- Backup copies: `backups/uifix6_20261115T225756Z/` with matching relative paths.
- Screenshot directory requested: `docs/screenshots/uifix6/` — no screenshots created because the browser checks could not run.
