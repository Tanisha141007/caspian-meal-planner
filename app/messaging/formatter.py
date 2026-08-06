"""Turns a day's MealPlanItems into the plain-text message sent to the cook.
Kept to plain ASCII text (no markdown, no emoji) because the interim SMS
channel bills non-GSM-7 characters as extra segments - see Caspian's
SMS & phone docs. Swapping to WhatsApp later can loosen this formatting."""

import datetime as dt

from app.config import MEAL_SLOTS

SLOT_LABELS = {"breakfast": "BREAKFAST", "lunch": "LUNCH", "snack": "SNACK", "dinner": "DINNER"}


def _fmt_qty(qty: float) -> str:
    qty = round(qty, 1)
    return str(int(qty)) if qty == int(qty) else str(qty)


def dish_names(dish_recipe_ids, recipe_cache) -> str:
    names = [recipe_cache[rid].name for rid in dish_recipe_ids if rid in recipe_cache]
    return " + ".join(names) if names else "(recipe not found)"


def aggregate_ingredients(dish_recipe_ids, portion_servings, recipe_cache):
    """Sums ingredient quantities across every dish in a meal slot, scaled
    to the household's portion size, merging items that repeat across dishes
    (e.g. ghee used in both the dal and the rice)."""
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
    return [f"{item} {_fmt_qty(totals[(item, unit)])} {unit}" for item, unit in order]


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


def format_daily_message(household, date: dt.date, slot_items: dict, recipe_cache: dict) -> str:
    """slot_items: {meal_slot: MealPlanItem} for one household on one date."""
    header = f"{household.name} household - {date.strftime('%a %d %b')} meals for {household.cook_name}:"
    blocks = [
        format_meal_block(slot, slot_items[slot], recipe_cache)
        for slot in MEAL_SLOTS
        if slot in slot_items
    ]
    return header + "\n\n" + "\n\n".join(blocks)
