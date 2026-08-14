"""Parses the Kaggle "Indian Food Dataset" CSV (RecipeName, Ingredients,
Servings, Cuisine, Course, Diet, Prep/Cook time - see
https://www.kaggle.com/datasets/kanishk307/6000-indian-food-recipes-dataset)
into Recipe rows matching app/models.py.

This is heuristic, not exact - free-text ingredient parsing and diet/course
inference from a messy real-world dataset can't be perfect. Where a choice
has a food-safety angle (diet type, allergens) we bias toward the safer/more
restrictive answer rather than guessing generously. See
scripts/ingest_recipes.py for the parse-failure/skip report this produces.
"""

import re
from fractions import Fraction

# --- Cuisine -> (cuisine_style, region) -------------------------------------
# Only rows whose Cuisine maps here are kept; everything else (Continental,
# Italian, Fusion, Asian, ... and a handful of Course/Diet values that leaked
# into the Cuisine column) is dropped - this app is Indian regional food only.
CUISINE_MAP = {
    "indian": ("pan-india", "pan-india"),
    "north indian recipes": ("north-indian", "north"),
    "south indian recipes": ("south-indian", "south"),
    "bengali recipes": ("bengali", "east"),
    "maharashtrian recipes": ("maharashtrian", "west"),
    "kerala recipes": ("kerala", "south"),
    "tamil nadu": ("tamil", "south"),
    "karnataka": ("karnataka", "south"),
    "rajasthani": ("rajasthani", "west"),
    "andhra": ("andhra", "south"),
    "gujarati recipes": ("gujarati", "west"),
    "goan recipes": ("goan", "west"),
    "punjabi": ("punjabi", "north"),
    "chettinad": ("chettinad", "south"),
    "kashmiri": ("kashmiri", "north"),
    "mangalorean": ("mangalorean", "south"),
    "parsi recipes": ("parsi", "west"),
    "awadhi": ("awadhi", "north"),
    "oriya recipes": ("odia", "east"),
    "sindhi": ("sindhi", "west"),
    "konkan": ("konkani", "west"),
    "mughlai": ("mughlai", "north"),
    "bihari": ("bihari", "east"),
    "hyderabadi": ("hyderabadi", "south"),
    "assamese": ("assamese", "northeast"),
    "north east india recipes": ("northeast", "northeast"),
    "himachal": ("himachali", "north"),
    "udupi": ("karnataka", "south"),
    "coorg": ("karnataka", "south"),
    "coastal karnataka": ("karnataka", "south"),
    "north karnataka": ("karnataka", "south"),
    "south karnataka": ("karnataka", "south"),
    "uttar pradesh": ("north-indian", "north"),
    "lucknowi": ("awadhi", "north"),
    "malabar": ("kerala", "south"),
    "malvani": ("konkani", "west"),
    "uttarakhand-north kumaon": ("north-indian", "north"),
    "haryana": ("punjabi", "north"),
    "kongunadu": ("tamil", "south"),
    "jharkhand": ("bihari", "east"),
    "nagaland": ("northeast", "northeast"),
}

COURSE_MEAL_TYPES = {
    "lunch": ["lunch"],
    "dinner": ["dinner"],
    "main course": ["lunch", "dinner"],
    "side dish": ["lunch", "dinner"],
    "one pot dish": ["lunch", "dinner"],
    "snack": ["snack"],
    "appetizer": ["snack"],
    "dessert": ["snack"],
    "brunch": ["breakfast"],
    "south indian breakfast": ["breakfast"],
    "north indian breakfast": ["breakfast"],
    "world breakfast": ["breakfast"],
    "indian breakfast": ["breakfast"],
}
DEFAULT_MEAL_TYPES = ["lunch", "dinner"]  # fallback for leaked/unrecognized Course values

DIET_COLUMN_MAP = {
    "vegetarian": "veg",
    "high protein vegetarian": "veg",
    "diabetic friendly": "veg",
    "gluten free": "veg",
    "sugar free diet": "veg",
    "no onion no garlic (sattvic)": "veg",
    "vegan": "vegan",
    "eggetarian": "egg",
    "non vegeterian": "non-veg",
    "high protein non vegetarian": "non-veg",
}
DIET_EXTRA_TAGS = {
    "high protein vegetarian": ["high-protein"],
    "high protein non vegetarian": ["high-protein"],
    "diabetic friendly": ["diabetic-friendly"],
    "gluten free": ["gluten-free"],
    "sugar free diet": ["sugar-free"],
    "no onion no garlic (sattvic)": ["no-onion-garlic", "jain-friendly"],
}

NONVEG_KEYWORDS = {
    "chicken", "mutton", "lamb", "pork", "beef", "fish", "prawn", "shrimp",
    "crab", "goat", "bacon", "ham", "squid", "oyster", "anchovy", "meat",
    "keema", "sausage", "salami",
}
EGG_KEYWORDS = {"egg", "eggs"}
DAIRY_KEYWORDS = {"milk", "ghee", "paneer", "curd", "yogurt", "yoghurt", "cream", "butter", "cheese", "honey"}

PROTEIN_KEYWORDS = NONVEG_KEYWORDS | EGG_KEYWORDS | {
    "paneer", "tofu", "dal", "lentil", "chana", "rajma", "moong", "urad",
    "soya", "chickpea", "beans", "sprouts",
}
CARB_KEYWORDS = {
    "rice", "wheat", "flour", "potato", "roti", "bread", "pasta", "noodle",
    "poha", "dalia", "daliya", "oats", "maida", "corn", "vermicelli", "sooji",
    "rava", "semolina",
}
VEG_KEYWORDS = {
    "onion", "tomato", "spinach", "palak", "cauliflower", "gobi", "brinjal",
    "baingan", "okra", "bhindi", "carrot", "beans", "peas", "cabbage",
    "capsicum", "pumpkin", "gourd", "drumstick", "beetroot", "radish",
    "cucumber", "mushroom", "greens", "methi", "spring onion",
}

STAPLE_NAME_HINTS = {
    "rice", "roti", "chapati", "naan", "paratha", "phulka", "poori", "puri",
    "idli", "dosa", "pulao", "biryani",
}

UNIT_WORDS = {
    "cups": "cup", "cup": "cup",
    "tablespoons": "tbsp", "tablespoon": "tbsp", "tbsp": "tbsp", "tbsps": "tbsp",
    "teaspoons": "tsp", "teaspoon": "tsp", "tsp": "tsp", "tsps": "tsp",
    "grams": "g", "gram": "g", "gms": "g", "gm": "g", "g": "g",
    "kilograms": "kg", "kilogram": "kg", "kgs": "kg", "kg": "kg",
    "millilitres": "ml", "milliliters": "ml", "ml": "ml",
    "litres": "l", "liters": "l", "litre": "l", "liter": "l", "l": "l",
    "cloves": "pc", "clove": "pc",
    "inches": "pc", "inch": "pc",
    "pieces": "pc", "piece": "pc", "pcs": "pc", "pc": "pc",
    "whole": "pc",
    "bunches": "pc", "bunch": "pc",
    "sprigs": "pc", "sprig": "pc",
    "leaves": "pc", "leaf": "pc",
    "slices": "pc", "slice": "pc",
    "pinches": "pc", "pinch": "pc",
    "handfuls": "pc", "handful": "pc",
    "stalks": "pc", "stalk": "pc",
}
# Sorted longest-first so multi-word/longer alternatives win before a short
# one (e.g. "cups" before "cup"); \b...\b keeps single-letter units like "g"
# from matching mid-word ("Green", "Ghee", "Ginger" all start with 'g').
UNIT_PATTERN = r"\b(?:" + "|".join(sorted(UNIT_WORDS, key=len, reverse=True)) + r")\b"

# Ordered most-specific-first: regex alternation takes the first alternative
# that matches at the current position, not the longest overall match, so a
# short pattern earlier would truncate a longer one (e.g. bare \d+ matching
# just "1" out of "1 1/2" if it came first).
NUMBER_PATTERN = (
    r"\d+\s+\d+\s*/\s*\d+"  # mixed, space-separated: "1 1/2"
    r"|\d+\s*-\s*\d+\s*/\s*\d+"  # mixed, dash-separated: "1-1/4"
    r"|\d+\s*-\s*\d+"  # a range: "6-7" (averaged)
    r"|\d+\s*/\s*\d+"  # simple fraction: "1/2"
    r"|\d+\.\d+"  # decimal: "2.5"
    r"|\d+"  # integer: "3"
)
INGREDIENT_LINE_RE = re.compile(
    rf"^\s*(?P<qty>{NUMBER_PATTERN})?\s*(?P<unit>{UNIT_PATTERN})?\.?\s*(?P<item>.+?)\s*$",
    re.IGNORECASE,
)


def _parse_number(raw: str) -> float:
    """'1 1/2' -> 1.5, '1-1/4' -> 1.25, '6-7' -> 6.5 (range, averaged),
    '1 / 4' -> 0.25, '2.5' -> 2.5, '3' -> 3.0"""
    raw = raw.strip()

    match = re.match(r"^(\d+)\s+(\d+)\s*/\s*(\d+)$", raw)  # "1 1/2"
    if match:
        whole, num, den = match.groups()
        return float(whole) + float(num) / float(den)

    match = re.match(r"^(\d+)\s*-\s*(\d+)\s*/\s*(\d+)$", raw)  # "1-1/4"
    if match:
        whole, num, den = match.groups()
        return float(whole) + float(num) / float(den)

    match = re.match(r"^(\d+)\s*-\s*(\d+)$", raw)  # "6-7" range -> average
    if match:
        low, high = match.groups()
        return (float(low) + float(high)) / 2

    if "/" in raw:
        return float(Fraction(raw.replace(" ", "")))
    return float(raw)


def parse_ingredient_line(line: str, servings: float):
    """One free-text ingredient line -> {item, qty, unit}, qty already scaled
    to 1 serving. unit is one of g/ml/pc/cup/tbsp/tsp/"to taste"."""
    line = line.strip()
    if not line:
        return None

    # Drop a trailing " - <prep note>" (e.g. "- deseeded", "- to taste");
    # the note isn't structured data we keep, but "to taste" flips the unit.
    to_taste = False
    if " - " in line:
        left, note = line.split(" - ", 1)
        if "to taste" in note.lower() or "as required" in note.lower() or "as per taste" in note.lower():
            to_taste = True
        line = left.strip()

    match = INGREDIENT_LINE_RE.match(line)
    if not match:
        return None

    item = re.sub(r"^[-,.\s]+|[-,.\s]+$", "", match.group("item") or "").strip().lower()
    item = re.sub(r"\s+", " ", item)
    # A handful of source rows have malformed quantities (double slashes like
    # "1//4", stray digits) that our regex can't confidently split from the
    # item name - if digits/slashes are still stuck to the item, or there's
    # no letter at all, treat it as unparseable rather than ship "1//4 cups
    # sugar" as an ingredient name.
    if not item or re.match(r"^[\d/]", item) or not re.search(r"[a-z]", item):
        return None

    # No explicit number in the line (e.g. "Salt", "Oil for frying", "Ginger
    # - small piece") - "to taste"/unspecified is more honest than guessing
    # a fabricated quantity like "1 piece" for something that could be any
    # amount.
    if to_taste or not match.group("qty"):
        return {"item": item, "qty": 0.0, "unit": "to taste"}

    try:
        qty = _parse_number(match.group("qty"))
    except (ValueError, ZeroDivisionError):
        return None

    unit_raw = (match.group("unit") or "").lower()
    unit = UNIT_WORDS.get(unit_raw, "pc")
    if unit == "kg":
        qty *= 1000
        unit = "g"
    elif unit == "l":
        qty *= 1000
        unit = "ml"

    return {"item": item, "qty": round(qty / max(servings, 1), 3), "unit": unit}


def parse_ingredients(raw_text: str, servings: float):
    parsed, failed = [], 0
    for line in str(raw_text).split(","):
        result = parse_ingredient_line(line, servings)
        if result is None:
            failed += 1
        else:
            parsed.append(result)
    return parsed, failed


def is_mostly_ascii(text: str, threshold: float = 0.9) -> bool:
    """Filters out the (small) fraction of rows this dataset never
    translated out of Hindi/other scripts - the app targets English text."""
    text = str(text)
    if not text:
        return True
    ascii_count = sum(1 for c in text if ord(c) < 128)
    return (ascii_count / len(text)) >= threshold


def infer_diet(ingredient_items: list, diet_column: str):
    joined = " ".join(ingredient_items)
    words = set(joined.split())
    if NONVEG_KEYWORDS & words or any(kw in joined for kw in NONVEG_KEYWORDS):
        return "non-veg", []
    if EGG_KEYWORDS & words:
        return "egg", []

    diet_key = str(diet_column).strip().lower()
    tags = list(DIET_EXTRA_TAGS.get(diet_key, []))
    has_dairy = DAIRY_KEYWORDS & words or any(kw in joined for kw in DAIRY_KEYWORDS)
    if diet_key == "vegan":
        # Source data mislabels some dairy-containing dishes "Vegan" - a
        # false "veg" here is a minor inconvenience; a false "vegan" is a
        # diet-safety bug for a vegan household, so downgrade explicitly
        # rather than falling through to DIET_COLUMN_MAP (which would just
        # map "vegan" -> "vegan" again and silently undo this check).
        return ("veg" if has_dairy else "vegan"), tags
    return DIET_COLUMN_MAP.get(diet_key, "veg"), tags


def infer_meal_types(course_column: str):
    return COURSE_MEAL_TYPES.get(str(course_column).strip().lower(), list(DEFAULT_MEAL_TYPES))


def infer_main_ingredient_category(ingredient_items: list):
    joined = " ".join(ingredient_items)
    scores = {
        "protein-heavy": sum(1 for kw in PROTEIN_KEYWORDS if kw in joined),
        "carb-heavy": sum(1 for kw in CARB_KEYWORDS if kw in joined),
        "vegetable-based": sum(1 for kw in VEG_KEYWORDS if kw in joined),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "mixed"


def infer_spice_level(ingredient_items: list, course_column: str, cuisine_style: str):
    if str(course_column).strip().lower() == "dessert":
        return "mild"
    chilli_mentions = sum(1 for item in ingredient_items if "chilli" in item or "chili" in item or "pepper" in item)
    if chilli_mentions >= 2 or cuisine_style in {"andhra", "chettinad"}:
        return "hot"
    return "medium"


def is_staple(name: str) -> bool:
    """A simple starch base (rice/roti/dosa/...) the planner can pair with a
    main curry - matched by name only. Ingredient count isn't a reliable
    signal here (e.g. "Vegetable Pulao" has 6+ ingredients but is still a
    staple base, not a separate main dish)."""
    lowered = name.lower()
    return any(hint in lowered for hint in STAPLE_NAME_HINTS)


def slugify(name: str, existing: set) -> str:
    base = re.sub(r"\s+recipe\s*$", "", name.strip(), flags=re.IGNORECASE)
    base = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or "recipe"
    slug = base
    i = 2
    while slug in existing:
        slug = f"{base}_{i}"
        i += 1
    existing.add(slug)
    return slug


def clean_display_name(name: str) -> str:
    return re.sub(r"\s+recipe\s*$", "", name.strip(), flags=re.IGNORECASE) or name.strip()
