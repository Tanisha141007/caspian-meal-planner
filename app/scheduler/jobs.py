"""Weekly plan generation, monthly shopping-list rollup, and the daily
send - the three cron jobs that drive the whole workflow. Wired up with
APScheduler so the whole thing runs as one process alongside
client.listen(); swap for a real cron / task queue in production."""

import datetime as dt
import logging

from app.db import get_session
from app.meal_planner.generator import generate_weekly_plan, monthly_shopping_list
from app.messaging.handler import get_client, send_daily_message
from app.models import Household, MealPlanItem, Recipe

logger = logging.getLogger("scheduler")


def _next_monday(today=None) -> dt.date:
    today = today or dt.date.today()
    days_ahead = (7 - today.weekday()) % 7 or 7
    return today + dt.timedelta(days=days_ahead)


def weekly_plan_job():
    """Sunday 20:00: generates next week's chart for every active household."""
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
        except Exception:
            logger.exception("Failed to generate weekly plan for household %s", h.id)


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
