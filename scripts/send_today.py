"""Sends today's planned meals to one household's cook right now, without
waiting for the scheduler - useful for testing the message format.

    python scripts/send_today.py <household_id>
"""

import argparse
import datetime as dt

from app.db import get_session, init_db
from app.messaging.handler import connect_channel, send_daily_message
from app.models import Household, MealPlanItem, Recipe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("household_id", type=int)
    args = parser.parse_args()

    init_db()
    connect_channel()

    session = get_session()
    try:
        household = session.get(Household, args.household_id)
        if household is None:
            raise SystemExit(f"No household with id {args.household_id}")

        today = dt.date.today()
        items = (
            session.query(MealPlanItem)
            .filter(MealPlanItem.household_id == household.id, MealPlanItem.date == today)
            .all()
        )
        if not items:
            raise SystemExit(f"No meal plan for {household.name} on {today} - run generate_week.py first")

        recipe_cache = {r.id: r for r in session.query(Recipe).all()}
        slot_items = {it.meal_slot: it for it in items}

        text = send_daily_message(household, slot_items, recipe_cache)
        print("Sent:\n")
        print(text)
    finally:
        session.close()


if __name__ == "__main__":
    main()
