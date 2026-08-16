import datetime as dt
import random
from collections import defaultdict

from app.config import MEAL_SLOTS
from app.db import get_session
from app.meal_planner.llm_client import generate_json
from app.meal_planner.prompts import build_ask_ai_prompt, build_feedback_prompt, build_plan_prompt, build_swap_prompt
from app.models import Household, MealPlan, MealPlanItem, Recipe, RegionCuisineMap

# A household can list a category term ("dairy") as an allergy/dislike, not
# just a literal ingredient name - expand it to what actually shows up in
# ingredient text before substring-matching. Diet-safety gap found during
# Phase 1 verification: a "dairy" entry alone caught 0% of dairy-containing
# recipes since no ingredient is literally named "dairy".
ALLERGY_CATEGORY_EXPANSIONS = {
    "dairy": ["milk", "ghee", "paneer", "curd", "yogurt", "yoghurt", "cream", "butter", "cheese", "khoya", "malai"],
    "nuts": ["peanut", "cashew", "almond", "walnut", "pistachio", "hazelnut", "pecan"],
    "tree nuts": ["cashew", "almond", "walnut", "pistachio", "hazelnut", "pecan"],
    "gluten": ["wheat", "maida", "atta", "semolina", "rava", "sooji", "barley", "flour"],
    "shellfish": ["prawn", "shrimp", "crab", "lobster", "oyster", "clam", "mussel"],
    "seafood": ["fish", "prawn", "shrimp", "crab", "lobster", "oyster", "clam", "mussel", "squid"],
    "soy": ["soya", "soy", "tofu"],
    "sesame": ["sesame", "til"],
}

# Baseline weight for cuisines with no explicit signal, so narrowing still
# leaves enough variety to fill a week rather than only ever offering the
# household's top 1-2 preferred cuisines. "pan-india" recipes (generically
# popular, not region-specific) get a solid default since they suit anyone.
_DEFAULT_CUISINE_WEIGHT = 0.5
_PAN_INDIA_WEIGHT = 1.5


def _diet_allowlist(diet_type: str) -> set:
    return {
        "vegan": {"vegan"},
        "jain": {"veg", "vegan"},
        "veg": {"veg", "vegan"},
        "eggetarian": {"veg", "vegan", "egg"},
        "non-veg": {"veg", "vegan", "egg", "non-veg"},
    }.get(diet_type, {"veg", "vegan"})


def _expand_banned_terms(terms: list) -> set:
    expanded = set()
    for term in terms:
        term = term.lower().strip()
        if not term:
            continue
        expanded.add(term)
        expanded.update(ALLERGY_CATEGORY_EXPANSIONS.get(term, []))
    return expanded


def candidate_recipes(session, household: Household):
    """Recipes matching the household's hard constraints: diet type, no
    allergens, no disliked ingredients. This filtered set - not the full
    recipe table - is what narrow_candidates() then ranks and caps before
    anything reaches the LLM."""
    allowed_diets = _diet_allowlist(household.diet_type)
    banned = _expand_banned_terms((household.allergies or []) + (household.disliked_ingredients or []))

    candidates = []
    for r in session.query(Recipe).all():
        if r.diet not in allowed_diets:
            continue
        ingredient_names = [ing["item"].lower() for ing in (r.ingredients or [])]
        if any(b in name for b in banned for name in ingredient_names):
            continue
        candidates.append(r)
    return candidates


def cuisine_weights(session, household: Household) -> dict:
    """cuisine_style -> weight. Explicit preferred_cuisines is the strongest
    signal (the plan's requirement: explicit preference overrides the
    regional default); falls back to RegionCuisineMap for the household's
    state when they haven't named any cuisines."""
    if household.preferred_cuisines:
        return {c.lower(): 3.0 for c in household.preferred_cuisines}
    if household.state:
        rows = session.query(RegionCuisineMap).filter(RegionCuisineMap.state == household.state).all()
        if rows:
            return {r.cuisine_style: r.weight for r in rows}
    return {}


def narrow_candidates(candidates: list, weights: dict, meal_slots: list, per_slot_cap: int = 60, hard_cap: int = 250):
    """Bounds what gets sent to the LLM regardless of how large the recipe
    table is (unbounded, this was ~224K tokens against the full ingested
    dataset - unusable). Ranks by cuisine weight within each meal slot so
    the cap favors the household's region/preferences rather than an
    arbitrary slice, then takes the union across slots so every slot still
    has options."""

    def weight_of(recipe):
        w = weights.get(recipe.cuisine_style, _DEFAULT_CUISINE_WEIGHT)
        if recipe.cuisine_style == "pan-india":
            w = max(w, _PAN_INDIA_WEIGHT)
        return w

    ranked = sorted(candidates, key=weight_of, reverse=True)
    selected = {}
    for slot in meal_slots:
        count = 0
        for recipe in ranked:
            if slot not in (recipe.meal_types or []):
                continue
            selected.setdefault(recipe.id, recipe)
            count += 1
            if count >= per_slot_cap:
                break

    result = list(selected.values())
    if len(result) > hard_cap:
        result = sorted(result, key=weight_of, reverse=True)[:hard_cap]
    random.shuffle(result)  # so the LLM doesn't see the same ordering (== same picks) every call
    return result


def suggested_recipes(session, household: Household, exclude_ids=None, limit: int = 6) -> list:
    """"New this week" picks for the Monday email - the same diet/allergy-safe
    candidate set Discover's rows are built from (app/api/routers/recipes.py),
    minus anything already on the plan we're mailing out, ranked by the
    household's cuisine weighting so the suggestions look like *their* food
    rather than a random slice of the table.

    Deterministic given the same inputs (no shuffle): this runs once a week
    and the family sees the result, so a stable "best N" beats a lucky draw."""
    exclude = set(exclude_ids or [])
    weights = cuisine_weights(session, household)
    pool = [r for r in candidate_recipes(session, household) if r.id not in exclude]

    def rank(recipe):
        w = weights.get(recipe.cuisine_style, _DEFAULT_CUISINE_WEIGHT)
        if recipe.cuisine_style == "pan-india":
            w = max(w, _PAN_INDIA_WEIGHT)
        return (-w, recipe.name)

    return sorted(pool, key=rank)[:limit]


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


def _call_llm_for_plan(household, candidates, recent_ids, start_date, num_days):
    system, user = build_plan_prompt(household, candidates, recent_ids, start_date, num_days, MEAL_SLOTS)
    return generate_json(system, user, max_tokens=4000)


def generate_weekly_plan(household_id: int, week_start: dt.date) -> int:
    """Generates and persists a 7-day meal chart for one household.
    Returns the new meal_plan id."""
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household is None:
            raise ValueError(f"No household with id {household_id}")

        candidates = candidate_recipes(session, household)
        weights = cuisine_weights(session, household)
        narrowed = narrow_candidates(candidates, weights, MEAL_SLOTS)
        recent_ids = recent_recipe_ids(session, household_id, week_start - dt.timedelta(days=14))
        plan_json = _call_llm_for_plan(household, narrowed, recent_ids, week_start, 7)

        # Regenerating the same week (the frontend's "Regenerate" action)
        # would otherwise leave two MealPlan rows both claiming these dates -
        # anything reading by date range (not by meal_plan_id) would then see
        # duplicates. Supersede rather than delete: history stays queryable.
        (
            session.query(MealPlan)
            .filter(
                MealPlan.household_id == household_id,
                MealPlan.period_type == "week",
                MealPlan.period_start == week_start,
                MealPlan.status == "active",
            )
            .update({"status": "superseded"})
        )

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


def regenerate_single_meal(household_id: int, date: dt.date, slot: str, hint: str = "") -> MealPlanItem:
    """Swaps one meal slot on one day without touching the rest of the
    week's plan - the frontend's per-meal swap button. `hint` is an
    optional free-text nudge for this swap specifically (e.g. "something
    lighter today")."""
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household is None:
            raise ValueError(f"No household with id {household_id}")

        item = (
            session.query(MealPlanItem)
            .filter(
                MealPlanItem.household_id == household_id,
                MealPlanItem.date == date,
                MealPlanItem.meal_slot == slot,
            )
            .first()
        )
        if item is None:
            raise ValueError(f"No planned meal for household {household_id} on {date} ({slot})")

        # Exclude whatever else this week already uses (no duplicate dish in
        # one week) plus the usual 14-day lookback; fall back to just the
        # lookback if that leaves nothing for this slot to pick from.
        same_week_ids = {
            rid
            for other in session.query(MealPlanItem).filter(MealPlanItem.meal_plan_id == item.meal_plan_id).all()
            for rid in (other.dish_recipe_ids or [])
        }
        recent_ids = set(recent_recipe_ids(session, household_id, date - dt.timedelta(days=14)))

        candidates = candidate_recipes(session, household)
        weights = cuisine_weights(session, household)

        pool = [c for c in candidates if c.id not in (same_week_ids | recent_ids)]
        if not any(slot in (r.meal_types or []) for r in pool):
            pool = [c for c in candidates if c.id not in recent_ids]

        narrowed = narrow_candidates(pool, weights, [slot], per_slot_cap=40)

        system, user = build_swap_prompt(household, narrowed, slot, hint)
        result = generate_json(system, user, max_tokens=300)

        item.dish_recipe_ids = result["recipe_ids"]
        item.note = result.get("note", item.note)
        session.commit()
        session.refresh(item)
        return item
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


def interpret_cook_reply(
    message_text: str,
    todays_recipe_ids: list,
    channel: str = "",
    sender_role: str = "cook",
    channel_guidance: str = "",
) -> dict:
    """Turns one inbound message into structured feedback: dislike, swap
    request, ingredient issue, confirmation, etc. Handles both senders - the
    cook replying to their daily message, and the family replying to the
    weekly chart email - since the same intents arrive from both."""
    system, user = build_feedback_prompt(
        message_text, todays_recipe_ids, channel=channel, sender_role=sender_role, channel_guidance=channel_guidance
    )
    return generate_json(system, user, max_tokens=300)


def ask_ai(household_id: int, message_text: str) -> dict:
    """The "Ask Caspian" free-text box: distills the request into a short
    instruction appended to household.notes (which every generation call
    already reads as free_text_notes), rather than just storing raw text -
    this is what makes it actually "fold into the profile" per the brief."""
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household is None:
            raise ValueError(f"No household with id {household_id}")

        system, user = build_ask_ai_prompt(household, message_text)
        result = generate_json(system, user, max_tokens=300)

        addition = (result.get("notes_append") or "").strip()
        if addition:
            household.notes = f"{household.notes}\n- {addition}".strip() if household.notes else f"- {addition}"
            session.commit()
            session.refresh(household)

        return {"reply": result.get("reply", ""), "notes_append": addition, "notes": household.notes}
    finally:
        session.close()
