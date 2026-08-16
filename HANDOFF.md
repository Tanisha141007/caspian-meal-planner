# Caspian meal planner — project handoff

Read this first if you're joining the project. It's kept up to date as a
substitute for chat history that doesn't travel between people/tools -
if something here is stale, fix it in the same PR that makes it stale.

## What this is

A meal-planning app for Indian households: plan a week/month of meals,
and the household's cook gets the day's dishes + ingredients + portions
sent automatically over Telegram (via the [Caspian
SDK](https://github.com/TryCaspian/caspian-sdk)). The cook can reply in
plain language ("no onion today") and it's parsed back into feedback.

## Repos (two, deliberately separate)

- **Backend** — [Tanisha141007/caspian-meal-planner](https://github.com/Tanisha141007/caspian-meal-planner)
  (this repo). FastAPI + SQLAlchemy/Alembic + Gemini for generation +
  Caspian for messaging. Owns all business logic and secrets.
- **Frontend** — [Tanisha141007/mealtime-harmony](https://github.com/Tanisha141007/mealtime-harmony).
  TanStack Start (React 19 + Tailwind v4 + shadcn/ui), originally scaffolded
  in Lovable. **Don't rewrite its git history** (force-push/rebase/amend
  already-pushed commits) - Lovable syncs against it live and the owner
  will lose editor history if you do.

They talk over plain HTTPS + a Supabase JWT - no shared code, no monorepo.

## Live deployment

- Frontend: https://tanisha141007-mealtime-harmony.tanishamalani1.workers.dev
  (Cloudflare Workers - it's a TanStack Start SSR app, not a static site;
  deploy is CI-driven, see `mealtime-harmony/.github/workflows/deploy.yml`)
- Backend: https://caspian-meal-planner-api.onrender.com (Render free web
  service; `/health` for a liveness check)
- DB + Auth: Supabase (Postgres + email-magic-link auth)
- Scheduling: Render's free tier has no worker/cron, so
  `.github/workflows/scheduled-jobs.yml` (this repo) hits shared-secret-
  protected `/internal/*` routes on a GitHub Actions cron instead - see
  `app/api/routers/internal.py`.

## Architecture

```
mealtime-harmony (Cloudflare Workers)
  React Query + fetch, Bearer <supabase JWT> on every call
        |
        v
caspian-meal-planner API (Render, FastAPI) - app/api/
  verifies Supabase JWT (JWKS) -> owner_user_id
  app/meal_planner/generator.py   - candidate narrowing + Gemini prompt -> weekly/monthly plan
  app/messaging/handler.py        - Caspian channel connect + on_message handler
  app/messaging/formatter.py      - plan -> cook-facing message text
  app/scheduler/jobs.py           - weekly/monthly/daily-send job bodies
        ^
        | scheduled trigger (shared secret, not user auth)
GitHub Actions cron (this repo's .github/workflows/scheduled-jobs.yml)
        |
        v
Supabase Postgres  (DATABASE_URL)
        |
        v
Caspian -> cook's Telegram
```

## Access you'll need

Ask the project owner to invite you to:
- **GitHub**, both repos above (Write; Admin if you'll manage Actions secrets)
- **Render** (Team → Invite Member) - logs, redeploys, env vars
- **Cloudflare** (Manage Account → Members) - the Worker lives under Compute
- **Supabase** (Project Settings → Team)
- Local dev secrets (`GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`,
  `CASPIAN_API_KEY`, Supabase anon key, `INTERNAL_JOBS_SECRET`) shared
  directly (they're not in git - see `.env.example` in each repo for what's
  needed, values come from whoever holds them)

## Status by milestone

- **M1** (backend JSON API), **M2** (candidate narrowing, single-meal swap,
  allergy expansion), **M3** (Supabase auth, both halves), **M4** (frontend
  wired to the real API) - all done and verified live.
- **Messaging channel** - done, verified live end-to-end (Telegram: connect,
  link via `Household.link_code`, real proactive send, human-confirmed
  receipt). Twilio/Telnyx were evaluated and parked - both require billing
  for real (non-template) SMS.
- **M5 (deploy)** - in progress. Backend and frontend are both live at the
  URLs above. Remaining/recent:
  - Production Supabase Postgres started with **zero recipes seeded** -
    `POST /internal/seed-recipes` (shared-secret protected) exists to fix
    this remotely since Render's free tier has no Shell access. Watch for
    the same trap again if the DB is ever reset: plan generation "succeeds"
    (200 response) but returns empty when there are no recipe candidates.
  - `seed_recipes()` had a real perf bug worth knowing about if you touch
    it again: SQLAlchemy's `bulk_update_mappings()` still executes one
    UPDATE per row under the hood - fast against local SQLite's near-zero
    latency, but thousands of round-trips (and a timeout) against a real
    network hop like Supabase's pooler. Fixed with a genuine single
    `INSERT ... ON CONFLICT DO UPDATE` per chunk (`app/data/seed.py`) - if
    you're adding other bulk-write paths, use that pattern, not
    `bulk_insert_mappings`/`bulk_update_mappings`.
  - `mealtime-harmony`'s deploy workflow needed: `bun` not `npm` (bun.lock
    is the tracked lockfile, `package-lock.json` is gitignored on purpose),
    an explicit `wranglerVersion`/entry-point (auto-detection of the
    Nitro-generated `wrangler.json` failed under the default wrangler
    version), and the Cloudflare account's `*.workers.dev` subdomain
    registered once by hand first (can't be done non-interactively from CI).

## Running locally

Backend:
```bash
cd caspian-meal-planner
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # fill in values
.venv/bin/uvicorn app.api.main:app --reload --port 8001
```

Frontend:
```bash
cd mealtime-harmony
bun install
cp .env.example .env.local   # fill in values, VITE_API_BASE_URL=http://localhost:8001
bun run dev
```

## Known simplifications (not bugs, just scope cuts worth knowing about)

- One Caspian channel per deployment (`CASPIAN_CHANNEL` env var), not
  per-household routing.
- `run_due_daily_sends()` checks send-time due-ness on every ~15-min
  external trigger rather than a precise per-minute cron - up to ~15-20 min
  of slack on the configured `send_time`.
- No automated tests yet - everything's been verified by live/manual
  end-to-end runs (see milestone notes above and git history for what was
  checked at each step).
