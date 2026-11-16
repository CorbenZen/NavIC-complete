# Authentication guide

## Website sign-in

Authentication routes are assembled by `backend/python_fastapi/application/api/routes/auth.py` and
controllers/services in `backend/python_fastapi/application/controllers/auth_controller.py`,
`backend/python_services/auth_service.py`, and the shared `navic_tcp/auth.py`.
The React login and registration pages are in `frontend/react-jsx/pages/authentication/`;
the reusable forms are `frontend/react-jsx/components/forms/SignInForm.jsx` and
`SignUpForm.jsx`, and the central client is `frontend/javascript-services/api.js`.

The primary flow for students and teachers is a unique **User ID plus password**.
No email address, SMTP configuration or verification link participates in
normal registration or sign-in:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register` | create a student/teacher account |
| POST | `/api/auth/login` | sign in with User ID (or admin email) and password |
| POST | `/api/auth/logout` | revoke the session and clear cookies |
| GET | `/api/auth/me` | return the authenticated principal |
| POST | `/auth/register`, `POST /auth/login/id` | prefix-free aliases used by the SPA |

Passwords use salted scrypt (`navic_tcp.security.hash_password` /
`verify_password`); only the hash is stored and it is never returned by the API.
Accounts are immediately usable after registration. Successful login creates a
database-backed `navic_session` cookie plus the readable `navic_csrf` cookie;
unsafe cookie-authenticated requests must echo the CSRF value in
`X-CSRF-Token`. Bearer tokens are still issued for API clients. Login and
registration are rate limited per client.

Sign-in error contract:

- empty ID or password → the form shows `Please enter your ID and password.`
- unknown User ID → `404 {"detail": "No account found with this ID."}`
- wrong password → `401 {"detail": "Incorrect password. Please try again."}`
- repeated failures → `429` with a `Retry-After` header.

## Student and teacher registration

The React registration screen is `frontend/react-jsx/pages/authentication/SignUp.jsx`;
its service calls `POST /api/auth/register`. Requests require `first_name`,
`last_name`, `account_type` (`student` or `teacher`), `user_id`, `password` and
`confirm_password`. Student registrations also require `usn_id`; teacher
registrations must omit it.

- User IDs are 3–32 characters, start with a letter or digit, and may contain
  letters, digits, dots, underscores or hyphens. They are normalised to upper
  case, so `navic001` and `NAVIC001` are the same account.
- Passwords are 8–128 characters, must contain at least one letter, must match
  `confirm_password`, and may not equal the User ID.
- `USN_REGEX` configures the institution's USN policy (default: a broad
  3–32 character alphanumeric/dash/slash pattern).
- A duplicate User ID returns `409 {"detail": "This ID is already registered. Please choose another ID."}`.
  A duplicate student USN returns `409 {"detail": "This student USN is already registered."}`.
- Unique indexes on `lower(trim(user_id))` and the student partial
  `lower(trim(usn))` close the race between the pre-flight check and a
  concurrent submission.
- Both account types receive the least-privileged `viewer` application role;
  `account_type` is stored separately for institutional rules.
- New accounts are marked email-verified internally so the legacy
  verification gate cannot block them; `email` is `NULL`.

## Administrator sign-in

The configured administrator continues to authenticate with `ADMIN_EMAIL` and
`ADMIN_PASSWORD_HASH`. On the normal sign-in form, enter the administrator email
address in the User ID field. `POST /api/auth/login` detects the configured
address, verifies the password hash, promotes the account to `admin` and issues
the usual session. The dedicated `POST /auth/admin-login` endpoint remains
available. New or existing User ID accounts cannot gain administrator rights
through this form; the admin role is only granted by the configured credential
check.

## Legacy email verification and magic links

The earlier email-based registration contract, one-time verification links and
the passwordless magic-link flow remain available for existing accounts and are
not used by the new User ID forms. `POST /api/auth/verify-email`,
`/api/auth/resend-verification`, `/api/auth/verification-status`, and the
`/auth/verify-email` aliases are retained. Verification tokens are stored only
as SHA-256 hashes, are single-use and expire. `POST /api/auth/login` is now the
User ID endpoint; the legacy email-password contract is served by
`POST /auth/login` for API clients.

Accounts created by earlier magic-link or Google flows may have an empty
`password_hash`. Password login reports that such an account has no password
and points to the existing email-link or Google path; it does not invent a
password or silently change the account. Configure SMTP to receive those links
in an inbox. With `EMAIL_PROVIDER=console` in development, the links are stored
only in the configured local capture file and no external email is delivered.

The frontend handles `/auth/verify-email?token=…` and calls
`POST /auth/verify-email`; the token is removed from the address bar before the
request. The API also provides `POST /auth/resend-verification` and
`GET /auth/verification-status`. Passwordless accounts can still use the
existing magic-link flow. Google sign-in marks an account verified only after
the Google ID token is validated and its `email_verified` claim is true.

Set `EMAIL_VERIFICATION_EXPIRE_MINUTES` to a value from 5 to 1440 (default 30).
For local development, the existing console mail provider records messages in
the ignored `dev-mail.jsonl` capture file. For real delivery, select the SMTP
provider and configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
`SMTP_PASSWORD`, `SMTP_FROM_EMAIL` (or legacy `EMAIL_FROM`) and `SMTP_USE_TLS`.
Production verification links require an HTTPS `FRONTEND_URL`. Delivery errors
return a server error; they are not reported as successful sends, and the
pending token is invalidated.

## Google OAuth

`backend/python_authlib/google_oauth/google_oauth.py` uses Authlib/HTTPX and Google token
verification. Configure the OAuth client ID and secret and an allowed callback
URL in `.env`; leave the feature disabled when credentials are unavailable.
OAuth state is stored and validated to prevent request forgery.

## Local email

SMTP settings are optional. In development, the mailer can record generated
links in the ignored `dev-mail.jsonl` capture file. Never commit `.env` or the
mail capture file; they may contain secrets or active sign-in links.

See `backend/.env.example` for the mail and verification settings and
`docs/DEVELOPMENT_GUIDE.md` for local startup.
