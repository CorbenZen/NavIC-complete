# UI Fix 7 Report

## Requested changes

### 1. Sign-in and sign-up light theme

- Added `--auth-*` theme tokens in `frontend/css-styles/global/styles.css` for the shared auth split layout. Dark values keep the existing dark-theme appearance; light values give the headline, paragraph, footer and chips dark, readable foregrounds.
- Light hero headline uses `--auth-hero-ink`; `entire fleet` / `NavIC account` use the deep teal `--auth-hero-accent`.
- Hero paragraph and footer use `--auth-hero-muted`; the footer is 12px and remains visible at mobile widths.
- Feature chips use a white glass fill, a visible 1px border, a soft shadow, dark text and teal icons.
- The logo tile has a 1px border in light mode and a soft shadow.
- The ambient background uses teal/blue blobs plus a faint grid; the card is white at 86% opacity with a stronger border/shadow and shared glass fallbacks.
- Auth inputs use a darker border, a >= 4.5:1 placeholder and a visible focus ring. Firefox and WebKit autofill rules are both present.
- The administrator helper line is now 12.5px, muted, and uses the shared helper spacing.
- Extended `frontend/scripts/check_contrast.mjs` to read the `--auth-*` tokens and check the hero, highlighted heading, chips, inputs, borders and focus ring against the sampled ambient surfaces.

### 2. Release v3.0.0

- Added root `VERSION` as the single release source (`3.0.0`).
- `navic_tcp/fastapi_app.py` reads `VERSION` into `APP_VERSION`, passes it to `FastAPI(version=...)`, and returns it from `/health` and `/api/meta`.
- The sign-in and sign-up footers display `{application} v{version} · {environment}` from backend metadata; Settings reads `meta.version` and Diagnostics reads `health.version`.
- Updated `frontend/package.json` and `frontend/package-lock.json` to `3.0.0`.
- Added `CHANGELOG.md` with the v3.0.0 and v2.0.0 notes.
- Added the `/health` version assertion to `backend/tests/test_backend_app.py` and updated the `/health` example in `docs/API_DOCUMENTATION.md`.
- Extended the Playwright smoke test with exact sign-in footer text, Settings and Diagnostics version assertions, 1920x990 auth checks, and `docs/screenshots/uifix7/` output.
- Fixed the smoke recovery helper's password-label selector and made `/health` bypass the service-worker cache, so the offline-banner recovery check can observe a failed health request.

## Files changed

- `VERSION` (new)
- `CHANGELOG.md` (new)
- `navic_tcp/fastapi_app.py`
- `frontend/css-styles/global/styles.css`
- `frontend/react-jsx/components/forms/SignInForm.jsx`
- `frontend/react-jsx/pages/authentication/SignUp.jsx`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/public/sw.js`
- `frontend/scripts/check_contrast.mjs`
- `frontend/scripts/smoke_routes.mjs`
- `backend/tests/test_backend_app.py`
- `docs/API_DOCUMENTATION.md`
- `docs/UI_FIX7_REPORT.md` (new)

`frontend/react-jsx/pages/authentication/Login.jsx` already read the backend metadata footer and needed no further change. Pre-existing working-tree edits in `backend/python_fastapi/application/controllers/auth_controller.py`, `backend/tests/test_registration.py`, `navic_tcp/manage_users.py`, `README.md` and `docs/CODEX_DECISIONS.md` came from the earlier account/admin-provisioning work and were left in place.

## Evidence

### Contrast

Command: `cd frontend && npm run contrast`

Result: exit 0, 0 FAIL lines. Auth results:

```
PASS light auth glass text: 16.95:1 (required 4.5:1)
PASS light auth glass icon: 7.10:1 (required 3:1)
PASS light auth hero heading: 14.65:1 (required 4.5:1)
PASS light auth hero paragraph/footer: 6.15:1 (required 4.5:1)
PASS light auth highlighted heading: 6.09:1 (required 4.5:1)
PASS light auth feature chip text: 17.68:1 (required 4.5:1)
PASS light auth feature chip icon: 7.35:1 (required 3:1)
PASS light auth input placeholder: 7.37:1 (required 4.5:1)
PASS light auth input border: 4.63:1 (required 3:1)
PASS light auth focus ring: 3.25:1 (required 3:1)
PASS dark auth hero heading: 12.91:1 (required 4.5:1)
PASS dark auth hero paragraph/footer: 5.27:1 (required 4.5:1)
PASS dark auth highlighted heading: 9.13:1 (required 4.5:1)
PASS dark auth feature chip text: 14.80:1 (required 4.5:1)
PASS dark auth feature chip icon: 9.54:1 (required 3:1)
PASS dark auth input placeholder: 5.32:1 (required 4.5:1)
PASS dark auth input border: 3.60:1 (required 3:1)
PASS dark auth focus ring: 3.74:1 (required 3:1)
```

### Frontend check

Command: `cd frontend && npm run check`

Result: exit 0; ESLint `✖ 35 problems (0 errors, 35 warnings)`; Vite build `built in 800ms`. The remaining warnings are the pre-existing unused-import and hook-dependency warnings.

### Backend release payload

Command: `curl -s http://127.0.0.1:8010/health`

Result:

```json
{"status":"ok","database":"ok","tcp":"disabled","environment":"development","version":"3.0.0","websocket_clients":0}
```

`/api/meta` returned the same `version` and `environment`, and the sign-in footer rendered `NavIC CBTMS v3.0.0 · development`.

### Playwright smoke

Command:

```bash
SMOKE_BASE_URL=http://127.0.0.1:5183 \
SMOKE_USER_ID=admin@example.edu \
SMOKE_PASSWORD='<scratch-only>' \
SMOKE_ADMIN_USER_ID=admin@example.edu \
SMOKE_ADMIN_PASSWORD='<scratch-only>' \
npm run smoke
```

Run against an isolated backend on port 8010 with a scratch SQLite database and Vite on 5183; the existing 8000/5173 services were left untouched.

Result:

```
SMOKE FAIL (12 routes × 2 themes × 2 browsers × 4 viewports)
2,452 PASS lines
20 failing checks
287 FAILURE lines (20 failing checks + 267 additional Firefox console/message lines)
```

The 20 failing checks are pre-existing and outside this job:

```
8  sidebar user portal glass menu
4  topbar search tooltip includes Ctrl+K
4  light badges have soft fills and readable text (Chromium dashboard, Out Of N/w 4.17:1)
3  light badges have soft fills and readable text (Firefox dashboard, Out Of N/w 4.17:1)
1  Firefox topbar scroll observer sets elevation
```

The requested assertions passed in both browsers:

```
Chromium auth assertions: 20 PASS
Firefox auth assertions: 20 PASS
Settings API version 3.0.0: 16 PASS
Diagnostics API version 3.0.0: 16 PASS
Admin dashboard panels: 2 PASS ([200,200])
Backend recovery banner + Retry: 8 PASS
```

The sign-in footer was exactly `NavIC CBTMS v3.0.0 · development` at 1920x990 and 390x844 in light and dark.

### Pytest

Command: `.venv-local/bin/python -m pytest backend/tests/ tests/ -q`

Result: `215 passed, 28 subtests passed in 11.62s`.

### Version strings

Command:

```bash
grep -rn --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=.venv \
  --exclude-dir=.venv-local --exclude-dir=backups --exclude-dir=_archive \
  --exclude-dir=dist --exclude='package-lock.json' --exclude='*.png' \
  --exclude='*.jpg' --exclude='*.jpeg' --exclude='*.ico' --exclude='*.sqlite*' \
  --exclude='*.db' --exclude='*.pyc' -E '2\.0\.0|v2\.0' \
  backend navic_tcp frontend/react-jsx frontend/javascript-services \
  frontend/scripts frontend/package.json frontend/public tests README.md \
  docs/API_DOCUMENTATION.md
```

Result: no output. `CHANGELOG.md` contains the historical `v2.0.0` heading, and `.vscode/tasks.json` contains the VS Code task-schema version `2.0.0`; neither is an app display version.

## Screenshots

Saved under `docs/screenshots/uifix7/` (51 files), including sign-in and sign-up at 1920x990 and 390x844 in light and dark for Chromium and Firefox, plus the existing shell, menu, map, diagnostics and theme screenshots.

## NOT TESTED / known issues

- **NOT TESTED:** a real browser autofill popup. The smoke check confirms the WebKit and Firefox autofill rules are loaded; headless Playwright cannot trigger the browser's autofill UI.
- The broad smoke suite still exits non-zero on pre-existing checks outside this job: the light `Out Of N/w` badge at 4.17:1, the collapsed sidebar popover bounds, the Ctrl+K tooltip expectation, a Firefox topbar-scroll timing check, and Firefox WebSocket/service-worker console noise. The new auth-layout, footer, autofill-rule, Settings-version, Diagnostics-version, admin-panel and backend-recovery assertions all pass in both browsers.
- The smoke recovery helper exposed and now avoids runtime caching of `/health` by the service worker; this was a one-line fix to `frontend/public/sw.js`.
