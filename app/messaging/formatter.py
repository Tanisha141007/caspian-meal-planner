"""Turns a day's MealPlanItems into the plain-text message sent to the cook.
Kept to plain ASCII text (no markdown, no emoji) because the interim SMS
channel bills non-GSM-7 characters as extra segments - see Caspian's
SMS & phone docs. Swapping to WhatsApp later can loosen this formatting."""

import datetime as dt
from html import escape

from app.config import MEAL_SLOTS

SLOT_LABELS = {"breakfast": "BREAKFAST", "lunch": "LUNCH", "snack": "SNACK", "dinner": "DINNER"}
SLOT_TITLES = {"breakfast": "Breakfast", "lunch": "Lunch", "snack": "Snack", "dinner": "Dinner"}
OWNER_TABLE_WIDTHS = {"day": 12, "breakfast": 28, "lunch": 32, "snack": 24, "dinner": 32}


def _fmt_qty(qty: float) -> str:
    qty = round(qty, 1)
    return str(int(qty)) if qty == int(qty) else str(qty)


def dish_names(dish_recipe_ids, recipe_cache) -> str:
    names = [recipe_cache[rid].name for rid in dish_recipe_ids if rid in recipe_cache]
    return " + ".join(names) if names else "(recipe not found)"


def aggregate_ingredients_structured(dish_recipe_ids, portion_servings, recipe_cache):
    """Sums ingredient quantities across every dish in a meal slot, scaled
    to the household's portion size, merging items that repeat across dishes
    (e.g. ghee used in both the dal and the rice). Structured {item, qty,
    unit} dicts - the one source of truth both the SMS/Telegram formatter
    below and app/api/serializers.py's embedded recipe data build on."""
    totals = {}
    order = []
    for rid in dish_recipe_ids:
        recipe = recipe_cache.get(rid)
        if not recipe:
            continue
        for ing in recipe.ingredients or []:
            key = (ing["item"], ing["unit"])
            if key not in totals:
                totals[key] = 0.0
                order.append(key)
            totals[key] += ing["qty"] * portion_servings
    return [{"item": item, "qty": round(totals[(item, unit)], 3), "unit": unit} for item, unit in order]


def aggregate_ingredients(dish_recipe_ids, portion_servings, recipe_cache):
    """Display-string form ("onion 240 g") for the cook-facing text message."""
    structured = aggregate_ingredients_structured(dish_recipe_ids, portion_servings, recipe_cache)
    return [f"{i['item']} {_fmt_qty(i['qty'])} {i['unit']}" for i in structured]


def format_meal_block(slot: str, item, recipe_cache) -> str:
    label = SLOT_LABELS.get(slot, slot.upper())
    names = dish_names(item.dish_recipe_ids, recipe_cache)
    ingredients = aggregate_ingredients(item.dish_recipe_ids, item.portion_servings, recipe_cache)

    lines = [f"{label} ({_fmt_qty(item.portion_servings)} servings): {names}"]
    if ingredients:
        lines.append("Ingredients: " + ", ".join(ingredients))
    if item.note:
        lines.append(f"Note: {item.note}")
    return "\n".join(lines)


def format_daily_message(household, date: dt.date, slot_items: dict, recipe_cache: dict, extra_message: str = "") -> str:
    """slot_items: {meal_slot: MealPlanItem} for one household on one date."""
    header = f"{household.name} household - {date.strftime('%a %d %b')} meals for {household.cook_name}:"
    blocks = [
        format_meal_block(slot, slot_items[slot], recipe_cache)
        for slot in MEAL_SLOTS
        if slot in slot_items
    ]
    if extra_message.strip():
        blocks.append("Note from family: " + extra_message.strip())
    return header + "\n\n" + "\n\n".join(blocks)


def format_weekly_owner_email_text(
    household,
    week_start: dt.date,
    week_items: list,
    recipe_cache: dict,
    suggestions: list,
) -> str:
    """Compact visible weekly summary for the signed-in household owner."""
    by_date = {}
    for item in week_items:
        by_date.setdefault(item.date, {})[item.meal_slot] = item

    def cell(value: str, width: int) -> str:
        value = " ".join((value or "").split())
        if len(value) > width:
            value = value[: width - 3].rstrip() + "..."
        return value.ljust(width)

    headers = [
        cell("Day", OWNER_TABLE_WIDTHS["day"]),
        *[cell(SLOT_TITLES[slot], OWNER_TABLE_WIDTHS[slot]) for slot in MEAL_SLOTS],
    ]
    separator = [
        "-" * OWNER_TABLE_WIDTHS["day"],
        *["-" * OWNER_TABLE_WIDTHS[slot] for slot in MEAL_SLOTS],
    ]

    lines = [
        f"Your ahaar meal plan for {week_start.strftime('%d %b')} - "
        f"{(week_start + dt.timedelta(days=6)).strftime('%d %b')}",
        "",
        f"Hi {household.name},",
        "",
        "Your meal plan for next week is ready:",
        "",
        " | ".join(headers),
        "-+-".join(separator),
    ]

    for offset in range(7):
        day = week_start + dt.timedelta(days=offset)
        slot_items = by_date.get(day, {})
        row = [cell(day.strftime("%a %d %b"), OWNER_TABLE_WIDTHS["day"])]
        for slot in MEAL_SLOTS:
            item = slot_items.get(slot)
            names = dish_names(item.dish_recipe_ids, recipe_cache) if item else ""
            row.append(cell(names, OWNER_TABLE_WIDTHS[slot]))
        lines.append(" | ".join(row))

    if suggestions:
        lines.extend(["", "New ideas from Discover:"])
        for recipe in suggestions:
            slots = "/".join(SLOT_TITLES.get(slot, slot.title()) for slot in (recipe.meal_types or []))
            slot_hint = f" ({slots})" if slots else ""
            lines.append(f"- {recipe.name}{slot_hint}, {recipe.prep_time_min} min")

    lines.extend(
        [
            "",
            f"{household.cook_name} will continue getting the daily cook-ready message separately.",
            "",
            "ahaar",
        ]
    )
    return "\n".join(lines)


def format_weekly_owner_email_html(
    household,
    week_start: dt.date,
    week_items: list,
    recipe_cache: dict,
    suggestions: list,
) -> str:
    """Compact HTML email using the ahaar app palette and table-first layout."""
    by_date = {}
    for item in week_items:
        by_date.setdefault(item.date, {})[item.meal_slot] = item

    rows = []
    for offset in range(7):
        day = week_start + dt.timedelta(days=offset)
        slot_items = by_date.get(day, {})
        cells = []
        for slot in MEAL_SLOTS:
            item = slot_items.get(slot)
            if not item:
                cells.append("<td></td>")
                continue
            note = f"<div class=\"note\">{escape(item.note)}</div>" if item.note else ""
            cells.append(
                "<td>"
                f"<strong>{escape(dish_names(item.dish_recipe_ids, recipe_cache))}</strong>"
                f"{note}"
                "</td>"
            )
        rows.append(
            "<tr>"
            f"<th><span>{day.strftime('%a')}</span><br>{day.strftime('%d %b')}</th>"
            + "".join(cells)
            + "</tr>"
        )

    suggestion_cards = []
    for recipe in suggestions:
        slots = " / ".join(SLOT_TITLES.get(slot, slot.title()) for slot in (recipe.meal_types or []))
        slot_line = f"<div>{escape(slots)}</div>" if slots else ""
        suggestion_cards.append(
            "<div class=\"suggestion\">"
            f"<strong>{escape(recipe.name)}</strong>"
            f"{slot_line}"
            f"<span>{recipe.prep_time_min} min</span>"
            "</div>"
        )

    date_range = f"{week_start.strftime('%d %b')} - {(week_start + dt.timedelta(days=6)).strftime('%d %b')}"
    return f"""<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body {{ margin: 0; background: #fbf7eb; color: #241f17; font-family: Arial, Helvetica, sans-serif; }}
      .wrap {{ max-width: 760px; margin: 0 auto; padding: 28px 14px; }}
      .card {{ background: #fffdf6; border: 1px solid #eadfc4; border-radius: 24px; overflow: hidden; }}
      .hero {{ background: #8cc220; color: #1f2a0c; padding: 24px; }}
      .brand {{ display: flex; align-items: center; gap: 10px; font-weight: 800; font-size: 24px; letter-spacing: 0; }}
      .mark {{ width: 44px; height: 44px; border-radius: 14px; background: #8cc220; display: inline-block; }}
      .hero h1 {{ margin: 18px 0 4px; font-size: 28px; line-height: 1.1; }}
      .hero p {{ margin: 0; font-size: 14px; font-weight: 700; }}
      .content {{ padding: 22px; }}
      table {{ width: 100%; border-collapse: separate; border-spacing: 0; overflow: hidden; border: 1px solid #eadfc4; border-radius: 18px; }}
      th, td {{ border-bottom: 1px solid #eadfc4; border-right: 1px solid #eadfc4; padding: 12px 10px; vertical-align: top; font-size: 13px; }}
      th {{ width: 78px; background: #f6eccf; text-align: left; color: #5c4a25; }}
      th span {{ font-size: 11px; text-transform: uppercase; }}
      td {{ background: #fffaf0; }}
      td strong {{ display: block; font-size: 13px; line-height: 1.25; }}
      tr:last-child th, tr:last-child td {{ border-bottom: 0; }}
      th:last-child, td:last-child {{ border-right: 0; }}
      .note {{ margin-top: 5px; color: #7a6846; font-size: 11px; }}
      h2 {{ margin: 24px 0 12px; font-size: 19px; }}
      .suggestions {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
      .suggestion {{ border: 1px solid #eadfc4; border-radius: 16px; background: #f6ffe8; padding: 12px; font-size: 13px; }}
      .suggestion strong {{ display: block; line-height: 1.25; }}
      .suggestion div {{ margin-top: 5px; color: #5f6f25; font-weight: 700; font-size: 11px; }}
      .suggestion span {{ display: inline-block; margin-top: 8px; border-radius: 999px; background: #fb9435; color: #2b1604; padding: 4px 8px; font-size: 11px; font-weight: 800; }}
      .footer {{ margin-top: 18px; color: #7a6846; font-size: 12px; }}
      @media (max-width: 620px) {{
        .content {{ padding: 14px; }}
        th, td {{ padding: 9px 7px; font-size: 12px; }}
        .suggestions {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <div class="hero">
          <div class="brand">
            <svg width="44" height="44" viewBox="0 0 64 64" role="img" aria-label="ahaar">
              <rect width="64" height="64" rx="14" fill="#8CC220"/>
              <path d="M14 34h36a18 18 0 0 1-36 0Z" fill="#FB9435"/>
              <path d="M35 12c4 4-4 6 0 10s-1 6-1 6" fill="none" stroke="#F5DC7A" stroke-width="4.5" stroke-linecap="round"/>
              <path d="M26 18c3 3-3 4.5 0 7.5s-.7 4.5-.7 4.5" fill="none" stroke="#F5DC7A" stroke-width="4" stroke-linecap="round"/>
            </svg>
            <span>ahaar</span>
          </div>
          <h1>Your weekly meal plan</h1>
          <p>{escape(date_range)} · {escape(str(household.family_size))} servings</p>
        </div>
        <div class="content">
          <table aria-label="Weekly meal plan">
            <thead>
              <tr>
                <th>Day</th>
                {"".join(f"<th>{escape(SLOT_TITLES[slot])}</th>" for slot in MEAL_SLOTS)}
              </tr>
            </thead>
            <tbody>
              {"".join(rows)}
            </tbody>
          </table>
          <h2>New ideas from Discover</h2>
          <div class="suggestions">{"".join(suggestion_cards)}</div>
          <p class="footer">{escape(household.cook_name)} will continue getting the daily cook-ready message separately.</p>
        </div>
      </div>
    </div>
  </body>
</html>"""


def format_weekly_owner_email(
    household,
    week_start: dt.date,
    week_items: list,
    recipe_cache: dict,
    suggestions: list,
) -> dict:
    subject = (
        f"Your ahaar meal plan for {week_start.strftime('%d %b')} - "
        f"{(week_start + dt.timedelta(days=6)).strftime('%d %b')}"
    )
    return {
        "subject": subject,
        "text": format_weekly_owner_email_text(household, week_start, week_items, recipe_cache, suggestions),
        "html": format_weekly_owner_email_html(household, week_start, week_items, recipe_cache, suggestions),
    }
