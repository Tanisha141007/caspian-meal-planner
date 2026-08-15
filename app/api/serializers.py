"""Adapts backend SQLAlchemy objects to the shapes mealtime-harmony's
src/lib/recipes.ts and src/lib/planner.tsx already expect, so the frontend
needed minimal changes to go from local mock data to this API (see M1 in
the integration plan). Heuristic where the backend has no equivalent field
(`art`) - same "approximate, not exact" spirit as the Phase 1 ingestion."""

DIET_BACKEND_TO_FRONTEND = {"veg": "veg", "vegan": "vegan", "egg": "egg", "non-veg": "nonveg"}
CATEGORY_BACKEND_TO_FRONTEND = {
    "protein-heavy": "protein",
    "carb-heavy": "carb",
    "vegetable-based": "vegetable",
    "mixed": "mixed",
}
SEASON_BACKEND_TO_FRONTEND = {"all-season": "all", "summer": "summer", "monsoon": "monsoon", "winter": "winter"}

# Reverse of the above - app/api/routers/recipes.py's query params
# (?category=protein, ?season=summer) use the same frontend vocabulary the
# serializer outputs, not the raw DB enum, so filtering needs the inverse map.
CATEGORY_FRONTEND_TO_BACKEND = {v: k for k, v in CATEGORY_BACKEND_TO_FRONTEND.items()}
SEASON_FRONTEND_TO_BACKEND = {v: k for k, v in SEASON_BACKEND_TO_FRONTEND.items()}
DIET_FRONTEND_TO_BACKEND = {v: k for k, v in DIET_BACKEND_TO_FRONTEND.items()}

# cuisine_style slug -> a human-readable place name, since the frontend's
# Recipe.region is a display string ("Kerala", "Tamil Nadu") while the
# backend's Recipe.region is a coarse bucket (north/south/west/east/
# northeast/pan-india) - cuisine_style is the closer match.
CUISINE_DISPLAY_NAMES = {
    "pan-india": "Pan-India",
    "north-indian": "North India",
    "south-indian": "South India",
    "bengali": "West Bengal",
    "maharashtrian": "Maharashtra",
    "kerala": "Kerala",
    "tamil": "Tamil Nadu",
    "karnataka": "Karnataka",
    "rajasthani": "Rajasthan",
    "andhra": "Andhra Pradesh",
    "gujarati": "Gujarat",
    "goan": "Goa",
    "punjabi": "Punjab",
    "chettinad": "Tamil Nadu",
    "kashmiri": "Kashmir",
    "mangalorean": "Karnataka",
    "parsi": "Maharashtra",
    "awadhi": "Uttar Pradesh",
    "odia": "Odisha",
    "sindhi": "Gujarat",
    "konkani": "Maharashtra",
    "mughlai": "Uttar Pradesh",
    "bihari": "Bihar",
    "hyderabadi": "Telangana",
    "assamese": "Assam",
    "northeast": "North-East India",
    "himachali": "Himachal Pradesh",
}

_DOSA_HINTS = ("dosa", "idli", "appam", "uttapam", "dosai")
_THALI_HINTS = ("thali", "biryani", "pulao", "khichdi")
_CHAI_HINTS = ("chai", "tea", "coffee")


def _art_for(recipe) -> str:
    name = recipe.name.lower()
    if any(h in name for h in _DOSA_HINTS):
        return "dosa"
    if recipe.meal_types == ["snack"] or any(h in name for h in _CHAI_HINTS):
        return "chai"
    if any(h in name for h in _THALI_HINTS):
        return "thali"
    return "curry"


def serialize_recipe(recipe) -> dict:
    return {
        "id": recipe.id,
        "name": recipe.name,
        "region": CUISINE_DISPLAY_NAMES.get(recipe.cuisine_style, recipe.region or "Pan-India"),
        "slots": recipe.meal_types or [],
        "diet": DIET_BACKEND_TO_FRONTEND.get(recipe.diet, "veg"),
        "category": CATEGORY_BACKEND_TO_FRONTEND.get(recipe.main_ingredient_category, "mixed"),
        "season": SEASON_BACKEND_TO_FRONTEND.get((recipe.season_tags or ["all-season"])[0], "all"),
        "minutes": recipe.prep_time_min,
        "art": _art_for(recipe),
        # per-serving, same convention the frontend's mock data already used -
        # it multiplies by household size client-side (usePlanner().scaled()).
        "ingredients": [{"name": i["item"], "qty": i["qty"], "unit": i["unit"]} for i in (recipe.ingredients or [])],
    }


def serialize_household(household) -> dict:
    location = ", ".join(p for p in (household.city, household.state) if p)
    return {
        "id": household.id,
        "household": household.family_size,
        "location": location,
        "city": household.city or "",
        "state": household.state or "",
        "dietType": household.diet_type,
        "dislikes": household.disliked_ingredients or [],
        "allergies": household.allergies or [],
        "cuisines": household.preferred_cuisines or [],
        "cookName": household.cook_name,
        "cookPhone": household.cook_phone,
        "channel": household.preferred_channel,
        "leadHours": household.lead_hours,
        "notes": household.notes or "",
    }


def serialize_day_plan(date, items_by_slot: dict) -> dict:
    """Matches src/lib/planner.tsx's DayPlan: {date, meals: [{slot, recipeId}]}.
    A meal_slot backed by a dish *combo* (lunch/dinner: dal + rice + roti)
    collapses to the combo's first recipe_id for the frontend's single-
    recipe-per-slot card - see the `dishRecipeIds` passthrough below for the
    full combo, used when the frontend needs every dish, not just the hero one."""
    meals = []
    for slot, item in items_by_slot.items():
        ids = item.dish_recipe_ids or []
        if not ids:
            continue
        meals.append(
            {
                "slot": slot,
                "recipeId": ids[0],
                "dishRecipeIds": ids,
                "servings": item.portion_servings,
                "note": item.note,
            }
        )
    return {"date": str(date), "meals": meals}
