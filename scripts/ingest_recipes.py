"""Parses app/data/raw/indian_food_dataset.csv (the Kaggle "6000+ Indian Food
Recipes Dataset" CSV, dropped in manually - see README) into
app/data/recipes_ingested.json, matching the Recipe model schema.

    python scripts/ingest_recipes.py [--csv path/to/other.csv]

Prints a summary report (row counts, drop reasons, per-region/diet/meal_type
breakdown, ingredient parse-failure rate) - this doubles as part of the
Phase 1 verification step. Doesn't touch the DB; run scripts/seed_db.py
--ingested afterward to load the result.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import pandas as pd

from app.data.ingest import (
    CUISINE_MAP,
    clean_display_name,
    infer_diet,
    infer_main_ingredient_category,
    infer_meal_types,
    infer_spice_level,
    is_mostly_ascii,
    is_staple,
    parse_ingredients,
    slugify,
)

DEFAULT_CSV = Path(__file__).parent.parent / "app" / "data" / "raw" / "indian_food_dataset.csv"
OUTPUT_PATH = Path(__file__).parent.parent / "app" / "data" / "recipes_ingested.json"

MIN_SERVINGS, MAX_SERVINGS, DEFAULT_SERVINGS = 1, 20, 4


def clamp_servings(raw) -> float:
    try:
        servings = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_SERVINGS
    if servings != servings or not (MIN_SERVINGS <= servings <= MAX_SERVINGS):  # NaN or out of range
        return DEFAULT_SERVINGS
    return servings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    args = parser.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"{args.csv} not found - drop the Kaggle CSV there first.")

    df = pd.read_csv(args.csv)
    total_rows = len(df)

    drop_reasons = Counter()
    parse_failed_lines = 0
    parsed_lines_total = 0
    recipes = []
    slugs_used = set()

    for _, row in df.iterrows():
        cuisine_raw = str(row.get("Cuisine", "")).strip().lower().replace("﻿", "")
        mapping = CUISINE_MAP.get(cuisine_raw)
        if mapping is None:
            drop_reasons["non-indian or unrecognized cuisine"] += 1
            continue
        cuisine_style, region = mapping

        name_raw = row.get("TranslatedRecipeName") or row.get("RecipeName") or ""
        ingredients_raw = row.get("TranslatedIngredients") or row.get("Ingredients") or ""
        if not is_mostly_ascii(name_raw) or not is_mostly_ascii(ingredients_raw):
            drop_reasons["not translated to English"] += 1
            continue

        servings = clamp_servings(row.get("Servings"))
        ingredients, failed = parse_ingredients(ingredients_raw, servings)
        parse_failed_lines += failed
        parsed_lines_total += failed + len(ingredients)
        if not ingredients:
            drop_reasons["no ingredients parsed"] += 1
            continue

        meal_types = infer_meal_types(row.get("Course"))
        ingredient_items = [i["item"] for i in ingredients]
        diet, extra_tags = infer_diet(ingredient_items, row.get("Diet"))
        main_category = infer_main_ingredient_category(ingredient_items)
        spice_level = infer_spice_level(ingredient_items, row.get("Course"), cuisine_style)

        prep = row.get("PrepTimeInMins") or 0
        cook = row.get("CookTimeInMins") or 0
        total_time = row.get("TotalTimeInMins")
        try:
            prep_time_min = int(prep) + int(cook)
            if prep_time_min <= 0:
                raise ValueError
        except (TypeError, ValueError):
            try:
                prep_time_min = int(total_time)
            except (TypeError, ValueError):
                prep_time_min = 30

        name = clean_display_name(str(name_raw))
        tags = list(extra_tags)
        if is_staple(name):
            tags.append("staple")

        recipes.append(
            {
                "id": slugify(name, slugs_used),
                "name": name,
                "region": region,
                "cuisine_style": cuisine_style,
                "meal_types": meal_types,
                "diet": diet,
                "spice_level": spice_level,
                "prep_time_min": prep_time_min,
                "main_ingredient_category": main_category,
                "season_tags": ["all-season"],  # dataset carries no season signal
                "tags": tags,
                "ingredients": ingredients,
            }
        )

    OUTPUT_PATH.write_text(json.dumps(recipes, indent=2))

    print(f"Read {total_rows} rows from {args.csv.name}")
    for reason, count in drop_reasons.most_common():
        print(f"  dropped {count:5d}  ({reason})")
    print(f"Kept {len(recipes)} recipes -> {OUTPUT_PATH}")
    if parsed_lines_total:
        rate = 100 * parse_failed_lines / parsed_lines_total
        print(f"Ingredient-line parse failures: {parse_failed_lines}/{parsed_lines_total} ({rate:.1f}%)")

    print("\nBy region:")
    for region, count in Counter(r["region"] for r in recipes).most_common():
        print(f"  {region:12s} {count}")
    print("\nBy diet:")
    for diet, count in Counter(r["diet"] for r in recipes).most_common():
        print(f"  {diet:10s} {count}")
    print("\nBy meal type (recipes can count in more than one):")
    meal_type_counts = Counter()
    for r in recipes:
        meal_type_counts.update(r["meal_types"])
    for slot, count in meal_type_counts.most_common():
        print(f"  {slot:10s} {count}")


if __name__ == "__main__":
    main()
