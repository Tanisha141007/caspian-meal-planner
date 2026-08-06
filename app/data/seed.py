import json
from pathlib import Path

from app.db import get_session, init_db
from app.models import Recipe

RECIPES_PATH = Path(__file__).parent / "recipes_seed.json"


def seed_recipes():
    """Load the Indian recipe universe from recipes_seed.json into the DB.
    Safe to re-run: upserts by recipe id."""
    init_db()
    recipes = json.loads(RECIPES_PATH.read_text())

    session = get_session()
    try:
        for r in recipes:
            existing = session.get(Recipe, r["id"])
            if existing:
                for key, value in r.items():
                    setattr(existing, key, value)
            else:
                session.add(Recipe(**r))
        session.commit()
        print(f"Seeded {len(recipes)} recipes.")
    finally:
        session.close()


if __name__ == "__main__":
    seed_recipes()
