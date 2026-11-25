# Deploying NavIC to Render

NavIC deploys as **one Docker web service** (FastAPI serves the API, the
WebSocket and the built React app from the same URL) plus **one managed
PostgreSQL database**. Both are defined in [`render.yaml`](../render.yaml).

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the frontend (Node 26), then runs the backend (Python 3.13) |
| `.dockerignore` | Keeps `.env`, SQLite files, venvs and caches out of the image |
| `render.yaml` | Render Blueprint: web service, database and environment variables |
| `scripts/render_start.sh` | Runs migrations → optional demo seed → starts Uvicorn on `$PORT` |
| `backend/requirements.txt` | Now includes `psycopg[binary]`, the PostgreSQL driver |

> Telemetry on the hosted site is **simulated**. Render exposes HTTP(S) only, so
> the TCP receiver (port 5000) is disabled (`TCP_ENABLED=false`) and the in-app
> demo simulation is enabled instead (`DEMO_SIMULATION_ENABLED=true`).

---

## Before you start: three things to prepare

### 1. An email provider (required)
Production startup refuses `EMAIL_PROVIDER=console`. The Blueprint defaults to
**Resend**: create an account at resend.com, create an API key, and verify a
sender domain (or use Resend's test sender while testing; see Resend's docs
for its limits). You will enter:
- `EMAIL_API_KEY`: the Resend API key
- `EMAIL_FROM`: the sender address, e.g. `NavIC <noreply@your-domain>`

To use SMTP instead, change `EMAIL_PROVIDER` to `smtp` in the dashboard and set
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`.

### 2. An administrator password hash (required)
Never store the plain password. Generate a scrypt hash locally. The password is
typed at a hidden prompt and never written to disk:

```bash
.venv-local/bin/python -c "from getpass import getpass; from navic_tcp.security import hash_password; print(hash_password(getpass('Admin password: ')))"
```

Copy the printed value (it starts with `scrypt$`) into `ADMIN_PASSWORD_HASH`.
Set `ADMIN_EMAIL` to the email you will sign in with.

### 3. The code on GitHub
Render deploys from a Git repository. Push this project to your GitHub repo
yourself, including these new or changed files:
`Dockerfile`, `.dockerignore`, `render.yaml`, `scripts/render_start.sh`,
`VERSION`, `backend/requirements.txt`, `.gitignore`.

Make sure **`.env` and `*.db` are not committed** (both are in `.gitignore`).

---

## Deploy

1. In the Render dashboard choose **New → Blueprint** and connect your GitHub repo.
2. Render reads `render.yaml` and shows the `navic` web service and the
   `navic-db` database. `DATABASE_URL`, `JWT_SECRET` and `AUTH_IP_SALT` are
   filled in automatically.
3. Fill in the prompted values:

   | Variable | Value |
   |---|---|
   | `FRONTEND_URL` | `https://navic.onrender.com` (your service URL) |
   | `BACKEND_URL` | same URL |
   | `CORS_ORIGINS` | same URL (no trailing slash, no path) |
   | `ADMIN_EMAIL` | your admin email |
   | `ADMIN_PASSWORD_HASH` | the `scrypt$...` value from step 2 |
   | `EMAIL_API_KEY` | your Resend key |
   | `EMAIL_FROM` | your sender address |

   The URL is `https://<service-name>.onrender.com`. If `navic` is already
   taken, Render adds a suffix; after the first deploy, copy the real URL from
   the dashboard into the three URL variables and redeploy.
4. Click **Apply**. The first build takes several minutes.
5. Watch **Logs**. A healthy start looks like:
   ```
   Applying database migrations...
   Running upgrade  -> 0001_baseline ... -> 0008_user_second_name
   Seeding demo fleet (idempotent)...
   Starting NavIC API on port ...
   Application startup complete.
   ```
6. Open `https://<your-url>/health`. Expect `"status":"ok","database":"ok"`.
   Then open the site and sign in with your admin email and password.

After the demo fleet exists you may set `SEED_DEMO_DATA=false`. Leaving it on
is safe: the seed only creates or updates the demo records and never deletes data.

---

## Troubleshooting

| Symptom in logs | Fix |
|---|---|
| `Invalid production configuration: ...` | The message lists each missing or invalid variable; set them in **Environment** |
| `FRONTEND_URL must use HTTPS` | Use the full `https://` Render URL |
| `ADMIN_PASSWORD_HASH must be a scrypt password hash` | Regenerate with the command above; paste the whole value |
| Sign-in works but you're logged out instantly | `FRONTEND_URL`/`BACKEND_URL`/`CORS_ORIGINS` don't match the URL in the browser |
| Site takes ~1 minute to load | Free services sleep when idle and wake on the next request |

## Free-tier notes

Check Render's current pricing page. On the free plan the web service sleeps
after inactivity, and free PostgreSQL databases have historically had a limited
lifetime, so upgrade the database (or export it) before relying on it for real
records.

## Verified locally (2026-11-25)

The image was built with Podman and run in production mode against a fresh
`postgres:17` container: all 8 migrations applied, the seed created 6 demo
buses, a restart re-applied nothing and duplicated nothing, `/health` and
`/api/meta` returned 200, protected API routes returned 401 without a session,
and the sign-in page rendered in a browser. Not tested: a real Render deploy,
email delivery, and the service worker over HTTPS.
