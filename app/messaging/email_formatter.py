"""Builds the Monday email to the family: the whole week's chart, plus a few
new dishes they could add to it.

Two renderings of the same content, because the two send paths differ in what
they accept (see app/messaging/handler.py::send_owner_email):

- `weekly_email_blocks()` - provider-neutral blocks, which Caspian renders as
  real HTML on email. Only usable via send_message(), i.e. once the family has
  replied once and we know their conversation_id.
- `weekly_email_text()` - plain text, for the cold-start initiate() path.
  initiate() takes `text` and nothing else in caspian-sdk 0.6.4, so the very
  first email a family gets is necessarily plain.

Unlike the cook's daily SMS (app/messaging/formatter.py, ASCII-only to keep
GSM-7 segment costs down), email has no per-character billing - so this one
uses normal punctuation and full ingredient detail.

Note on subject lines: the SDK exposes `subject` on *inbound* Message only;
neither send_message() nor initiate() accepts one, so Caspian derives it. The
first line of both renderings is therefore written to stand on its own as the
opening line of the mail.
"""

import datetime as dt

from caspian_sdk import blocks as b

from app.config import MEAL_SLOTS
from app.messaging.formatter import SLOT_LABELS, _fmt_qty, dish_names

SUGGESTION_SLOT_LABEL = {
    "breakfast": "breakfast",
    "lunch": "lunch",
    "snack": "a snack",
    "dinner": "dinner",
}


def _day_lines(date: dt.date, slot_items: dict, recipe_cache: dict) -> list:
    """One day of the chart as ["LUNCH: dal + rice", ...] - dish names only.
    Ingredient lists are the cook's daily message's job; a week of them in one
    email is unreadable, and the family gets the shopping list separately."""
    lines = []
    for slot in MEAL_SLOTS:
        item = slot_items.get(slot)
        if item is None:
            continue
        line = f"{SLOT_LABELS.get(slot, slot.upper())}: {dish_names(item.dish_recipe_ids, recipe_cache)}"
        if item.note:
            line += f" ({item.note})"
        lines.append(line)
    return lines


def _suggestion_line(recipe) -> str:
    slots = [SUGGESTION_SLOT_LABEL.get(s, s) for s in (recipe.meal_types or [])]
    slot_text = " or ".join(slots) if slots else "any meal"
    region = recipe.cuisine_style or recipe.region or "Indian"
    return f"{recipe.name} - {region}, good for {slot_text}, about {recipe.prep_time_min} min"


def _shopping_line(entry: dict) -> str:
    return f"{entry['item']} {_fmt_qty(entry['qty'])} {entry['unit']}"


def weekly_email_text(
    household,
    week_start: dt.date,
    days: list,
    recipe_cache: dict,
    suggestions: list,
    shopping_list: list = None,
) -> str:
    """`days`: [(date, {slot: MealPlanItem}), ...] in date order."""
    week_end = week_start + dt.timedelta(days=6)
    out = [
        f"{household.name} household - meal chart for {week_start.strftime('%d %b')} "
        f"to {week_end.strftime('%d %b %Y')}",
        "",
        f"Here's the full week for {household.cook_name} to cook, "
        f"portioned for {household.family_size}.",
        "",
    ]

    for date, slot_items in days:
        lines = _day_lines(date, slot_items, recipe_cache)
        out.append(date.strftime("%A %d %b"))
        if lines:
            out.extend(f"  {line}" for line in lines)
        else:
            out.append("  (nothing planned yet)")
        out.append("")

    if suggestions:
        out.append("NEW THIS WEEK - dishes you could add:")
        out.extend(f"  - {_suggestion_line(r)}" for r in suggestions)
        out.append("")
        out.append("Open the app to add any of these to a day.")
        out.append("")

    if shopping_list:
        out.append("SHOPPING LIST FOR THE WEEK:")
        out.append("  " + ", ".join(_shopping_line(i) for i in shopping_list))
        out.append("")

    out.append("Reply to this email to change anything - it reaches the planner directly.")
    return "\n".join(out).rstrip() + "\n"


def weekly_email_blocks(
    household,
    week_start: dt.date,
    days: list,
    recipe_cache: dict,
    suggestions: list,
    shopping_list: list = None,
) -> list:
    """Same content as weekly_email_text(), as blocks Caspian renders into
    HTML on email (and degrades to clean text anywhere else)."""
    week_end = week_start + dt.timedelta(days=6)
    out = [
        b.heading(
            f"{household.name} - meal chart for {week_start.strftime('%d %b')} "
            f"to {week_end.strftime('%d %b %Y')}"
        ),
        b.text(
            f"Here's the full week for {household.cook_name} to cook, "
            f"portioned for {household.family_size}."
        ),
        b.divider(),
    ]

    for date, slot_items in days:
        out.append(b.heading(date.strftime("%A %d %b")))
        lines = _day_lines(date, slot_items, recipe_cache)
        out.append(b.bullet_list(lines) if lines else b.text("Nothing planned yet."))

    if suggestions:
        out.append(b.divider())
        out.append(b.heading("New this week - dishes you could add"))
        out.append(b.bullet_list([_suggestion_line(r) for r in suggestions]))
        out.append(b.text("Open the app to add any of these to a day."))

    if shopping_list:
        out.append(b.divider())
        out.append(b.heading("Shopping list for the week"))
        out.append(b.bullet_list([_shopping_line(i) for i in shopping_list]))

    out.append(b.divider())
    out.append(b.text("Reply to this email to change anything - it reaches the planner directly."))
    return out


def weekly_shopping_list(days: list, recipe_cache: dict) -> list:
    """Every ingredient across the week, scaled to the household's portions
    and merged - the same aggregation monthly_shopping_list() does, over the
    seven days already loaded for the email rather than a fresh DB pass."""
    totals = {}
    order = []
    for _date, slot_items in days:
        for item in slot_items.values():
            for rid in item.dish_recipe_ids or []:
                recipe = recipe_cache.get(rid)
                if not recipe:
                    continue
                for ing in recipe.ingredients or []:
                    key = (ing["item"], ing["unit"])
                    if key not in totals:
                        totals[key] = 0.0
                        order.append(key)
                    totals[key] += ing["qty"] * item.portion_servings
    return [{"item": i, "qty": round(totals[(i, u)], 1), "unit": u} for i, u in sorted(order)]
