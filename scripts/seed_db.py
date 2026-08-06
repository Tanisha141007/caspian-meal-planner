"""Loads the Indian recipe universe (app/data/recipes_seed.json) into the DB.

    python scripts/seed_db.py
"""

from app.data.seed import seed_recipes

if __name__ == "__main__":
    seed_recipes()
