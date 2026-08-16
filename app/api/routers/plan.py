import datetime as dt
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db, get_owned_household
from app.api.schemas import AssignRequest, GenerateWeekRequest, SwapRequest
from app.api.serializers import serialize_day_plan
from app.config import llm_configured
from app.meal_planner.generator import generate_weekly_plan, regenerate_single_meal
from app.messaging.weekly_email import active_week_items
from app.models import Household, MealPlan, MealPlanItem, Recipe

_LLM_NOT_CONFIGURED = "No LLM provider key configured yet (GEMINI_API_KEY/ANTHROPIC_API_KEY) - can't generate a plan"

router = APIRouter(prefix="/api/households/{household_id}/plan", tags=["plan"])


def _this_monday(date: dt.date) -> dt.date:
    return date - dt.timedelta(days=date.weekday())


def _recipe_cache_for(db, items: list) -> dict:
    """Only the recipes actually referenced by these items, not the whole
    table - serialize_day_plan needs full Recipe objects to embed."""
    ids = {rid for it in items for rid in (it.dish_recipe_ids or [])}
    if not ids:
        return {}
    return {r.id: r for r in db.query(Recipe).filter(Recipe.id.in_(ids)).all()}


def _week_days(db, household_id: int, week_start: dt.date) -> list:
    """Only the *active* plan's items - a superseded regeneration for the
    same week must not also show up (see generate_weekly_plan's supersede
    step in app/meal_planner/generator.py). Shares that query with the weekly
    family email so both read a week the same way."""
    items = active_week_items(db, household_id, week_start)
    recipe_cache = _recipe_cache_for(db, items)
    by_date = defaultdict(dict)
    for it in items:
        by_date[it.date][it.meal_slot] = it

    return [
        serialize_day_plan(week_start + dt.timedelta(days=o), by_date.get(week_start + dt.timedelta(days=o), {}), recipe_cache)
        for o in range(7)
    ]


def _get_or_create_plan_for_date(db, household_id: int, date: dt.date) -> MealPlan:
    week_start = _this_monday(date)
    plan = (
        db.query(MealPlan)
        .filter(
            MealPlan.household_id == household_id,
            MealPlan.period_type == "week",
            MealPlan.period_start == week_start,
            MealPlan.status == "active",
        )
        .first()
    )
    if plan is None:
        plan = MealPlan(household_id=household_id, period_type="week", period_start=week_start, status="active")
        db.add(plan)
        db.flush()
    return plan


@router.get("")
def get_week(week_start: dt.date | None = None, household: Household = Depends(get_owned_household), db=Depends(get_db)):
    return _week_days(db, household.id, week_start or _this_monday(dt.date.today()))


@router.post("/generate")
def generate_week(body: GenerateWeekRequest, household: Household = Depends(get_owned_household), db=Depends(get_db)):
    if not llm_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _LLM_NOT_CONFIGURED)
    week_start = body.week_start or _this_monday(dt.date.today())
    try:
        generate_weekly_plan(household.id, week_start)
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Plan generation failed: {e}") from e
    return _week_days(db, household.id, week_start)


@router.post("/assign")
def assign_meal(body: AssignRequest, household: Household = Depends(get_owned_household), db=Depends(get_db)):
    """Discover's "add to plan" - directly sets one slot to a chosen recipe,
    creating that week's plan row first if generate/plan was never called for it."""
    plan = _get_or_create_plan_for_date(db, household.id, body.date)
    item = (
        db.query(MealPlanItem)
        .filter(
            MealPlanItem.meal_plan_id == plan.id,
            MealPlanItem.date == body.date,
            MealPlanItem.meal_slot == body.slot,
        )
        .first()
    )
    if item is None:
        item = MealPlanItem(
            meal_plan_id=plan.id,
            household_id=household.id,
            date=body.date,
            meal_slot=body.slot,
            dish_recipe_ids=[body.recipe_id],
            portion_servings=float(household.family_size),
            note="",
        )
        db.add(item)
    else:
        item.dish_recipe_ids = [body.recipe_id]
    db.commit()
    recipe_cache = _recipe_cache_for(db, [item])
    return serialize_day_plan(body.date, {body.slot: item}, recipe_cache)


@router.post("/swap")
def swap_meal(body: SwapRequest, household: Household = Depends(get_owned_household), db=Depends(get_db)):
    """The frontend's per-meal swap button - regenerates ONE slot via the
    LLM (candidate-narrowed, excludes the rest of this week + the 14-day
    lookback) without touching anything else in the week."""
    if not llm_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _LLM_NOT_CONFIGURED)
    try:
        item = regenerate_single_meal(household.id, body.date, body.slot, body.hint)
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Swap failed: {e}") from e
    recipe_cache = _recipe_cache_for(db, [item])
    return serialize_day_plan(body.date, {body.slot: item}, recipe_cache)
