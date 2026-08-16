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


FEEDBACK_SYSTEM_PROMPT = """You read one inbound reply about a household's planned meals \
and turn it into structured intent. It may come from the family's cook (replying to a \
daily message on Telegram/SMS/WhatsApp) or from the family themselves (replying to their \
weekly meal-chart email) - the sender and channel are stated in the user message, and a \
cook's "couldn't get okra" is an ingredient_issue while a family's "we're bored of dal" \
is a dislike. Categorize into exactly one type: "dislike" (didn't like / don't repeat a \
dish), "swap_request" (wants a different dish instead, now or going forward), \
"ingredient_issue" (missing/can't get an ingredient), "confirmation" (acknowledging, no \
action needed), "question", or "other". If a specific recipe_id from the provided list is \
clearly referenced, include it; otherwise use null. Respond with ONLY valid JSON: \
{"type": "...", "recipe_id": "..." or null, "summary": "one short sentence"} - no prose, \
no markdown fences."""


def build_feedback_prompt(
    message_text, todays_recipe_ids, channel: str = "", sender_role: str = "cook", channel_guidance: str = ""
):
    """`channel_guidance` is Caspian's own per-channel etiquette text
    (client.behavior_prompt(), see app/messaging/handler.py) - appended rather
    than interpolated so an empty/unreachable gateway changes nothing."""
    system = FEEDBACK_SYSTEM_PROMPT
    if channel_guidance:
        system += "\n\nChannel etiquette for the channels this agent is connected to:\n" + channel_guidance

    sender = "the family's cook" if sender_role == "cook" else "the family (the household's own account)"
    channel_line = f" over {channel}" if channel else ""

    return system, (
        f"Today's planned recipe ids: {json.dumps(todays_recipe_ids)}\n\n"
        f'Message from {sender}{channel_line}: "{message_text}"'
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


ASK_AI_SYSTEM_PROMPT = """You read one free-text request from a household about their meal \
plan (the "Ask Caspian" box) and turn it into a short profile note plus a friendly reply. \
Distill the request into a single, concrete, reusable instruction for future meal planning \
(e.g. "more high-protein breakfasts", "no repeated dals more than once a week", "prefer \
millet-based dishes") - specific enough that a planner reading it later knows what changed. \
If the request isn't a genuine planning preference (off-topic, a question, nonsense), leave \
notes_append empty and say so in the reply. Never contradict or override the household's \
existing hard constraints (diet type, allergies) - those aren't something this box can change. \
Respond with ONLY valid JSON: {"reply": "one short sentence back to the household", \
"notes_append": "the distilled instruction, or \\"\\" if nothing to add"} - no prose, no \
markdown fences."""


def build_ask_ai_prompt(household, message_text):
    household_profile = _household_profile_dict(household)
    return ASK_AI_SYSTEM_PROMPT, (
        f"Household profile:\n{json.dumps(household_profile, indent=2)}\n\n"
        f'Household\'s request: "{message_text}"'
    )
