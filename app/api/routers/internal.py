"""M5: Render's free web-service tier has no persistent worker or cron, so
the jobs that used to run in-process via app/scheduler/jobs.py's
start_scheduler() (inbound-message polling, daily send, weekly plan,
monthly rollup) are instead triggered externally on a schedule - see
.github/workflows/scheduled-jobs.yml, which hits these routes via cron.

Every route here is gated by a shared secret header (X-Internal-Secret),
not a user JWT - there's no user on the other end, just GitHub Actions.
INTERNAL_JOBS_SECRET unset means these 401 unconditionally, never run open.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.config import INTERNAL_JOBS_SECRET
from app.data.seed import RECIPES_PATH, seed_recipes, seed_region_cuisine_map
from app.db import get_session
from app.messaging.handler import ensure_ready, get_client
from app.models import AppState, Household, Recipe
from app.scheduler.jobs import monthly_rollup_job, run_due_daily_sends, weekly_plan_job

router = APIRouter(prefix="/internal", tags=["internal"])

_CURSOR_KEY = "caspian_after_seq"


def _verify_secret(x_internal_secret: str = Header(default="")):
    if not INTERNAL_JOBS_SECRET or x_internal_secret != INTERNAL_JOBS_SECRET:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing internal secret")


@router.post("/poll-messages", dependencies=[Depends(_verify_secret)])
def poll_messages():
    """One-shot replacement for client.listen()'s infinite loop:
    dispatch_pending() drains everything new since the last stored cursor
    through the same @client.on_message handler register_handler() sets
    up, then we persist the new cursor in AppState so the next invocation
    (a separate process entirely) picks up where this one left off."""
    ensure_ready()
    client = get_client()

    session = get_session()
    try:
        state = session.get(AppState, _CURSOR_KEY)
        after_seq = int(state.value) if state and state.value else 0
    finally:
        session.close()

    new_seq = client.dispatch_pending(after_seq=after_seq)

    session = get_session()
    try:
        state = session.get(AppState, _CURSOR_KEY)
        if state is None:
            session.add(AppState(key=_CURSOR_KEY, value=str(new_seq)))
        else:
            state.value = str(new_seq)
        session.commit()
    finally:
        session.close()

    return {"after_seq": new_seq}


@router.post("/daily-send", dependencies=[Depends(_verify_secret)])
def daily_send():
    """Checks every active household's configured send_time against the
    current time and sends anything due - see run_due_daily_sends() for why
    this replaced one-cron-per-send_time now that there's no long-lived
    process to hold those crons."""
    ensure_ready()
    sent = run_due_daily_sends()
    return {"sent_household_ids": sent}


@router.post("/weekly-plan", dependencies=[Depends(_verify_secret)])
def weekly_plan():
    """Generates next week's chart for every active household. Scheduled
    for Sunday evening via the workflow's own cron entry (not a day-of-week
    check here) - see scheduled-jobs.yml."""
    weekly_plan_job()
    return {"status": "ok"}


@router.post("/monthly-rollup", dependencies=[Depends(_verify_secret)])
def monthly_rollup():
    """Aggregates the month just finished into one shopping list per
    household. Scheduled for the 1st of the month via the workflow's own
    cron entry - see scheduled-jobs.yml."""
    monthly_rollup_job()
    return {"status": "ok"}


@router.post("/seed-recipes", dependencies=[Depends(_verify_secret)])
def seed_recipes_route():
    """One-off, not on any schedule: loads the full ~4,262-recipe Kaggle-
    derived universe (app/data/recipes_ingested.json) plus the region-
    cuisine map into whatever DB this instance's DATABASE_URL points at.
    Exists because Render's free tier has no Shell access to run
    `python -m app.data.seed` directly against production the way we did
    locally - this is the same operation, reachable over HTTP instead.
    Safe to re-run (seed_recipes upserts by id)."""
    ingested_path = RECIPES_PATH.parent / "recipes_ingested.json"
    path = ingested_path if ingested_path.exists() else RECIPES_PATH
    seed_recipes(path)
    seed_region_cuisine_map()

    session = get_session()
    try:
        count = session.query(Recipe).count()
    finally:
        session.close()

    return {"recipe_count": count, "seeded_from": path.name}


@router.get("/debug-households", dependencies=[Depends(_verify_secret)])
def debug_households():
    """Read-only diagnostic: what's actually stored for link_code / linked
    state per household, without needing raw DB access. Added to debug a
    live 'the cook's code isn't recognized' report - no other way to see
    production data short of the Supabase dashboard's table editor."""
    session = get_session()
    try:
        households = session.query(Household).all()
        return [
            {
                "id": h.id,
                "name": h.name,
                "cook_name": h.cook_name,
                "link_code": h.link_code,
                "linked": h.caspian_conversation_id is not None,
                "active": h.active,
            }
            for h in households
        ]
    finally:
        session.close()
