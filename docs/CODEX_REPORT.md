# Codex report — work in progress

Date: 2026-11-15. Earlier project claims are not used as evidence. No Git commands were used after the owner instructed that Git is out of scope.

## Scoreboard

| Area | Status | Evidence |
| --- | --- | --- |
| Phase 0 snapshot and orientation | Partly | Snapshot and structure map recorded in `docs/CODEX_PROGRESS.md`; `pg_dump` unavailable, configured store is SQLite. |
| Frontend build | Partly | `npm run build` succeeded; combined lint/build gate fails. |
| Frontend route rendering in browser | Missing | Smoke test NOT TESTED; Vite could not be started on the expected port. |
| Backend compile | Works | `python -m compileall -q backend navic_tcp tests` passed. |
| Backend tests | Broken / NOT TESTED | Default discovery found backup duplicates; scoped run stalled after 13 tests / at test 14. |
| Python lint | Partly | Whole-repository Ruff reported 91 issues; replay helper now passes its scoped Ruff check. |
| Migrations | Partly | Scratch upgrade through 0007 passed. Downgrade exposed an index ordering failure at 0004. Current DB migration not attempted because that DB is readonly here. |
| Historical crash pages, source provenance, incidents, geofences, share security, ETA, PWA, API security/performance | NOT TESTED | Requires the planned browser, API, and focused tests, which were not completed. |
| Documentation and editor setup | Partly | Added project instructions, architecture map, progress, decisions, verification evidence, and this report. Remaining requested docs/configuration are not complete. |

## Bugs and findings

- Fixed eight Ruff findings in `scripts/replay_nmea.py`; scoped Ruff check passes.
- Found current frontend lint failures and a SQLite migration downgrade ordering defect. They remain open.
- Configured DB startup attempts a provenance backfill and failed read-only. No permissions or data were changed.

## Structure and cleanup

The initial structure map is in `docs/ARCHITECTURE.md`. No source files were moved or deleted; no archive cleanup was performed.

## Verification summary

- Frontend build: PASS.
- Frontend lint: FAIL, 38 errors and 44 warnings.
- Backend compile: PASS.
- Backend tests: NOT TESTED to completion (stalled; see `docs/VERIFICATION.md`).
- Scratch migration upgrade: PASS; downgrade: FAIL at revision 0004.
- Browser smoke table: NOT TESTED; no PASS/FAIL route matrix exists.
- Current DB migration and fresh clone-like walkthrough: NOT TESTED.

## Security and environment

No secret values were written to docs or intentionally printed. A configured `.env` file exists locally and is excluded from neither the project snapshot nor the ordinary repository; review of secret exposure was NOT TESTED. `pg_dump` is unavailable. No database contents were changed by this session.

## Backup and rollback

Snapshot: `backups/pre_codex_20261115_170000/project.tar`. Restore source/config files from that archive as needed. It excludes dependency directories, build output, prior backups, `_archive/`, and `.git`. The live configured SQLite database was not changed; no SQL dump exists.

## Hardware follow-up

Real IVTD hardware and its protocol remain unavailable. Validate physical device framing, authentication, timestamps, GNSS fields, source labeling, and observed constellations when hardware is provided. Do not infer device behavior before that review.

## Remaining work

Phases 1–5 are incomplete. See `docs/CODEX_PROGRESS.md` and `docs/VERIFICATION.md` for blockers and raw command evidence. No route behavior or feature status is claimed as verified.
