"""Assembles the Monday email: one week of the household's active chart plus
the dishes they could add to it.

Sits between the planner and the transport so the scheduled job
(app/scheduler/jobs.py) and the on-demand API route
(app/api/routers/email_chart.py) build byte-identical mail - the route is
what you use to preview or re-send exactly what Monday's cron sends.
"""

import datetime as dt
from collections import defaultdict

from app.config import WEEKLY_EMAIL_SUGGESTIONS
from app.meal_planner.generator import suggested_recipes
from app.messaging.email_formatter import (
    weekly_email_blocks,
    weekly_email_text,
    weekly_shopping_list,
)
from app.models import MealPlan, MealPlanItem, Recipe


def this_monday(date: dt.date = None) -> dt.date:
    date = date or dt.date.today()
    return date - dt.timedelta(days=date.weekday())


def active_week_items(session, household_id: int, week_start: dt.date) -> list:
    """This week's MealPlanItems from the *active* plan only - a superseded
    regeneration for the same week must not double up (see
    generate_weekly_plan()'s supersede step in app/meal_planner/generator.py)."""
    active_plan_ids = [
        p.id
        for p in session.query(MealPlan)
        .filter(
            MealPlan.household_id == household_id,
            MealPlan.period_type == "week",
            MealPlan.period_start == week_start,
            MealPlan.status == "active",
        )
        .all()
    ]
    if not active_plan_ids:
        return []
    return (
        session.query(MealPlanItem)
        .filter(
            MealPlanItem.household_id == household_id,
            MealPlanItem.date >= week_start,
            MealPlanItem.date < week_start + dt.timedelta(days=7),
            MealPlanItem.meal_plan_id.in_(active_plan_ids),
        )
        .all()
    )


def build_weekly_email(session, household, week_start: dt.date = None) -> dict:
    """Returns {week_start, text, blocks, days_planned, suggestions,
    shopping_list}. `text` and `blocks` are the same content in the two forms
    send_owner_email() picks between; an empty `days_planned` means no active
    plan exists for that week and the caller should skip rather than mail an
    empty chart."""
    week_start = week_start or this_monday()
    items = active_week_items(session, household.id, week_start)

    by_date = defaultdict(dict)
    for item in items:
        by_date[item.date][item.meal_slot] = item
    days = [
        (week_start + dt.timedelta(days=offset), by_date.get(week_start + dt.timedelta(days=offset), {}))
        for offset in range(7)
    ]

    planned_ids = {rid for item in items for rid in (item.dish_recipe_ids or [])}
    recipe_cache = (
        {r.id: r for r in session.query(Recipe).filter(Recipe.id.in_(planned_ids)).all()}
        if planned_ids
        else {}
    )

    # Suggestions exclude what's already on the plan - "new this week" has to
    # actually be new relative to the chart sitting above it in the same email.
    suggestions = suggested_recipes(
        session, household, exclude_ids=planned_ids, limit=WEEKLY_EMAIL_SUGGESTIONS
    )
    shopping_list = weekly_shopping_list(days, recipe_cache)

    args = (household, week_start, days, recipe_cache, suggestions, shopping_list)
    return {
        "week_start": week_start,
        "text": weekly_email_text(*args),
        "blocks": weekly_email_blocks(*args),
        "days_planned": sum(1 for _date, slots in days if slots),
        "suggestions": suggestions,
        "shopping_list": shopping_list,
    }
