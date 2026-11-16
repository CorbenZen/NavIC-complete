# NavIC handoff notes

## Work completed

- Fixed `frontend/javascript-services/api.js` so every non-2xx response becomes an `ApiError`, instead of allowing most error responses to be mistaken for successful data. This was the cause of anonymous `/sign-up` visits being treated as signed in after `/api/auth/me` returned 401. The same control-flow issue caused successful responses to return `undefined`, which broke login when the UI read `result.user`.
- Kept same-origin API requests enabled when `VITE_API_BASE_URL` is unset. This supports both the Vite proxy and the FastAPI deployment that serves the built frontend and API on one origin.
- Fixed `frontend/react-jsx/context/FleetContext.jsx` to use the existing `api.getDemoSimulationState()` method rather than nonexistent `api.get()`.
- Backups of edited source files are in `backups/emergency_repair_20261115T212711Z/` and `backups/emergency_repair_20261115T212817Z/`.

## Evidence collected

- `npm run check` completed successfully: 0 lint errors, 35 warnings, production build completed.
- A Playwright check against a disposable SQLite database showed `/sign-up` remains on the signup form after an anonymous `/api/auth/me` 401 and does not mount the protected fleet shell.
- Registration returned HTTP 201; login returned HTTP 200 and navigated to `/overview` with the returned session.
- All six Dashboard status filters were clicked in light and dark themes. Their count circles retained teal, green, red, blue, gray, and purple fills with readable foreground text.
- The FastAPI-hosted production build loaded `/sign-up` and called `/api/meta` on the same origin successfully.
- `npm run smoke` did not pass. It ran Chromium and Firefox checks but reported multiple pre-existing assertions: a light Out Of N/W badge had 4.17:1 contrast; viewer-role restrictions caused the route assertions to fail on restricted pages; the Firefox Geofences check encountered a missing element; additional popup/tooltip and WebSocket checks failed.
- Full `pytest` did not complete: `ApplicationCompositionTests::test_every_shared_route_is_registered` stalled. A run excluding `backend/tests/test_backend_app.py` completed with 185 passed. The isolated composition test also stalled until a 25-second timeout.

## Suggested next steps

1. Investigate why `test_every_shared_route_is_registered` stalls during collection/execution, then rerun the complete pytest command from `AGENTS.md` using a disposable `DATABASE_URL`.
2. Triage the existing smoke failures individually. Use an admin smoke account where route access is expected; retain separate viewer authorization checks.
3. Fix the measured Out Of N/W badge contrast and missing Geofences test element if confirmed against the current UI.
4. Re-run `npm run check`, `npm run smoke`, and the complete scoped pytest command. Do not report the entire site as clear until those checks pass.

No Git commands were run, following the repository's `AGENTS.md`. The temporary browser account and database used for the checks were disposable and kept under `/tmp`.
