"""Estimates protein/carbs/fat/calories for a recipe from its ingredient
list, since neither the Kaggle-derived dataset (app/data/recipes_ingested.json)
nor anything else in this project has real nutrition data - it only has
names/ingredients/tags (see app/data/ingest.py). This is a keyword-matched
lookup against standard per-100g macro values for the ~150 ingredients that
cover the large majority of occurrences across the 4,262-recipe dataset
(checked by frequency), not a real nutrition database - close enough for a
"roughly how much protein is in this" badge on the Planner tab, not
suitable for medical/diabetic precision dosing.

Recipe.ingredients is already stored per-serving (see app/models.py), so
this computes a per-serving estimate directly with no DB migration or
seed-time precomputation needed - it's derived at serialize time from data
already on hand.
"""

# (keyword, protein_g, carbs_g, fat_g, kcal) per 100g of the ingredient as
# listed (raw/dry weight, the convention recipe ingredient lists use before
# cooking - not cooked-weight values). Checked against the dataset's most
# frequent ingredient strings; matched by substring, longest keyword first,
# so "coconut milk" matches before generic "coconut" does.
_MACROS_PER_100G: list[tuple[str, float, float, float, float]] = [
    # Oils / fats - ~0 protein/carbs, ~100% fat
    ("sunflower oil", 0, 0, 100, 884),
    ("mustard oil", 0, 0, 100, 884),
    ("coconut oil", 0, 0, 100, 862),
    ("sesame (gingelly) oil", 0, 0, 100, 884),
    ("gingelly oil", 0, 0, 100, 884),
    ("olive oil", 0, 0, 100, 884),
    ("vegetable oil", 0, 0, 100, 884),
    ("cooking oil", 0, 0, 100, 884),
    ("oil", 0, 0, 100, 884),
    ("ghee", 0, 0, 100, 900),
    ("butter (unsalted)", 0.9, 0.1, 81, 717),
    ("butter", 0.9, 0.1, 81, 717),
    # Dairy
    ("condensed milk", 7.9, 54, 8.7, 321),
    ("milk powder", 26, 38, 26, 496),
    ("hung curd (greek yogurt)", 10, 3.6, 0.4, 59),
    ("curd (dahi / yogurt)", 3.5, 4.7, 3.3, 61),
    ("curd", 3.5, 4.7, 3.3, 61),
    ("yogurt", 3.5, 4.7, 3.3, 61),
    ("milk", 3.4, 5, 3.6, 61),
    ("paneer (homemade cottage cheese)", 18, 1.2, 20, 265),
    ("paneer", 18, 1.2, 20, 265),
    ("cheese", 25, 1.3, 33, 402),
    ("fresh cream", 2.1, 2.8, 37, 340),
    ("cream", 2.1, 2.8, 37, 340),
    ("khoya (mawa)", 15, 25, 25, 421),
    ("khoya", 15, 25, 25, 421),
    ("tofu", 8, 1.9, 4.8, 76),
    # Grains / flours / starches
    ("basmati rice", 7, 78, 0.6, 345),
    ("idli rice", 7, 78, 0.6, 345),
    ("cooked rice", 7, 78, 0.6, 345),
    ("poha (flattened rice)", 6.9, 76, 1.2, 346),
    ("poha", 6.9, 76, 1.2, 346),
    ("rice flour", 6, 80, 1.4, 366),
    ("rice", 7, 78, 0.6, 345),
    ("whole wheat flour", 11, 72, 1.5, 340),
    ("wheat flour", 11, 72, 1.5, 340),
    ("all purpose flour (maida)", 10, 76, 1, 364),
    ("maida", 10, 76, 1, 364),
    ("gram flour (besan)", 22, 58, 6, 387),
    ("besan", 22, 58, 6, 387),
    ("sooji (semolina/ rava)", 13, 72, 1, 360),
    ("rava", 13, 72, 1, 360),
    ("semolina", 13, 72, 1, 360),
    ("ragi flour", 7.3, 72, 1.3, 336),
    ("jowar flour", 10, 73, 3.3, 349),
    ("bajra flour", 11.6, 67, 5, 361),
    ("instant oats (oatmeal)", 13, 68, 7, 389),
    ("oats", 13, 68, 7, 389),
    ("whole wheat bread crumbs", 9, 49, 3.2, 265),
    ("bread", 9, 49, 3.2, 265),
    ("corn flour", 7, 80, 0.9, 381),
    # Pulses / legumes (dry)
    ("arhar dal (split toor dal)", 22, 63, 1.5, 343),
    ("toor dal", 22, 63, 1.5, 343),
    ("yellow moong dal (split)", 24, 59, 1.2, 347),
    ("green moong dal (whole)", 24, 59, 1.2, 347),
    ("green moong sprouts", 3, 6, 0.2, 30),
    ("moong dal", 24, 59, 1.2, 347),
    ("moong", 24, 59, 1.2, 347),
    ("chana dal (bengal gram dal)", 19, 61, 6, 364),
    ("chana dal", 19, 61, 6, 364),
    ("kabuli chana (white chickpeas)", 19, 61, 6, 364),
    ("kala chana (brown chickpeas)", 19, 61, 6, 364),
    ("white urad dal (split)", 25, 59, 1.6, 341),
    ("white urad dal (whole)", 25, 59, 1.6, 341),
    ("black urad dal (split)", 25, 59, 1.6, 341),
    ("urad dal", 25, 59, 1.6, 341),
    ("masoor dal", 25, 60, 1.1, 352),
    ("rajma (large kidney beans)", 24, 60, 1, 333),
    ("rajma", 24, 60, 1, 333),
    ("horse gram dal (kollu/ kulith)", 22, 57, 0.5, 321),
    ("roasted gram dal (pottukadalai)", 20, 58, 5, 350),
    ("raw peanuts (moongphali)", 26, 16, 49, 567),
    ("roasted peanuts (moongphali)", 26, 16, 49, 567),
    ("peanuts", 26, 16, 49, 567),
    # Vegetables
    ("onion", 1.1, 9, 0.1, 40),
    ("homemade tomato puree", 0.9, 3.9, 0.2, 18),
    ("tomato puree", 0.9, 3.9, 0.2, 18),
    ("tomato", 0.9, 3.9, 0.2, 18),
    ("baby potatoes", 2, 17, 0.1, 77),
    ("potatoes (aloo)", 2, 17, 0.1, 77),
    ("potato (aloo)", 2, 17, 0.1, 77),
    ("potato", 2, 17, 0.1, 77),
    ("carrot (gajjar)", 0.9, 10, 0.2, 41),
    ("carrots", 0.9, 10, 0.2, 41),
    ("carrot", 0.9, 10, 0.2, 41),
    ("cauliflower (gobi)", 1.9, 5, 0.3, 25),
    ("cabbage (patta gobi/ muttaikose)", 1.3, 6, 0.1, 25),
    ("cabbage", 1.3, 6, 0.1, 25),
    ("spinach leaves (palak)", 2.9, 3.6, 0.4, 23),
    ("spinach", 2.9, 3.6, 0.4, 23),
    ("methi leaves (fenugreek leaves)", 4.4, 6, 0.9, 49),
    ("green bell pepper (capsicum)", 1, 6, 0.3, 20),
    ("red bell pepper (capsicum)", 1, 6, 0.3, 20),
    ("capsicum (green)", 1, 6, 0.3, 20),
    ("capsicum", 1, 6, 0.3, 20),
    ("cucumber", 0.7, 3.6, 0.1, 15),
    ("kaddu (parangikai/ pumpkin)", 1, 6.5, 0.1, 26),
    ("pumpkin", 1, 6.5, 0.1, 26),
    ("mooli/ mullangi (radish)", 0.7, 3.4, 0.1, 16),
    ("radish", 0.7, 3.4, 0.1, 16),
    ("small brinjal (baingan / eggplant)", 1, 6, 0.2, 25),
    ("brinjal (baingan / eggplant)", 1, 6, 0.2, 25),
    ("brinjal", 1, 6, 0.2, 25),
    ("green beans (french beans)", 1.8, 7, 0.2, 31),
    ("green peas (matar)", 5.4, 14, 0.4, 81),
    ("green peas", 5.4, 14, 0.4, 81),
    ("bhindi (lady finger/okra)", 1.9, 7.5, 0.2, 33),
    ("bottle gourd (lauki)", 0.6, 3.4, 0.1, 15),
    ("ridge gourd (turai/ peerkangai)", 0.5, 4.3, 0.1, 17),
    ("button mushrooms", 3.1, 3.3, 0.3, 22),
    ("mushroom", 3.1, 3.3, 0.3, 22),
    ("sweet corn", 3.2, 19, 1.2, 86),
    ("drumstick", 2.1, 8.5, 0.2, 37),
    ("beetroot", 1.6, 10, 0.2, 43),
    ("elephant yam (suran/senai/ratalu)", 1.5, 28, 0.2, 118),
    ("colocasia root (arbi)", 1.5, 26, 0.2, 112),
    ("raw banana", 1.3, 22, 0.1, 89),
    ("mango (raw)", 0.8, 15, 0.4, 60),
    ("mango (ripe)", 0.6, 15, 0.4, 60),
    ("celery", 0.7, 3, 0.2, 16),
    ("broccoli", 2.8, 7, 0.4, 34),
    ("green coriander", 3.3, 6.5, 0.7, 43),
    ("coriander (dhania) leaves", 3.3, 6.5, 0.7, 43),
    ("coriander leaves", 3.3, 6.5, 0.7, 43),
    ("mint leaves (pudina)", 3.8, 15, 0.7, 70),
    ("dill leaves", 3.5, 7, 1.1, 43),
    # Fruits / sweeteners
    ("dates", 2.5, 75, 0.4, 282),
    ("pineapple", 0.5, 13, 0.1, 50),
    ("fresh coconut", 3.3, 15, 33, 354),
    ("dessicated coconut", 3.3, 15, 33, 354),
    ("dry coconut (kopra)", 3.3, 15, 33, 354),
    ("coconut milk", 2.3, 3.3, 24, 230),
    ("coconut", 3.3, 15, 33, 354),
    ("raisins", 3.1, 79, 0.5, 299),
    ("jaggery", 0.4, 98, 0.1, 383),
    ("honey", 0.3, 82, 0, 304),
    ("caster sugar", 0, 100, 0, 387),
    ("sugar", 0, 100, 0, 387),
    ("lemon juice", 0.4, 3.2, 0.2, 15),
    ("lemon", 0.4, 3.2, 0.2, 15),
    # Nuts / seeds
    ("cashew nuts", 18, 30, 44, 553),
    ("cashews", 18, 30, 44, 553),
    ("badam (almond)", 21, 22, 50, 579),
    ("pistachios", 20, 28, 45, 560),
    ("sesame seeds (til seeds)", 18, 23, 50, 573),
    ("poppy seeds", 18, 28, 42, 525),
    ("mixed nuts", 20, 25, 48, 570),
    # Meat / egg / seafood
    ("boneless chicken", 27, 0, 3.6, 165),
    ("chicken breasts", 27, 0, 3.6, 165),
    ("chicken breast", 27, 0, 3.6, 165),
    ("chicken", 27, 0, 3.6, 165),
    ("mutton", 25, 0, 21, 294),
    ("eggs", 13, 1.1, 11, 155),
    ("egg", 13, 1.1, 11, 155),
    ("prawns", 24, 0.2, 0.3, 99),
    ("fish", 22, 0, 5, 140),
    # Aromatics / condiments (small quantities in most recipes, but priced
    # for completeness rather than zeroed out)
    ("ginger garlic paste", 3, 25, 0.6, 115),
    ("garlic", 6.4, 33, 0.5, 149),
    ("ginger", 1.8, 18, 0.8, 80),
    ("green chillies", 2, 7, 0.4, 40),
    ("green chilli", 2, 7, 0.4, 40),
    ("green chili", 2, 7, 0.4, 40),
    ("dry red chillies", 2, 7, 0.4, 40),
    ("dry red chilli", 2, 7, 0.4, 40),
    ("red chilli flakes", 2, 7, 0.4, 40),
    ("tamarind paste", 2.8, 63, 0.6, 239),
    ("tamarind water", 2.8, 63, 0.6, 239),
    ("tamarind", 2.8, 63, 0.6, 239),
    ("kokum (malabar tamarind)", 2.8, 63, 0.6, 239),
    ("green chutney (coriander & mint)", 2, 20, 3, 120),
    ("sweet chutney (date & tamarind)", 2, 20, 3, 120),
    ("active dry yeast", 40, 41, 7, 325),
    ("vinegar", 0, 1, 0, 20),
    # Spices, whole and ground - realistic per-100g so a heavy hand still
    # scales sensibly, but typical recipe quantities are tiny so their
    # actual contribution is small
    ("garam masala powder", 11, 50, 15, 350),
    ("sambar powder", 11, 50, 15, 350),
    ("panch phoran masala", 11, 50, 15, 350),
    ("chaat masala powder", 11, 50, 15, 350),
    ("anardana powder (pomegranate seed powder)", 4, 66, 1.5, 292),
    ("kashmiri red chilli powder", 14, 50, 17, 282),
    ("red chilli powder", 14, 50, 17, 282),
    ("red chili powder", 14, 50, 17, 282),
    ("chilli powder", 14, 50, 17, 282),
    ("turmeric powder (haldi)", 8, 65, 3, 312),
    ("turmeric powder", 8, 65, 3, 312),
    ("coriander powder (dhania)", 12, 55, 17, 298),
    ("coriander powder", 12, 55, 17, 298),
    ("coriander (dhania) seeds", 12, 55, 17, 298),
    ("coriander seeds", 12, 55, 17, 298),
    ("cumin powder (jeera)", 18, 44, 22, 375),
    ("cumin powder", 18, 44, 22, 375),
    ("cumin seeds (jeera)", 18, 44, 22, 375),
    ("cumin seeds", 18, 44, 22, 375),
    ("mustard seeds", 21, 28, 36, 508),
    ("fennel seeds (saunf)", 16, 52, 15, 345),
    ("fennel powder", 16, 52, 15, 345),
    ("fennel", 16, 52, 15, 345),
    ("methi seeds (fenugreek seeds)", 23, 58, 6, 323),
    ("fenugreek seeds", 23, 58, 6, 323),
    ("kasuri methi (dried fenugreek leaves)", 18, 40, 5, 300),
    ("kasuri methi", 18, 40, 5, 300),
    ("ajwain (carom seeds)", 16, 44, 25, 400),
    ("kalonji (onion nigella seeds)", 21, 38, 28, 420),
    ("amchur (dry mango powder)", 2, 75, 1, 300),
    ("dry ginger powder", 9, 71, 5, 347),
    ("asafoetida (hing)", 4, 67, 1.1, 297),
    ("asafetida", 4, 67, 1.1, 297),
    ("asafoetida", 4, 67, 1.1, 297),
    ("curry leaves", 6, 18, 1, 108),
    ("cardamom (elaichi) pods/seeds", 11, 68, 7, 311),
    ("cardamom powder (elaichi)", 11, 68, 7, 311),
    ("black cardamom (badi elaichi)", 11, 68, 7, 311),
    ("cardamom", 11, 68, 7, 311),
    ("cinnamon stick (dalchini)", 4, 81, 1.2, 247),
    ("cinnamon powder (dalchini)", 4, 81, 1.2, 247),
    ("cinnamon", 4, 81, 1.2, 247),
    ("cloves (laung)", 6, 65, 13, 274),
    ("(laung)", 6, 65, 13, 274),
    ("bay leaf (tej patta)", 7.6, 75, 8, 313),
    ("bay leaves (tej patta)", 7.6, 75, 8, 313),
    ("bay leaf", 7.6, 75, 8, 313),
    ("star anise", 18, 50, 16, 337),
    ("mace (javitri)", 6, 51, 24, 475),
    ("nutmeg powder", 6, 49, 36, 525),
    ("black pepper powder", 10, 64, 3.3, 251),
    ("whole black peppercorns", 10, 64, 3.3, 251),
    ("black peppercorns", 10, 64, 3.3, 251),
    ("saffron strands", 11, 65, 6, 310),
    ("saffron", 11, 65, 6, 310),
    ("black salt (kala namak)", 0, 0, 0, 0),
    ("salt", 0, 0, 0, 0),
    ("baking soda", 0, 0, 0, 0),
    ("cooking soda", 0, 0, 0, 0),
    ("baking powder", 0, 0, 0, 0),
    ("enos fruit salt", 0, 0, 0, 0),
    ("vanilla extract", 0, 13, 0, 288),
    ("rose water", 0, 0, 0, 0),
    ("water", 0, 0, 0, 0),
]

# "pc" (piece) unit weights in grams - matched the same way (keyword
# substring, longest first), since "1 onion" and "1 cardamom pod" are very
# different masses. Falls back to _DEFAULT_PC_GRAMS when nothing matches.
_PC_GRAMS: list[tuple[str, float]] = [
    ("chicken breast", 150),
    ("potato", 150),
    ("tomato", 120),
    ("onion", 110),
    ("banana", 120),
    ("lemon", 60),
    ("egg", 50),
    ("bread", 30),
    ("cinnamon stick", 3),
    ("green chilli", 5),
    ("green chili", 5),
    ("garlic", 5),
    ("bay leaf", 0.5),
    ("cardamom", 0.5),
    ("clove", 0.2),
    ("(laung)", 0.2),
]
_DEFAULT_PC_GRAMS = 30

_UNIT_GRAMS = {"g": 1.0, "ml": 1.0, "tbsp": 15.0, "tsp": 5.0, "cup": 240.0}

# Anything not matched at all (rare, long-tail ingredient strings) - a mild
# generic estimate rather than zero, so an unmatched item doesn't just
# silently disappear from the total.
_DEFAULT_MACROS = (1.5, 6.0, 0.3, 30.0)


def _grams_for(item: str, qty: float, unit: str) -> float:
    if unit == "pc":
        item_lower = item.lower()
        for keyword, grams in _PC_GRAMS:
            if keyword in item_lower:
                return qty * grams
        return qty * _DEFAULT_PC_GRAMS
    return qty * _UNIT_GRAMS.get(unit, 0.0)  # unrecognized unit ("to taste", ...) contributes nothing


def _macros_for(item: str) -> tuple[float, float, float, float]:
    item_lower = item.lower()
    for keyword, protein, carbs, fat, kcal in _MACROS_PER_100G:
        if keyword in item_lower:
            return protein, carbs, fat, kcal
    return _DEFAULT_MACROS


def estimate_nutrition(ingredients: list[dict]) -> dict:
    """ingredients: [{"item"|"name": str, "qty": float, "unit": str}, ...],
    already per-serving (see Recipe.ingredients' docstring in app/models.py
    and _serialize_combo_recipe's per-serving convention). Returns
    per-serving {protein_g, carbs_g, fat_g, calories}, rounded to 1 decimal."""
    protein = carbs = fat = kcal = 0.0
    for ing in ingredients or []:
        item = ing.get("item") or ing.get("name") or ""
        qty = ing.get("qty", 0) or 0
        unit = ing.get("unit", "")
        grams = _grams_for(item, qty, unit)
        if grams <= 0:
            continue
        p100, c100, f100, k100 = _macros_for(item)
        factor = grams / 100.0
        protein += p100 * factor
        carbs += c100 * factor
        fat += f100 * factor
        kcal += k100 * factor

    return {
        "protein_g": round(protein, 1),
        "carbs_g": round(carbs, 1),
        "fat_g": round(fat, 1),
        "calories": round(kcal, 0),
    }
