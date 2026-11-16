# Database Guide

NavIC uses **SQLAlchemy 2** with a single declarative schema shared by the TCP
telemetry application and the website backend. The schema is defined once in
`navic_tcp/models.py`; `backend/python_sqlalchemy/models/` re-exports the model classes by
domain.

## 1. Engine and session management

`navic_tcp/db.py` creates the engine from `DATABASE_URL`, defaulting to a
persistent SQLite file in the user's local application data directory:

```python
DATABASE_URL = os.getenv("DATABASE_URL", default_database_url()).strip()

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```

- SQLite connections run `PRAGMA foreign_keys=ON` through a `connect` event
  listener, so `ON DELETE` rules are enforced in development too.
- `pool_pre_ping=True` checks connections before use.
- `expire_on_commit=False` keeps returned objects usable after a commit.

The backend exposes the same objects through `backend/python_sqlalchemy/database/`:

| Module | Contents |
| --- | --- |
| `base.py` | `Base` |
| `connection.py` | `engine`, `DATABASE_URL`, `init_database()`, `database_reachable()`, `ensure_schema()`, `ensure_gnss_schema()`, `ensure_bus_route_schema()` |
| `session.py` | `SessionLocal`, `get_db()` dependency, `session_scope()` context manager |

Two session patterns are used:

```python
# FastAPI dependency: always closes the session
from backend.python_fastapi.application.core.dependencies import get_db

def handler(db=Depends(get_db)):
    ...

# Service/tooling: commit on success, rollback on error
from backend.python_sqlalchemy.database import session_scope

with session_scope() as db:
    db.add(record)
```

`fleet_service`, `alert_service` and `telemetry_service` accept a `Session` and
perform explicit `commit()`/`rollback()` with a `refresh()` after writes.

## 2. Database location and configuration

| Environment | `DATABASE_URL` |
| --- | --- |
| Default SQLite | `~/.local/share/navic/navic.sqlite3` |
| Custom data directory | `NAVIC_DATA_DIR=/path/to/navic-data` |
| Custom SQLite file | `DATABASE_URL=sqlite:////absolute/path/navic.sqlite3` |

First startup copies the old root `navic_dev.db` to this location when the
destination does not exist. The source remains untouched. The URL is read once
when `navic_tcp.db` is imported; restart after changing it. SQLAlchemy models
and migrations keep database access centralized for future database options.

## 3. Schema

19 tables are defined. Relationships:

```text
Driver 1 --- * Bus * --- 1 Route
                 |
                 * TrackingDevice 1 --- * LocationHistory
                                  1 --- * Alert
                                  1 --- * DeviceGeofenceState * --- 1 Geofence

User 1 --- * SafetyAlert (user_id, acknowledged_by, resolved_by)
User 1 --- * Feedback
User 1 --- * SupportTicket
User 1 --- * StudentBusPass * --- 1 Bus
User 1 --- 1 UserPreferences
User 1 --- * MagicLinkToken
User 1 --- * AuthSession
GoogleOAuthTransaction      (standalone, one row per in-flight login)
SystemSetting               (key/value)
AuditLog                    (append-only)
```

### Fleet

| Table | Key columns | Notes |
| --- | --- | --- |
| `buses` | `vehicle_id` (unique), `registration_number` (unique), `driver_id`, `route_id` | `driver_name`/`route_name` keep legacy display values; FKs use `SET NULL` |
| `drivers` | `email` (unique), `license_number` (unique), `active` | one driver can be assigned to many buses |
| `routes` | `name` (unique), `identifier` (unique), `stops` JSON, `color` | `stops` is an ordered list of `{name, latitude, longitude}` |
| `geofences` | `name` (unique), `latitude`, `longitude`, `radius_m`, `active` | circular geofences |
| `tracking_devices` | `device_id` (unique), `bus_id`, `device_type`, `identifier_type`, `simulated`, `active` | `bus_id` uses `SET NULL` |

### Telemetry

| Table | Key columns | Notes |
| --- | --- | --- |
| `location_history` | `device_id`, `message_id` (unique), `timestamp`, lat/lon/speed/course, `simulated`, `ignition`, `odometer`, GNSS columns | one row per accepted telemetry frame; index `ix_location_device_time` on `(device_id, timestamp)` |
| `device_geofence_state` | composite PK `(device_id, geofence_id)`, `inside` | last known inside/outside state per device and geofence |

GNSS columns include `altitude_m`, `fix_valid`, `satellites_in_view`,
`satellites_used`, `pdop`, `hdop`, `vdop` and `gnss_metadata` (JSON).

### Alerts

| Table | Key columns | Notes |
| --- | --- | --- |
| `alerts` | `event_type`, `message`, `device_id`, `created_at`, `is_read` | system/offline/geofence alerts; `device_id` uses `SET NULL` |
| `safety_alerts` | `user_id`, `bus_id`, `reason`, `status`, `latitude`, `longitude`, `location_source`, `idempotency_key` (unique), acknowledgement/resolution columns | SOS reports; indexes on `(bus_id, status)` and `(status, created_at)` |

### Identity and student services

| Table | Key columns | Notes |
| --- | --- | --- |
| `users` | `username` (unique), `user_id` (unique), `email` (nullable unique), `google_sub` (unique index), `role`, `password_hash`, `active` | `user_id` is the primary login identifier; `email` may be null for User ID accounts; `password_hash` may be empty for OAuth/magic-link-only users |

New registration attributes are `first_name`, `last_name`, `account_type`, and
`updated_at`. `user_id` is the unique, normalised login identifier for student
and teacher accounts (`lower(trim(user_id))` index). `email` is nullable and
used only by the administrator, Google and legacy magic-link accounts. Legacy
records retain a null account type; migration does not guess whether they are
students or teachers. Email uniqueness is still enforced on
`lower(trim(email))`; student USNs use a partial unique index on
`lower(trim(usn))`. SQLite triggers and PostgreSQL check constraints enforce
student/teacher USN rules.
| `auth_sessions` | `token_hash` (unique), `csrf_hash`, `expires_at`, `revoked_at`, `ip_hash`, `user_agent` | only hashes are stored |
| `magic_link_tokens` | `token_hash` (unique), `expires_at`, `used_at`, `requested_ip_hash` | single use |
| `google_oauth_transactions` | `state_hash` (unique), `nonce`, `code_verifier`, `expires_at`, `used_at` | one-time OAuth handshake |
| `user_preferences` | `user_id` PK/FK, `values` JSON | cascade delete |
| `student_bus_passes` | `pass_token` (unique), `user_id`, `bus_id`, `status`, `expires_at` | QR-verifiable pass |
| `feedback` | `user_id`, `rating`, `category`, `comments`, `status` | |
| `support_tickets` | `ticket_number` (unique), `user_id`, `subject`, `priority`, `status` | |
| `system_settings` | `key` PK, `value` | key/value configuration edited from Settings |
| `audit_logs` | `actor`, `actor_role`, `action`, `entity`, `entity_id`, `detail` | append-only management trail |

## 4. Schema initialisation and migrations

Startup retains the existing additive schema management for legacy NavIC
databases, and the backend also includes Alembic revisions for the auth changes.
`0002_email_verification` adds the verification state; it backfills
`is_email_verified` only for rows that already have a non-null legacy
`email_verified_at`, and the raw verification token is never stored, only its
hash. `0003_student_teacher_registration` adds the student/teacher attributes
and uniqueness rules. `0004_user_id_password_auth` adds the nullable `user_id`
column, backfills existing rows with a deterministic `USER<id>` identifier,
makes `email` nullable (batched table rebuild on SQLite), and creates the
normalized `user_id` and email indexes plus the student-USN triggers. Existing
rows and emails are preserved.

On startup the FastAPI lifespan calls `ensure_schema(engine)`.
`navic_tcp/schema.py` then:

1. creates missing tables from `Base.metadata` (`create_all`);
2. adds missing nullable columns to existing development databases;
3. backfills safe defaults and creates required indexes.

Nothing is dropped, truncated or rewritten. This preserves the existing
database and its data on both SQLite and PostgreSQL.

Apply the schema manually (for example after pulling new models):

```bash
.venv-local/bin/python -c "from backend.python_sqlalchemy.database import init_database; init_database()"
```

`backend/python_sqlalchemy/migrations/README.md` documents the policy and
Alembic commands. Back up databases before schema changes; migration revisions
must remain additive unless a deliberate data-preserving conversion is defined.

## 5. Seeding demo data

```bash
.venv-local/bin/python -m backend.python_sqlalchemy.database.seed
```

`backend/python_sqlalchemy/database/seed.py` is idempotent:

- creates/updates six demo buses, their tracking devices, six drivers, two
  routes and one geofence;
- never deletes records and never resets a database;
- never creates user accounts or credentials.

The seeded coordinates are illustrative campus-area points, not a surveyed road
route. The simulator always marks frames `simulated=true`.

## 6. CRUD and transactions

The transactional service layer is `backend/python_services/fleet_service.py`:

```python
from backend.python_sqlalchemy.database import SessionLocal
from backend.python_sqlalchemy.models import Bus
from backend.python_services import fleet_service

with SessionLocal() as db:
    bus = fleet_service.create_record(
        db, Bus, vehicle_id="BUS-01", registration_number="KA01AB1234"
    )
    fleet_service.update_record(db, Bus, bus.id, driver_name="A. Driver")
    counts = fleet_service.fleet_counts(db)
    fleet_service.delete_record(db, Bus, bus.id)
```

All write helpers commit on success, roll back on failure and re-raise the
original exception. Duplicate unique keys therefore raise `IntegrityError`
without leaving the session in a broken transaction (covered by
`test_duplicate_vehicle_rolls_back_without_corrupting_session`).

Telemetry writes go through `navic_tcp.fastapi_app.on_telemetry`:

- validates the frame with `decode_telemetry` before this point;
- ignores duplicate `message_id` values;
- inserts one `location_history` row;
- evaluates geofences and writes `alerts` when state changes;
- updates `device_geofence_state`;
- publishes live events to the WebSocket hub.

## 7. Backup and preservation

- `backup/architecture-20261113-060719-fullstack/` contains the pre-change copy
  of `backend/`, `frontend/react-jsx`, docs, VS Code configuration and `navic_dev.db`.
- Backups are timestamped and never overwritten.
- The existing root SQLite database is used in place; the architecture pass did
  not recreate or delete it.
- Additive startup migrations only add missing structures.

## 8. Testing the database layer

```bash
.venv-local/bin/python -m unittest backend.tests.test_backend_app -v
.venv-local/bin/python -m unittest backend.tests.test_schema_migration -v
```

Tests that need isolation create an in-memory SQLite engine with `StaticPool`,
call `Base.metadata.create_all()` and pass the resulting session to the service
functions, so the development database is never modified.
