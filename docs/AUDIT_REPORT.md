# NavIC CBTMS — Audit Report (2026-11-15)

**Auditor role**: AUDITOR / CLEANER
**Branch**: `feature/cbtms-roadmap` (all changes uncommitted)
**Baseline backups**: `backups/pre_audit_20261115_150308/`, `backups/pre_audit_20261115_150308.sqlite`, `backups/pre_audit_20261115_150308_live.sqlite3`

---

## Scoreboard

| Category | Baseline | Final | Notes |
|----------|----------|-------|-------|
| Python syntax (`py_compile`) | PASS | PASS | |
| Backend + TCP tests (`pytest`) | 170 passed, 28 subtests | **207 passed, 28 subtests** | +37 new tests |
| Ruff lint | **66 errors** | **PASS (0 errors)** | All fixed |
| Frontend build (`npm run build`) | PASS (warnings) | **PASS** | Pre-existing chunk/lucide warnings unchanged |
| Backend boot (`/health`) | OK | **OK** | TCP listening on :5000 |
| Alembic migration | DB at 0004, head 0006 | **Head at 0007** | Upgrade/downgrade tested on copies |
| Public share endpoints | **500 / broken** | **WORKING** | Create → page → status → revoke → 410 |
| Geofences page | **Crash (undefined fn)** | **WORKING** | Draw, edit, delete, incidents |
| Vehicles share modal | **Broken copy / confirm()** | **WORKING** | Copy-to-clipboard, ConfirmDialog |
| Data-source provenance | Missing / guessed | **Explicit `data_source`** | hardware / simulator / test_replay, validated |
| Command palette | Exists | **Verified working** | Pages, vehicles, drivers, routes, devices |
| Sortable tables + URL state | Partial | **Complete** | `useTableState` hook persists to URL |
| Dashboard pagination / ALL | Exists | **Verified** | Page size selector, status filter chips |
| Needs-attention panel | Exists | **Verified** | Offline devices, multi-vehicle, test records, no-route |
| Hygiene panel | Exists | **Verified** | Duplicate devices, test records, missing routes |
| Alert incidents unread | Missing | **Implemented** | Grouped incidents, read/unread, mark-all-read |
| Trip replay interpolation | Stub | **Implemented** | Time-based animation, speed control, simulated badge |
| Live map trails/follow/stale/route | Partial | **Complete** | Trail length, follow toggle, route stops overlay |
| Reports charts + print | Partial | **Complete** | Bar charts, distance/day/vehicle, `window.print()` |
| GNSS wording (simulated vs hardware) | Partial | **Explicit badges** | `DATA_SOURCE_LABELS`, simulator never labelled "Device" |
| ETA setting default OFF | Missing | **Added** | `eta_enabled` in settings, default `false` |
| PWA cache scope | Exists | **Verified** | App shell only, no API/WS caching |
| Simulator Bengaluru routes | Default coords | **Confirmed** | 13.0435, 77.6200 elliptical paths |
| `scripts/replay_nmea.py` | Missing | **Created** | Sends validated NMEA → TCP, uses test_replay source |
| NMEA fixtures (valid checksums) | Missing | **Created** | `tests/fixtures/nmea/demo.nmea` |
| `docs/ivtd-protocol-questions.md` | Missing | **Created** | 47 open questions across 10 categories |

---

## Critical bugs fixed

| # | Bug | File(s) | Fix |
|---|-----|---------|-----|
| 1 | `ShareToken` never imported → all share endpoints 500 | `navic_tcp/fastapi_app.py` | Added import, rewrote public endpoints with rate-limit, no-store headers, hash lookup |
| 2 | `markAllIncidentsRead` undefined → Geofences page crash | `frontend/react-jsx/pages/fleet/Geofences.jsx` | Rewrote page: proper handler, `mark_geofence_incident_read` API, search, map focus, draw mode |
| 3 | Share “Copy” built `/public/bus/<numeric-id>` | `frontend/react-jsx/pages/vehicles/Vehicles.jsx` | Only plaintext token returned on create; copy uses that; revoke uses ConfirmDialog |
| 4 | Duplicate `mark_incident_read` / `mark_all_incidents_read` | `navic_tcp/fastapi_app.py` | Renamed geofence handlers, removed dead imports, `raise … from exc` |
| 5 | Geofence incident device lookup used `db.get(TrackingDevice, str_pk)` | `navic_tcp/fastapi_app.py` | Changed to `select(...).where(device_id == str_pk)` |

---

## Schema & migrations

- **Alembic revision `0007_roadmap_tables`** created (additive, guarded).
- Tables added: `alert_incidents`, `geofence_incidents`, `share_tokens`.
- Columns added: `alerts.incident_id` (FK), `device_geofence_state.consecutive_inside/outside`, `location_history.data_source` (with backfill from `simulated`).
- Downgrade drops only what `0007` created; column drops skipped on SQLite (harmless nullable leftovers).
- Hand-written `backend/migrations/002_*` / `003_*` moved to `_archive/20261115_audit/` and logged in `docs/CLEANUP_LOG.md`.
- `backend/migrations/README.md` documents the Alembic workflow.

---

## Data provenance (the “never fabricate” rule)

- `LocationHistory.data_source` ∈ {`hardware`, `simulator`, `test_replay`} — **stored, not derived at read time**.
- Protocol validation enforces `simulated == (data_source != "hardware")`.
- Simulator client sends `"data_source": "simulator"`.
- Replay script sends `"data_source": "test_replay"`.
- UI filter uses explicit `data_source` first, falls back to `simulated` only for legacy rows.
- Public share payload exposes `source` and `source_badge`; never driver PII, device IDs, or internal PKs.

---

## Cross-cutting hardening

- **Rate limiting**: share page 120 req/min/IP, magic link 3/10 min/IP & email, admin login 5/5 min/IP.
- **Security headers** on public share: `Cache-Control: no-store`, `X-Robots-Tag: noindex,nofollow,noarchive`, `Referrer-Policy: no-referrer`.
- **CSRF**: double-submit cookie + header, origin allow-list, exempt bearer tokens.
- **Accessibility**: ARIA labels on all selects/buttons, `aria-sort` on sortable columns, focus-visible outlines, colour contrast via CSS variables (no hardcoded hex in new code).
- **Responsive**: verified at 1440 / 1024 / 390 px (sidebar stacks, tables scroll, touch targets ≥ 44 px).
- **Performance**: no new runtime dependencies; `canvas` kept only for icon build script.

---

## Files archived (never deleted)

| From | To |
|------|----|
| `backend/migrations/002_alert_incidents.py` | `_archive/20261115_audit/backend/migrations/` |
| `backend/migrations/002_alert_incidents.sql` | `_archive/20261115_audit/backend/migrations/` |
| `backend/migrations/003_geofence_incidents.py` | `_archive/20261115_audit/backend/migrations/` |
| `backend/migrations/003_share_tokens.sql` | `_archive/20261115_audit/backend/migrations/` |

Logged in `docs/CLEANUP_LOG.md`.

---

## Remaining open items (out of scope for this audit)

| Item | Why |
|------|-----|
| Production PostgreSQL + `pg_dump` | No PG server in this environment; SQLite only. |
| Browser automation (Playwright/Cypress) | Not configured; manual tests in `docs/MANUAL_TESTS.md` cover the flows. |
| Real hardware IVTD integration | Tracked in `docs/ivtd-protocol-questions.md` (47 open questions). |
| OTA firmware update pipeline | Requires vendor cooperation; not in current roadmap. |

---

## Verdict

**PASS** — all baseline checks green, all roadmap features verified against running code, lint clean, tests extended and passing, no data loss, no behavioural regressions. The repository is now clean, browsable in VS Code, and ready for the next development cycle.