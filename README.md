# Outreach

A small web app for sending LinkedIn connection requests from a list, on a drip
schedule, with a dashboard of how many went out per day, week and month.

It is the Colab notebook turned into something a team can share: the same
Voyager calls, but with a queue, per-account daily and weekly caps, a send
window, encrypted tokens, and a history you can look at.

- **Backend** — FastAPI + SQLAlchemy + Postgres, with the drip worker running in
  a thread inside the same process.
- **Frontend** — React (Vite), built and served by the same container.
- **Sources** — CSV upload or a Google Sheet, with results written back into the
  sheet.

---

## How it works

```
CSV / Google Sheet
      │  column mapping (vmid, name, company, title, note)
      ▼
   campaign ──────────► invitations queue (one row per profile)
                              │
                              │  the worker wakes up every 15s and, for each
                              │  LinkedIn account, sends AT MOST one request,
                              │  then waits a random 90–300s
                              ▼
                     LinkedIn Voyager API
                              │
                              ├──► row marked sent / failed / skipped
                              └──► result written back into the Google Sheet
```

An account only sends when **all** of these are true: it is active, the local
time is inside its window, it is a weekday (if weekends are off), it is under
its daily cap, it is under its weekly cap, and its random gap since the last
request has elapsed.

When LinkedIn answers with something that matters, the worker reacts instead of
hammering:

| LinkedIn says | What happens |
|---|---|
| 401 / 403 / 999 | Account marked **needs new tokens**, everything stays queued |
| 429 | Account **cools down** 20 minutes, the row stays queued |
| weekly invite limit reached | Account **stops until tomorrow**, the row stays queued |
| already invited / already connected | Row marked **skipped**, no retry |
| 5xx or a network error | Retried on a later tick, up to 5 attempts |

---

## Deploy on Railway

1. **Push this folder to a GitHub repo.**

2. **New Project → Deploy from GitHub repo.** Railway detects the `Dockerfile`
   on its own and builds the React app and the Python API into one image. There
   are no build settings to fill in.

   Note: Railway deprecated Config-as-Code, and services created after
   2026-08-28 that never used it cannot opt in — so a `railway.json` in the repo
   is ignored. The start command comes from the `Dockerfile`'s `CMD`; the
   healthcheck and restart policy have to be set in the UI (steps 5 and 6).

3. **Add Postgres first**: in the project, *New → Database → Add PostgreSQL*.
   Railway does **not** inject `DATABASE_URL` into the app service for you — on
   the app service add a variable `DATABASE_URL` with the value
   `${{Postgres.DATABASE_URL}}`.

   Do this before the app's first successful boot. That reference resolves by
   service name, so if you set it while no service named `Postgres` exists,
   Railway stores the literal text and the app dies on import with
   `sqlalchemy.exc.ArgumentError: Could not parse SQLAlchemy URL`.

4. **Set the variables** (*Variables* tab on the app service). See
   `.env.example` for the full list; the ones you cannot skip:

   ```
   APP_SECRET=<openssl rand -hex 32>
   ADMIN_EMAIL=julio@kalungi.com
   ADMIN_PASSWORD=<a strong one>
   ```

   `APP_SECRET` both signs the session cookies and derives the key that
   encrypts the LinkedIn tokens. **Set it once.** If you change it later,
   everyone is signed out and the stored LinkedIn tokens can no longer be
   decrypted — you would have to paste them again.

5. **Set the healthcheck** to `/api/health` in *Settings → Deploy → Healthcheck
   Path*. Without it Railway marks a deploy successful as soon as the image is
   built, so a container that crashes on boot still shows green.

6. **Generate a domain** (*Settings → Networking → Generate Domain*) and give it
   target port **8080** — that is the `PORT` Railway injects at runtime, which
   is what the `Dockerfile`'s `CMD` binds to. Then open it and sign in with
   `ADMIN_EMAIL` / `ADMIN_PASSWORD`. The admin user is created on the first boot
   only; after that, change the password from the app and drop
   `ADMIN_PASSWORD` from the variables.

Logs from the worker are prefixed `worker`.

### When you change a variable

Railway resolves variables when it creates a deployment. *Restart* and
*Redeploy* both reuse the previous deployment's resolved values, so neither
picks up a new variable or a reference that only just became resolvable. Edit
the variable and use the **Deploy** button that appears (*Apply N changes*),
which builds a genuinely new deployment.

### Keep it to one replica

The worker holds a Postgres advisory lock so a second replica will not send
duplicates — but it will also just sit idle, so there is nothing to gain from
scaling up. If you ever want the worker separate from the web service:

- Web service: `RUN_WORKER=false`
- Second service, same repo and image, start command `python -m app.worker`

---

## First steps in the app

1. **Team** → add your teammates. Members only see their own LinkedIn accounts
   and campaigns; admins see everyone's and can switch the dashboard between
   *Mine* and *Whole team*.

2. **LinkedIn accounts** → *Add account*. Paste the same token dictionary the
   notebook uses:

   ```
   {'li_at': 'AQED...', 'JSESSIONID': '"ajax:123..."', 'csrf-token': 'ajax:123...',
    'user-agent': 'Mozilla/5.0 ...'}
   ```

   The app checks the session against LinkedIn right away and tells you if it is
   already expired. Tokens are encrypted before they touch the database and are
   never sent back to the browser.

   To get them: sign in to LinkedIn in Chrome → DevTools → *Application →
   Cookies* for `li_at`, `JSESSIONID` and `li_a`; `csrf-token` is the
   `JSESSIONID` value without the quotes; `user-agent` is whatever
   `navigator.userAgent` prints in the console.

3. **Campaigns → New campaign** → upload a CSV or paste a Sheet URL, check the
   column mapping (it guesses from the headers), write the note if you want one,
   and queue it.

The note accepts `{first_name}`, `{full_name}`, `{company}` and `{title}`, and
is capped at LinkedIn's 300 characters. A per-row note column wins over the
template. Leave both empty to send without a note.

### What gets skipped before anything is sent

Rows are checked at import time, so you see the problems immediately instead of
one failure at a time: values that are not vmids (`ACoAA…`), duplicates inside
the file, profiles this account already has queued or already invited, and notes
over 300 characters. Everything else goes into the queue.

---

## Google Sheets (optional)

Set `GOOGLE_SERVICE_ACCOUNT_JSON` to the full service-account JSON (one line)
and the *Google Sheet* source appears in the campaign wizard. Share each sheet
as **Editor** with the service account email — the app shows you which one it is
right under the URL field.

Results are written back into the column you choose (`Result` by default),
created if it doesn't exist, in batches after each tick — the same text the
notebook wrote: `Connection request sent! (2026-09-15 14:03 UTC)`,
`Not sent (429) - RATE_LIMIT - …`.

The service-account key that was hardcoded in the notebook should be rotated
before this goes anywhere near a shared repo.

---

## Sending limits

Defaults per account: **20/day, 100/week, 09:00–18:00 local, weekdays only,
90–300s between requests.** The server refuses anything above
`MAX_DAILY_LIMIT` (80) and `MAX_WEEKLY_LIMIT` (200) whatever the UI asks for.

Those defaults are deliberately conservative. LinkedIn's Terms of Service do not
allow automated tools against their site, and the practical consequence of
pushing volume is a restricted account — usually starting with invitations
silently failing, then a temporary block. The per-account caps, the random gaps
and the work-hours window exist to keep the pattern boring; they are not a
guarantee. Keep an eye on the *Accepted by LinkedIn* number on the dashboard: if
it starts dropping, slow down rather than retrying.

---

## Local development

```bash
# backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
export DATABASE_URL="sqlite:///./local.db" APP_SECRET=dev COOKIE_SECURE=false \
       ADMIN_EMAIL=you@example.com ADMIN_PASSWORD=devpassword
uvicorn app.main:app --reload

# frontend (another terminal) — proxies /api to port 8000
cd frontend && npm install && npm run dev
```

Demo data to click around with, without touching LinkedIn:

```bash
cd backend && python -m scripts.seed_demo    # demo@kalungi.com / demo12345
```

SQLite works for local development; use Postgres in production (the worker's
`SKIP LOCKED` row grab and the advisory lock only apply there).

### Tests

```bash
.venv/bin/python -m pytest backend/tests -q
```

54 tests covering the LinkedIn client against a mocked transport (endpoint,
payload, cookie/header split, every error class), the CSV and Sheet importers,
the window and quota arithmetic, the worker's drip behaviour, and the API
including permissions.

---

## Layout

```
backend/
  app/
    main.py          FastAPI app, serves the SPA, boots the worker
    models.py        users, linkedin_accounts, campaigns, invitations
    linkedin.py      the Voyager client (the notebook's logic, classified)
    worker.py        the drip loop
    scheduling.py    send windows and quota arithmetic
    importers.py     CSV parsing, column mapping, note templating
    sheets.py        Google Sheets read/write
    security.py      password hashing, session tokens, token encryption
    routers/         auth, accounts, campaigns, stats
  scripts/seed_demo.py
  tests/
frontend/src/
  pages/             Dashboard, Campaigns, NewCampaign, CampaignDetail, Accounts, Team
  components/        Layout, BarChart, StatTile, Badge
```

## Changing the schema later

Tables are created with `Base.metadata.create_all` on boot, which creates
missing **tables** but not missing **columns**. If you add a field to a model,
add the column by hand (`ALTER TABLE …`) or bring in Alembic. Worth doing before
there is data you care about.
