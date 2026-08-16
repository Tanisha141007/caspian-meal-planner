import json
from pathlib import Path

from app.db import get_session, init_db
from app.models import Recipe, RegionCuisineMap

RECIPES_PATH = Path(__file__).parent / "recipes_seed.json"
REGION_CUISINE_PATH = Path(__file__).parent / "region_cuisine_seed.json"

_CHUNK_SIZE = 500  # rows per statement - keeps bound-param counts sane, still few round-trips overall


def _chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def seed_recipes(path: Path = RECIPES_PATH):
    """Load the Indian recipe universe (default: the small hand-curated
    fixture; pass app/data/recipes_ingested.json once scripts/ingest_recipes.py
    has run) into the DB. Safe to re-run: upserts by recipe id.

    One real multi-row `INSERT ... ON CONFLICT DO UPDATE` per chunk, not
    session.bulk_insert_mappings()/bulk_update_mappings(): those looked
    like an improvement over the original per-row get()+setattr()/add()
    loop, but bulk_update_mappings still executes one UPDATE per row under
    the hood (psycopg2's executemany doesn't collapse UPDATEs into fewer
    round-trips the way SQLAlchemy 2.0's insertmanyvalues does for plain
    INSERTs) - fine against local SQLite's near-zero latency, but still
    thousands of round-trips against a real network hop (Supabase's
    pooler, from Render), which is exactly what timed out in production.
    ON CONFLICT DO UPDATE is a single statement covering both cases, so
    this is genuinely ~9 round-trips total (4262 recipes / 500-row
    chunks) regardless of how many already exist."""
    from sqlalchemy.dialects import postgresql, sqlite

    init_db()
    recipes = json.loads(Path(path).read_text())

    session = get_session()
    try:
        dialect = session.bind.dialect.name
        insert = postgresql.insert if dialect == "postgresql" else sqlite.insert
        update_cols = {c.name: c for c in Recipe.__table__.columns if c.name != "id"}

        for chunk in _chunked(recipes, _CHUNK_SIZE):
            stmt = insert(Recipe).values(chunk)
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"], set_={name: stmt.excluded[name] for name in update_cols}
            )
            session.execute(stmt)
        session.commit()
        print(f"Seeded {len(recipes)} recipes.")
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
