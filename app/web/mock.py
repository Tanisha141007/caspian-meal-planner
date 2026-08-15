"""Rule-based fallbacks for the web preview when no LLM provider key is
set, so the family/cook dashboards work with zero external keys. Still
diet/allergy-safe: it reuses candidate_recipes() for filtering. Swapped
out automatically for the real Claude generator in app/web/main.py the
moment a key is configured."""

import datetime as dt
import random

from app.config import MEAL_SLOTS
from app.db import get_session
from app.meal_planner.generator import candidate_recipes
from app.models import Household, MealPlan, MealPlanItem


def _pick_combo(pool):
    if not pool:
        return []
    staples = [r for r in pool if "staple" in (r.tags or [])]
    mains = [r for r in pool if r not in staples]
    combo = []
    if mains:
        combo.append(random.choice(mains))
    if staples:
        combo.append(random.choice(staples))
    if not combo and pool:
        combo.append(random.choice(pool))
    return [r.id for r in combo]


def mock_generate_weekly_plan(household_id: int, week_start: dt.date) -> int:
    session = get_session()
    try:
        household = session.get(Household, household_id)
        candidates = candidate_recipes(session, household)
        by_slot = {slot: [r for r in candidates if slot in (r.meal_types or [])] for slot in MEAL_SLOTS}

        plan = MealPlan(household_id=household_id, period_type="week", period_start=week_start, status="active")
        session.add(plan)
        session.flush()

        for day_offset in range(7):
            date = week_start + dt.timedelta(days=day_offset)
            for slot in MEAL_SLOTS:
                pool = by_slot.get(slot, [])
                dish_ids = _pick_combo(pool) if slot in ("lunch", "dinner") else (
                    [random.choice(pool).id] if pool else []
                )
                session.add(
                    MealPlanItem(
                        meal_plan_id=plan.id,
                        household_id=household_id,
                        date=date,
                        meal_slot=slot,
                        dish_recipe_ids=dish_ids,
                        portion_servings=float(household.family_size),
                        note="",
                    )
                )
        session.commit()
        return plan.id
    finally:
        session.close()


def mock_generate_monthly_plan(household_id: int, month_start: dt.date) -> list:
    return [mock_generate_weekly_plan(household_id, month_start + dt.timedelta(weeks=w)) for w in range(4)]


_DISLIKE_WORDS = ["don't like", "dont like", "didn't like", "not good", "too spicy", "hated", "disliked"]
_SWAP_WORDS = ["instead", "swap", "change", "replace", "different dish"]
_INGREDIENT_WORDS = ["out of", "don't have", "dont have", "no ", "missing", "ran out"]
_CONFIRM_WORDS = ["thanks", "thank you", "ok", "okay", "great", "done", "yum", "perfect"]


def mock_interpret_feedback(message_text: str, todays_recipe_ids: list) -> dict:
    text = (message_text or "").lower()
    if any(w in text for w in _DISLIKE_WORDS):
        kind = "dislike"
    elif any(w in text for w in _SWAP_WORDS):
        kind = "swap_request"
    elif any(w in text for w in _INGREDIENT_WORDS):
        kind = "ingredient_issue"
    elif any(w in text for w in _CONFIRM_WORDS):
        kind = "confirmation"
    elif "?" in text:
        kind = "question"
    else:
        kind = "other"

    recipe_id = next((rid for rid in todays_recipe_ids if rid.replace("_", " ") in text), None)
    return {"type": kind, "recipe_id": recipe_id, "summary": (message_text or "")[:80]}
