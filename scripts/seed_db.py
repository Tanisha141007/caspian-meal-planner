"""Loads the recipe universe and the state->cuisine popularity map into the DB.
Defaults to the small hand-curated fixture (app/data/recipes_seed.json); pass
--ingested to load the full Kaggle-derived dataset once
scripts/ingest_recipes.py has produced app/data/recipes_ingested.json.

    python scripts/seed_db.py [--ingested]
"""

import argparse
from pathlib import Path

from app.data.seed import RECIPES_PATH, seed_recipes, seed_region_cuisine_map

INGESTED_PATH = Path(__file__).parent.parent / "app" / "data" / "recipes_ingested.json"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ingested", action="store_true", help="load the full ingested Kaggle dataset instead of the small fixture"
    )
    args = parser.parse_args()

    if args.ingested:
        if not INGESTED_PATH.exists():
            raise SystemExit(f"{INGESTED_PATH} doesn't exist yet - run scripts/ingest_recipes.py first")
        seed_recipes(INGESTED_PATH)
    else:
        seed_recipes(RECIPES_PATH)

    seed_region_cuisine_map()
