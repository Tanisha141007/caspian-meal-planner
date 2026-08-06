"""FastAPI preview UI: a family/user dashboard (household profile + weekly
chart + monthly shopping list) and a cook dashboard (today's meals with
ingredients/portions + a feedback box that simulates a WhatsApp/SMS reply
round-trip, without needing Caspian/Twilio credentials).

Uses the real Claude-backed generator when ANTHROPIC_API_KEY is set,
otherwise falls back to app/web/mock.py so the whole flow is clickable with
zero external keys.

Run with: uvicorn app.web.main:app --reload
"""

import datetime as dt

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import ANTHROPIC_API_KEY, MEAL_SLOTS
from app.db import get_session, init_db
from app.meal_planner import generator as claude_generator
from app.messaging.formatter import aggregate_ingredients, dish_names, format_daily_message
from app.models import Feedback, Household, MealPlan, MealPlanItem, Recipe
from app.web import mock

init_db()

app = FastAPI(title="Caspian Meal Planner - Preview")
templates = Jinja2Templates(directory="app/web/templates")
app.mount("/static", StaticFiles(directory="app/web/static"), name="static")

LIVE_MODE = bool(ANTHROPIC_API_KEY)


def _this_monday(today=None) -> dt.date:
    today = today or dt.date.today()
    return today - dt.timedelta(days=today.weekday())


def _split(s: str):
    return [x.strip() for x in s.split(",") if x.strip()]


def generate_week(household_id: int, week_start: dt.date) -> int:
    if LIVE_MODE:
        return claude_generator.generate_weekly_plan(household_id, week_start)
    return mock.mock_generate_weekly_plan(household_id, week_start)


def generate_month(household_id: int, month_start: dt.date) -> list:
    if LIVE_MODE:
        return claude_generator.generate_monthly_plan(household_id, month_start)
    return mock.mock_generate_monthly_plan(household_id, month_start)


def interpret_feedback(text: str, todays_recipe_ids: list) -> dict:
    if LIVE_MODE:
        return claude_generator.interpret_cook_reply(text, todays_recipe_ids)
    return mock.mock_interpret_feedback(text, todays_recipe_ids)


@app.get("/")
def index(request: Request):
    session = get_session()
    try:
        households = session.query(Household).order_by(Household.id).all()
        return templates.TemplateResponse(
            request, "index.html", {"households": households, "live_mode": LIVE_MODE}
        )
    finally:
        session.close()


@app.get("/households/new")
def new_household_form(request: Request):
    return templates.TemplateResponse(request, "new_household.html", {"live_mode": LIVE_MODE})


@app.post("/households/new")
def create_household(
    name: str = Form(...),
    cook_name: str = Form(...),
    cook_phone: str = Form(...),
    diet_type: str = Form("veg"),
    family_size: int = Form(4),
    kids_count: int = Form(0),
    spice_level: str = Form("medium"),
    allergies: str = Form(""),
    disliked_ingredients: str = Form(""),
    preferred_cuisines: str = Form(""),
    notes: str = Form(""),
):
    session = get_session()
    try:
        household = Household(
            name=name,
            cook_name=cook_name,
            cook_phone=cook_phone,
            diet_type=diet_type,
            family_size=family_size,
            kids_count=kids_count,
            spice_level=spice_level,
            allergies=_split(allergies),
            disliked_ingredients=_split(disliked_ingredients),
            preferred_cuisines=_split(preferred_cuisines),
            notes=notes,
        )
        session.add(household)
        session.commit()
        return RedirectResponse(f"/family/{household.id}", status_code=303)
    finally:
        session.close()


@app.get("/family/{household_id}")
def family_dashboard(request: Request, household_id: int):
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household is None:
            return RedirectResponse("/", status_code=303)

        plan = (
            session.query(MealPlan)
            .filter(MealPlan.household_id == household_id, MealPlan.period_type == "week")
            .order_by(MealPlan.period_start.desc())
            .first()
        )
        recipe_cache = {r.id: r for r in session.query(Recipe).all()}

        week_days = []
        if plan:
            items = session.query(MealPlanItem).filter(MealPlanItem.meal_plan_id == plan.id).all()
            by_date = {}
            for it in items:
                by_date.setdefault(it.date, {})[it.meal_slot] = it
            for offset in range(7):
                date = plan.period_start + dt.timedelta(days=offset)
                slots = by_date.get(date, {})
                week_days.append(
                    {
                        "date": date,
                        "is_today": date == dt.date.today(),
                        "slots": {
                            slot: dish_names(slots[slot].dish_recipe_ids, recipe_cache)
                            for slot in MEAL_SLOTS
                            if slot in slots
                        },
                    }
                )

        return templates.TemplateResponse(
            request,
            "family.html",
            {
                "household": household,
                "plan": plan,
                "week_days": week_days,
                "meal_slots": MEAL_SLOTS,
                "live_mode": LIVE_MODE,
            },
        )
    finally:
        session.close()


@app.post("/family/{household_id}/edit")
def edit_household(
    household_id: int,
    name: str = Form(...),
    cook_name: str = Form(...),
    cook_phone: str = Form(...),
    diet_type: str = Form("veg"),
    family_size: int = Form(4),
    kids_count: int = Form(0),
    spice_level: str = Form("medium"),
    allergies: str = Form(""),
    disliked_ingredients: str = Form(""),
    preferred_cuisines: str = Form(""),
    notes: str = Form(""),
):
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household:
            household.name = name
            household.cook_name = cook_name
            household.cook_phone = cook_phone
            household.diet_type = diet_type
            household.family_size = family_size
            household.kids_count = kids_count
            household.spice_level = spice_level
            household.allergies = _split(allergies)
            household.disliked_ingredients = _split(disliked_ingredients)
            household.preferred_cuisines = _split(preferred_cuisines)
            household.notes = notes
            session.commit()
        return RedirectResponse(f"/family/{household_id}", status_code=303)
    finally:
        session.close()


@app.post("/family/{household_id}/generate-week")
def do_generate_week(household_id: int):
    generate_week(household_id, _this_monday())
    return RedirectResponse(f"/family/{household_id}", status_code=303)


@app.get("/family/{household_id}/month")
def month_view(request: Request, household_id: int):
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household is None:
            return RedirectResponse("/", status_code=303)
        month_start = _this_monday()
        shopping_list = claude_generator.monthly_shopping_list(household_id, month_start)
        return templates.TemplateResponse(
            request,
            "month.html",
            {
                "household": household,
                "month_start": month_start,
                "shopping_list": shopping_list,
                "live_mode": LIVE_MODE,
            },
        )
    finally:
        session.close()


@app.post("/family/{household_id}/generate-month")
def do_generate_month(household_id: int):
    generate_month(household_id, _this_monday())
    return RedirectResponse(f"/family/{household_id}/month", status_code=303)


@app.get("/cook/{household_id}")
def cook_dashboard(request: Request, household_id: int):
    session = get_session()
    try:
        household = session.get(Household, household_id)
        if household is None:
            return RedirectResponse("/", status_code=303)

        today = dt.date.today()
        items = (
            session.query(MealPlanItem)
            .filter(MealPlanItem.household_id == household_id, MealPlanItem.date == today)
            .all()
        )
        recipe_cache = {r.id: r for r in session.query(Recipe).all()}
        slot_items = {it.meal_slot: it for it in items}

        message_preview = format_daily_message(household, today, slot_items, recipe_cache) if items else None

        meal_cards = [
            {
                "slot": slot,
                "names": dish_names(slot_items[slot].dish_recipe_ids, recipe_cache),
                "ingredients": aggregate_ingredients(
                    slot_items[slot].dish_recipe_ids, slot_items[slot].portion_servings, recipe_cache
                ),
                "servings": slot_items[slot].portion_servings,
                "note": slot_items[slot].note,
            }
            for slot in MEAL_SLOTS
            if slot in slot_items
        ]

        recent_feedback = (
            session.query(Feedback)
            .filter(Feedback.household_id == household_id)
            .order_by(Feedback.created_at.desc())
            .limit(10)
            .all()
        )

        return templates.TemplateResponse(
            request,
            "cook.html",
            {
                "household": household,
                "today": today,
                "meal_cards": meal_cards,
                "message_preview": message_preview,
                "recent_feedback": recent_feedback,
                "live_mode": LIVE_MODE,
            },
        )
    finally:
        session.close()


@app.post("/cook/{household_id}/feedback")
def submit_feedback(household_id: int, message_text: str = Form(...)):
    session = get_session()
    try:
        today = dt.date.today()
        items = (
            session.query(MealPlanItem)
            .filter(MealPlanItem.household_id == household_id, MealPlanItem.date == today)
            .all()
        )
        todays_recipe_ids = [rid for it in items for rid in (it.dish_recipe_ids or [])]
        intent = interpret_feedback(message_text, todays_recipe_ids)

        session.add(
            Feedback(
                household_id=household_id,
                conversation_id="web-preview",
                raw_text=message_text,
                parsed_intent=intent,
            )
        )
        session.commit()
        return RedirectResponse(f"/cook/{household_id}", status_code=303)
    finally:
        session.close()
