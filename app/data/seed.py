import json
from pathlib import Path

from app.db import get_session, init_db
from app.models import Recipe, RegionCuisineMap

RECIPES_PATH = Path(__file__).parent / "recipes_seed.json"
REGION_CUISINE_PATH = Path(__file__).parent / "region_cuisine_seed.json"


def seed_recipes(path: Path = RECIPES_PATH):
    """Load the Indian recipe universe (default: the small hand-curated
    fixture; pass app/data/recipes_ingested.json once scripts/ingest_recipes.py
    has run) into the DB. Safe to re-run: upserts by recipe id.

    Bulk, not per-row get()+setattr()/add(): that was ~2 round-trips per
    recipe (a SELECT existence check, then an INSERT or UPDATE), which is
    fine against local SQLite but took several minutes - long enough to
    time out - against a real network-hop DB (Supabase's pooler, from
    Render). One SELECT for all existing ids, then one batched INSERT and
    one batched UPDATE, gets this down to low single-digit seconds."""
    init_db()
    recipes = json.loads(Path(path).read_text())

    session = get_session()
    try:
        existing_ids = {row[0] for row in session.query(Recipe.id).all()}
        to_insert = [r for r in recipes if r["id"] not in existing_ids]
        to_update = [r for r in recipes if r["id"] in existing_ids]

        if to_insert:
            session.bulk_insert_mappings(Recipe, to_insert)
        if to_update:
            session.bulk_update_mappings(Recipe, to_update)
        session.commit()
        print(f"Seeded {len(recipes)} recipes ({len(to_insert)} new, {len(to_update)} updated).")
    finally:
        session.close()


def seed_region_cuisine_map():
    """Loads the hand-authored state/UT -> cuisine_style weighting from
    region_cuisine_seed.json. Safe to re-run: replaces all rows for a given
    state rather than accumulating duplicates."""
    init_db()
    data = json.loads(REGION_CUISINE_PATH.read_text())
    data.pop("_comment", None)

    session = get_session()
    try:
        session.query(RegionCuisineMap).delete()
        count = 0
        for state, entries in data.items():
            for entry in entries:
                session.add(
                    RegionCuisineMap(
                        state=state,
                        cuisine_style=entry["cuisine_style"],
                        weight=entry["weight"],
                    )
                )
                count += 1
        session.commit()
        print(f"Seeded {count} region->cuisine rows across {len(data)} states/UTs.")
    finally:
        session.close()


if __name__ == "__main__":
    seed_recipes()
    seed_region_cuisine_map()
