"""Adds one household + its cook's phone number.

    python scripts/onboard_household.py \\
        --name "Malani" --cook-name "Radha" --cook-phone "+919812345678" \\
        --diet-type veg --family-size 4 --kids-count 1 --spice-level mild \\
        --allergies peanut --preferred-cuisines gujarati punjabi
"""

import argparse

from app.db import get_session, init_db
from app.models import Household


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Household/family name")
    parser.add_argument("--cook-name", required=True)
    parser.add_argument("--cook-phone", required=True, help="E.164, e.g. +919812345678")
    parser.add_argument("--diet-type", default="veg", choices=["veg", "vegan", "jain", "eggetarian", "non-veg"])
    parser.add_argument("--family-size", type=int, default=4)
    parser.add_argument("--kids-count", type=int, default=0)
    parser.add_argument("--spice-level", default="medium", choices=["mild", "medium", "hot"])
    parser.add_argument("--allergies", nargs="*", default=[])
    parser.add_argument("--dislikes", nargs="*", default=[])
    parser.add_argument("--preferred-cuisines", nargs="*", default=[])
    parser.add_argument("--send-time", default="07:00", help="HH:MM local time for the daily message")
    parser.add_argument("--notes", default="", help="Free text handed straight to the LLM prompt")
    args = parser.parse_args()

    init_db()
    session = get_session()
    try:
        household = Household(
            name=args.name,
            cook_name=args.cook_name,
            cook_phone=args.cook_phone,
            diet_type=args.diet_type,
            family_size=args.family_size,
            kids_count=args.kids_count,
            spice_level=args.spice_level,
            allergies=args.allergies,
            disliked_ingredients=args.dislikes,
            preferred_cuisines=args.preferred_cuisines,
            send_time=args.send_time,
            notes=args.notes,
        )
        session.add(household)
        session.commit()
        print(f"Created household {household.id}: {household.name} (cook {household.cook_name}, {household.cook_phone})")
    finally:
        session.close()


if __name__ == "__main__":
    main()
