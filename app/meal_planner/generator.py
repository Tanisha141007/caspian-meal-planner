import datetime as dt
import json
from collections import defaultdict

from anthropic import Anthropic

from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MEAL_SLOTS
from app.db import get_session
from app.meal_planner.prompts import build_feedback_prompt, build_plan_prompt
from app.models import Household, MealPlan, MealPlanItem, Recipe

_client = None


def _anthropic():
    global _client
    if _client is None:
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.lower().startswith("json"):
            text = text.split("\n", 1)[1]
    return json.loads(text)


def _diet_allowlist(diet_type: str) -> set:
    return {
        "vegan": {"vegan"},
        "jain": {"veg", "vegan"},
        "veg": {"veg", "vegan"},
        "eggetarian": {"veg", "vegan", "egg"},
        "non-veg": {"veg", "vegan", "egg", "non-veg"},
    }.get(diet_type, {"veg", "vegan"})


def candidate_recipes(session, household: Household):
    """Recipes matching the household's hard constraints: diet type, no
    allergens, no disliked ingredients. This filtered set is what gets
    handed to Claude as context - the recipe universe never leaves the DB
    wholesale."""
    allowed_diets = _diet_allowlist(household.diet_type)
    banned = {i.lower() for i in (household.allergies or []) + (household.disliked_ingredients or [])}

    candidates = []
    for r in session.query(Recipe).all():
        if r.diet not in allowed_diets:
            continue
        ingredient_names = [ing["item"].lower() for ing in (r.ingredients or [])]
        if any(b in name for b in banned for name in ingredient_names):
            continue
        candidates.append(r)
    return candidates


def recent_recipe_ids(session, household_id: int, since: dt.date):
    items = (
        session.query(MealPlanItem)
        .filter(MealPlanItem.household_id == household_id, MealPlanItem.date >= since)
        .all()
    )
    ids = []
    for it in items:
        ids.extend(it.dish_recipe_ids or [])
    return ids


def _call_claude_for_plan(household, candidates, recent_ids, start_date, num_days):
    system, user = build_plan_prompt(household, candidates, recent_ids, start_date, num_days, MEAL_SLOTS)
    response = _anthropic().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _parse_json(response.content[0].text)


def generate_weekly_plan(household_id: int, week_start: dt.date) -> int:
    """Generates and persists a 7-day meal chart for one household.
    Returns the new meal_plan id."""
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household is None:
            raise ValueError(f"No household with id {household_id}")

        candidates = candidate_recipes(session, household)
        recent_ids = recent_recipe_ids(session, household_id, week_start - dt.timedelta(days=14))
        plan_json = _call_claude_for_plan(household, candidates, recent_ids, week_start, 7)

        plan = MealPlan(household_id=household_id, period_type="week", period_start=week_start, status="active")
        session.add(plan)
        session.flush()

        for day_entry in plan_json["days"]:
            date = dt.date.fromisoformat(day_entry["date"])
            for slot, meal in day_entry["meals"].items():
                session.add(
                    MealPlanItem(
                        meal_plan_id=plan.id,
                        household_id=household_id,
                        date=date,
                        meal_slot=slot,
                        dish_recipe_ids=meal["recipe_ids"],
                        portion_servings=float(household.family_size),
                        note=meal.get("note", ""),
                    )
                )
        session.commit()
        return plan.id
    finally:
        session.close()


def generate_monthly_plan(household_id: int, month_start: dt.date) -> list:
    """A 'monthly chart' is four consecutive weekly charts, generated one
    week at a time so each week can react to the previous week's variety
    instead of guessing 28 days in one shot."""
    plan_ids = []
    for week_offset in range(4):
        week_start = month_start + dt.timedelta(weeks=week_offset)
        plan_ids.append(generate_weekly_plan(household_id, week_start))
    return plan_ids


def monthly_shopping_list(household_id: int, month_start: dt.date, num_days: int = 28):
    """Aggregates ingredient quantities across a month of MealPlanItems,
    scaled by portion size - the bulk grocery list for the household."""
    session = get_session()
    try:
        end = month_start + dt.timedelta(days=num_days)
        items = (
            session.query(MealPlanItem)
            .filter(
                MealPlanItem.household_id == household_id,
                MealPlanItem.date >= month_start,
                MealPlanItem.date < end,
            )
            .all()
        )
        recipe_cache = {r.id: r for r in session.query(Recipe).all()}

        totals = defaultdict(float)
        units = {}
        for it in items:
            for rid in it.dish_recipe_ids or []:
                recipe = recipe_cache.get(rid)
                if not recipe:
                    continue
                for ing in recipe.ingredients or []:
                    totals[ing["item"]] += ing["qty"] * it.portion_servings
                    units[ing["item"]] = ing["unit"]

        return [{"item": k, "qty": round(v, 1), "unit": units[k]} for k, v in sorted(totals.items())]
    finally:
        session.close()


def interpret_cook_reply(message_text: str, todays_recipe_ids: list) -> dict:
    """Turns one inbound WhatsApp/SMS message from the cook into structured
    feedback: dislike, swap request, ingredient issue, confirmation, etc."""
    system, user = build_feedback_prompt(message_text, todays_recipe_ids)
    response = _anthropic().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=300,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _parse_json(response.content[0].text)
