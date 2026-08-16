"""Weekly plan generation, monthly shopping-list rollup, and the daily
send - the three cron jobs that drive the whole workflow. Wired up with
APScheduler so the whole thing runs as one process alongside
client.listen(); swap for a real cron / task queue in production."""

import datetime as dt
import logging

from app.db import get_session
from app.meal_planner.generator import candidate_recipes, cuisine_weights, generate_weekly_plan, monthly_shopping_list
from app.messaging.formatter import format_weekly_owner_email
from app.messaging.handler import get_client, send_daily_message, send_owner_email
from app.models import Household, MealPlan, MealPlanItem, Recipe

logger = logging.getLogger("scheduler")


def _next_monday(today=None) -> dt.date:
    today = today or dt.date.today()
    days_ahead = (7 - today.weekday()) % 7 or 7
    return today + dt.timedelta(days=days_ahead)


def weekly_plan_job():
    """Sunday 20:00: generates next week's chart and emails it to each signed-in owner."""
    session = get_session()
    try:
        households = session.query(Household).filter(Household.active.is_(True)).all()
    finally:
        session.close()

    week_start = _next_monday()
    for h in households:
        try:
            plan_id = generate_weekly_plan(h.id, week_start)
            logger.info("Generated weekly plan %s for household %s (%s)", plan_id, h.id, h.name)
            send_weekly_owner_email(h.id, plan_id, week_start)
        except Exception:
            logger.exception("Failed to generate weekly plan for household %s", h.id)


def _discover_suggestions(session, household: Household, week_items: list, limit: int = 6) -> list[Recipe]:
    planned_recipe_ids = {rid for item in week_items for rid in (item.dish_recipe_ids or [])}
    weights = cuisine_weights(session, household)

    def rank(recipe: Recipe):
        cuisine_weight = weights.get(recipe.cuisine_style, 0.5)
        slot_score = len(recipe.meal_types or [])
        return (-cuisine_weight, -slot_score, recipe.prep_time_min, recipe.name)

    pool = [recipe for recipe in candidate_recipes(session, household) if recipe.id not in planned_recipe_ids]
    return sorted(pool, key=rank)[:limit]


def send_weekly_owner_email(household_id: int, plan_id: int, week_start: dt.date) -> bool:
    """Formats and sends the household-owner Sunday email through Caspian."""
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household is None:
            logger.warning("No household %s for weekly owner email", household_id)
            return False
        if not household.owner_email:
            logger.info("Skipping weekly owner email for household %s - no owner_email yet", household_id)
            return False

        plan = session.get(MealPlan, plan_id)
        if plan is None:
            logger.warning("No meal plan %s for household %s weekly owner email", plan_id, household_id)
            return False

        week_items = (
            session.query(MealPlanItem)
            .filter(MealPlanItem.meal_plan_id == plan.id)
            .order_by(MealPlanItem.date, MealPlanItem.meal_slot)
            .all()
        )
        recipe_ids = {rid for item in week_items for rid in (item.dish_recipe_ids or [])}
        suggestions = _discover_suggestions(session, household, week_items)
        recipe_ids.update(recipe.id for recipe in suggestions)
        recipe_cache = {recipe.id: recipe for recipe in session.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()}

        text = format_weekly_owner_email(household, week_start, week_items, recipe_cache, suggestions)
        send_owner_email(household, text)
        logger.info("Sent weekly owner email for household %s to %s", household_id, household.owner_email)
        return True
    except Exception:
        logger.exception("Failed to send weekly owner email for household %s", household_id)
        return False
    finally:
        session.close()


def monthly_rollup_job():
    """1st of the month, 08:00: aggregates the month just finished into one
    ingredient shopping list and texts it to the cook."""
    today = dt.date.today()
    last_month_end = dt.date(today.year, today.month, 1) - dt.timedelta(days=1)
    month_start = dt.date(last_month_end.year, last_month_end.month, 1)

    session = get_session()
    try:
        households = session.query(Household).filter(Household.active.is_(True)).all()
    finally:
        session.close()

    client = get_client()
    for h in households:
        shopping_list = monthly_shopping_list(h.id, month_start)
        if not shopping_list or not h.caspian_conversation_id:
            continue
        lines = [f"{i['item']} {i['qty']}{i['unit']}" for i in shopping_list]
        text = f"Monthly shopping list for {h.name} ({month_start.strftime('%B %Y')}):\n" + ", ".join(lines)
        try:
            client.send_message(h.caspian_conversation_id, text=text)
        except Exception:
            logger.exception("Failed to send monthly rollup to household %s", h.id)


def daily_send_job(send_time: str = None):
    """Pushes today's breakfast/lunch/snack/dinner - with ingredients and
    portion sizes - to every household due at this send_time."""
    session = get_session()
    try:
        query = session.query(Household).filter(Household.active.is_(True))
        if send_time:
            query = query.filter(Household.send_time == send_time)
        households = query.all()

        today = dt.date.today()
        recipe_cache = {r.id: r for r in session.query(Recipe).all()}

        for h in households:
            items = (
                session.query(MealPlanItem)
                .filter(MealPlanItem.household_id == h.id, MealPlanItem.date == today)
                .all()
            )
            if not items:
                logger.warning("No meal plan items for household %s on %s - run weekly_plan_job first", h.id, today)
                continue

            slot_items = {it.meal_slot: it for it in items}
            try:
                send_daily_message(h, slot_items, recipe_cache)
                for it in items:
                    it.sent_at = dt.datetime.utcnow()
                    it.delivery_status = "sent"
            except Exception:
                logger.exception("Failed to send daily message to household %s", h.id)
                for it in items:
                    it.delivery_status = "failed"
            session.commit()
    finally:
        session.close()


def run_due_daily_sends(window_minutes: int = 20):
    """The M5 replacement for start_scheduler()'s "one cron trigger per
    distinct send_time" - that model needs a long-lived process, which
    Render's free tier doesn't give us (see app/api/routers/internal.py).
    Instead this runs on every external trigger (GitHub Actions, ~every 15
    min) and checks each active household's send_time against the current
    local time itself, sending if due and not already sent today. Keeps
    real per-household custom timing (the originally-scoped feature)
    despite the coarser, externally-driven interval - window_minutes is
    slack against that interval so a household is never skipped because a
    trigger landed a few minutes early or late."""
    from zoneinfo import ZoneInfo

    from app.config import APP_TIMEZONE

    now_local = dt.datetime.now(ZoneInfo(APP_TIMEZONE))
    today = now_local.date()

    session = get_session()
    try:
        households = session.query(Household).filter(Household.active.is_(True)).all()
        recipe_cache = {r.id: r for r in session.query(Recipe).all()}
        sent_household_ids = []

        for h in households:
            try:
                hour, minute = (int(x) for x in (h.send_time or "07:00").split(":"))
            except ValueError:
                logger.warning("Household %s has an unparseable send_time %r - skipping", h.id, h.send_time)
                continue

            due_at = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if not (due_at <= now_local < due_at + dt.timedelta(minutes=window_minutes)):
                continue

            items = (
                session.query(MealPlanItem)
                .filter(MealPlanItem.household_id == h.id, MealPlanItem.date == today)
                .all()
            )
            if not items:
                logger.warning("No meal plan items for household %s on %s - run weekly_plan_job first", h.id, today)
                continue
            if all(it.delivery_status == "sent" for it in items):
                continue  # already sent today, don't resend on the next poll

            slot_items = {it.meal_slot: it for it in items}
            try:
                send_daily_message(h, slot_items, recipe_cache)
                for it in items:
                    it.sent_at = dt.datetime.utcnow()
                    it.delivery_status = "sent"
                sent_household_ids.append(h.id)
            except Exception:
                logger.exception("Failed to send daily message to household %s", h.id)
                for it in items:
                    it.delivery_status = "failed"
            session.commit()

        return sent_household_ids
    finally:
        session.close()


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.config import APP_TIMEZONE

    scheduler = BackgroundScheduler(timezone=APP_TIMEZONE)
    scheduler.add_job(weekly_plan_job, "cron", day_of_week="sun", hour=20, id="weekly_plan")
    scheduler.add_job(monthly_rollup_job, "cron", day=1, hour=8, id="monthly_rollup")

    session = get_session()
    try:
        send_times = {h.send_time for h in session.query(Household).filter(Household.active.is_(True)).all()}
    finally:
        session.close()

    # One cron trigger per distinct household send_time (defaults to 07:00
    # if no households exist yet). Re-run start_scheduler() after adding a
    # household with a new send_time to pick it up.
    for t in send_times or {"07:00"}:
        hour, minute = (int(x) for x in t.split(":"))
        scheduler.add_job(daily_send_job, "cron", hour=hour, minute=minute, args=[t], id=f"daily_send_{t}")

    scheduler.start()
    return scheduler
