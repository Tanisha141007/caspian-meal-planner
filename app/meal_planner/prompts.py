"""Prompt templates for the meal-plan generator. The recipe universe (name,
region, diet, ingredients) IS the training/context data referenced in the
project brief: there's no fine-tuning here, it's retrieval + a structured
household profile fed to Claude as context on every generation call."""

import datetime as dt
import json

PLAN_SYSTEM_PROMPT = """You are a meal-planning assistant for Indian households, \
writing charts that a family cook will actually execute. You only ever pick dishes \
from the candidate recipe list given to you - never invent a dish. Follow standard \
Indian meal structure (e.g. lunch/dinner = one dal or curry + a rice or roti base, \
optionally a second sabzi; breakfast is a single dish; snack is a single light item). \
Respect the household's diet type, allergies, dislikes and spice level exactly - \
these are hard constraints, not preferences. Avoid repeating a dish that was served \
in the last 14 days unless the candidate list is too short to avoid it. Vary region/\
cuisine across the week rather than repeating the same cuisine style every day. \
Respond with ONLY valid JSON matching the schema you're given - no prose, no markdown \
fences."""


def _household_profile_dict(household):
    return {
        "family_size": household.family_size,
        "kids_count": household.kids_count,
        "diet_type": household.diet_type,
        "allergies": household.allergies or [],
        "disliked_ingredients": household.disliked_ingredients or [],
        "preferred_cuisines": household.preferred_cuisines or [],
        "spice_level": household.spice_level,
        "free_text_notes": household.notes or "",
    }


def _candidate_list_json(candidates):
    return [
        {
            "id": r.id,
            "name": r.name,
            "meal_types": r.meal_types,
            "diet": r.diet,
            "region": r.region,
            "cuisine_style": r.cuisine_style,
            "spice_level": r.spice_level,
            "tags": r.tags,
        }
        for r in candidates
    ]


def build_plan_prompt(household, candidates, recent_ids, start_date, num_days, meal_slots):
    household_profile = _household_profile_dict(household)
    candidate_list = _candidate_list_json(candidates)
    dates = [str(start_date + dt.timedelta(days=i)) for i in range(num_days)]

    schema_hint = {
        "days": [
            {
                "date": "YYYY-MM-DD",
                "meals": {
                    slot: {"recipe_ids": ["<id from candidates>", "..."], "note": "short note or empty string"}
                    for slot in meal_slots
                },
            }
        ]
    }

    user_prompt = f"""Household profile:
{json.dumps(household_profile, indent=2)}

Candidate recipes (pick recipe_ids ONLY from this list):
{json.dumps(candidate_list, indent=2)}

Dishes served in the last 14 days (avoid repeating unless necessary):
{json.dumps(recent_ids)}

Generate a meal chart for these {num_days} dates: {json.dumps(dates)}
Meal slots to fill each day: {json.dumps(meal_slots)}

For "lunch" and "dinner", recipe_ids should usually be a combo of 2-3 dish ids \
(e.g. one dal/curry + one rice or roti). For "breakfast" and "snack", use a single \
recipe_id. Use the "note" field for anything the cook should know (e.g. "extra mild \
for the kids today", "no onion - fasting day") - leave it "" when there's nothing to add.

Return JSON matching exactly this shape:
{json.dumps(schema_hint, indent=2)}
"""
    return PLAN_SYSTEM_PROMPT, user_prompt


FEEDBACK_SYSTEM_PROMPT = """You read one WhatsApp/SMS reply from a family's cook about \
today's planned meals and turn it into structured intent. Categorize into exactly one \
type: "dislike" (didn't like / don't repeat a dish), "swap_request" (wants a different \
dish instead, now or going forward), "ingredient_issue" (missing/can't get an ingredient), \
"confirmation" (acknowledging, no action needed), "question", or "other". If a specific \
recipe_id from the provided list is clearly referenced, include it; otherwise use null. \
Respond with ONLY valid JSON: {"type": "...", "recipe_id": "..." or null, "summary": "one \
short sentence"} - no prose, no markdown fences."""


def build_feedback_prompt(message_text, todays_recipe_ids):
    return FEEDBACK_SYSTEM_PROMPT, (
        f"Today's planned recipe ids: {json.dumps(todays_recipe_ids)}\n\n"
        f'Cook\'s message: "{message_text}"'
    )


SWAP_SYSTEM_PROMPT = """You are replacing ONE meal slot in an already-planned week for an \
Indian household, without touching the rest of the week. Pick only from the candidate \
recipes given - never invent a dish. Follow standard Indian meal structure (lunch/dinner = \
one dal or curry + a rice or roti base, optionally a second sabzi; breakfast and snack are \
a single dish). Respect diet type, allergies, dislikes and spice level exactly - hard \
constraints, not preferences. Respond with ONLY valid JSON matching the schema you're \
given - no prose, no markdown fences."""


def build_swap_prompt(household, candidates, slot, hint=""):
    household_profile = _household_profile_dict(household)
    candidate_list = _candidate_list_json(candidates)
    schema_hint = {"recipe_ids": ["<id from candidates>", "..."], "note": "short note or empty string"}

    hint_line = f'\nExtra request from the household for this swap: "{hint}"\n' if hint else ""

    user_prompt = f"""Household profile:
{json.dumps(household_profile, indent=2)}

Candidate recipes for the "{slot}" slot (pick recipe_ids ONLY from this list - all \
of these are already excluded from repeating anything else in this week's plan):
{json.dumps(candidate_list, indent=2)}
{hint_line}
Pick a replacement for this "{slot}" slot. For "lunch"/"dinner" use a combo of 2-3 \
recipe_ids (one dal/curry + one rice or roti); for "breakfast"/"snack" use a single \
recipe_id. Use "note" for anything the cook should know, "" if nothing to add.

Return JSON matching exactly this shape:
{json.dumps(schema_hint, indent=2)}
"""
    return SWAP_SYSTEM_PROMPT, user_prompt
