"""Generates a weekly meal chart for one household.

    python scripts/generate_week.py <household_id> [--week-start YYYY-MM-DD]
"""

import argparse
import datetime as dt

from app.db import init_db
from app.meal_planner.generator import generate_weekly_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("household_id", type=int)
    parser.add_argument("--week-start", help="YYYY-MM-DD, defaults to next Monday")
    args = parser.parse_args()

    init_db()
    if args.week_start:
        week_start = dt.date.fromisoformat(args.week_start)
    else:
        today = dt.date.today()
        week_start = today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)

    plan_id = generate_weekly_plan(args.household_id, week_start)
    print(f"Generated meal_plan {plan_id} starting {week_start}")


if __name__ == "__main__":
    main()
