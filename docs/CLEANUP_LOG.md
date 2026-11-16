# Cleanup log

Every file below was **moved**, never deleted. Relative paths are preserved under
`_archive/<timestamp>/` so a file can be restored by moving it back.

## 2026-11-15 — audit pass (`_archive/20261115_audit/`)

| Moved from | Moved to | Why |
| --- | --- | --- |
| `backend/migrations/002_alert_incidents.py` | `_archive/20261115_audit/backend/migrations/002_alert_incidents.py` | Hand-written, unversioned migration. Superseded by Alembic `0007_roadmap_tables`. Not referenced anywhere. |
| `backend/migrations/002_alert_incidents.sql` | `_archive/20261115_audit/backend/migrations/002_alert_incidents.sql` | Same change as above, SQL variant; never invoked by the application. |
| `backend/migrations/003_geofence_incidents.py` | `_archive/20261115_audit/backend/migrations/003_geofence_incidents.py` | Superseded by Alembic `0007_roadmap_tables`; had 12 ruff errors (unused imports, unsorted imports) and duplicate numbering with `003_share_tokens.sql`. |
| `backend/migrations/003_share_tokens.sql` | `_archive/20261115_audit/backend/migrations/003_share_tokens.sql` | Superseded by Alembic `0007_roadmap_tables`. |

`backend/migrations/README.md` now explains the Alembic workflow and points at
the archive.

## 2026-11-15 — sidebar menu repair (`_archive/20261115T132602Z/`)

| Moved from | Moved to | Why |
| --- | --- | --- |
| inactive `.sidebar.is-rail .sidebar-brand-row::after`, `.sidebar-collapse.sidebar-expand`, nav item tooltip, and sidebar search tooltip rules | `_archive/20261115T132602Z/frontend/css-styles/global/rail-artifacts.css` | The pseudo-element painted the empty rounded square under the rail handle; the legacy collapse selector has no matching element in the current sidebar; CSS-only tooltip duplicates were replaced by the shared portal popover. Kept the removed rules for restoration and evidence. |
