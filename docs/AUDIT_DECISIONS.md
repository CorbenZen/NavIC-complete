# Audit decisions

Safest-option decisions taken during the audit. Each entry records what was
chosen and why.

1. **Do not touch `.git`.** The task forbids git commands, so safety relies on the
   rsync backup in `backups/pre_audit_20261115_150308/` plus the SQLite copy
   `backups/pre_audit_20261115_150308.sqlite`.
2. **Do not run destructive migrations on the live DB during investigation.**
   Alembic upgrades were tested against `/tmp/opencode/audit_copy.db` first.
   The live DB is only advanced after the whole schema change set is proven.
3. **Preserve the historical audit.** `docs/AUDIT.md` keeps the 2026-11-06 audit
   below the new section instead of overwriting it.
4. **Never invent a `data_source` value.** When a fix needs the
   hardware/simulator/test_replay distinction, it is derived from the existing
   `simulated` flag plus an explicit stored `data_source` column, never guessed
   from device names.
5. **Public share page keeps the numeric bus id out of the response.** The
   public payload exposes registration, route, position and freshness only.
   `vehicle_id` is kept because it is the human-facing fleet label already shown
   on the public page; device ids/IMEI and driver contact data are never exposed.
6. **No new runtime dependency.** Fixes use the standard library / existing
   packages only. `canvas` is only needed by the icon generator and will be
   marked as such (kept, because deleting it would break `npm run icons`).
7. **Dead files are archived, never deleted.** Moves go to
   `_archive/20261115_audit/` with their relative path preserved and are listed
   in `docs/CLEANUP_LOG.md`.
8. **Visible behaviour is preserved unless it is a bug.** Where the roadmap
   promised a feature that does not exist, the feature is implemented behind the
   existing UI rather than inventing a new design.
