import datetime as dt
import random
import string

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.db import Base

# Excludes 0/O/1/I - easy to misread when a family reads this code aloud or
# texts it to their cook.
_LINK_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_link_code() -> str:
    return "".join(random.choices(_LINK_CODE_ALPHABET, k=6))


class Household(Base):
    """One family whose cook we message - over whichever channel the cook's
    first inbound message arrived on (SMS, Telegram, ...), matched via
    link_code rather than phone number, since not every channel exposes a
    stable, known-in-advance identity (Telegram's sender has no phone
    number at all, for instance)."""

    __tablename__ = "households"

    id = Column(Integer, primary_key=True)
    # Supabase auth user id (JWT "sub" claim). Nullable for households
    # created before auth existed (CLI scripts, the old Jinja demo); every
    # household created through app/api/ sets it and every app/api/ route
    # scopes its queries by it - see app/api/deps.py::get_current_user_id.
    owner_user_id = Column(String, nullable=True, unique=True, index=True)
    name = Column(String, nullable=False)
    cook_name = Column(String, nullable=False)
    cook_phone = Column(String, nullable=False, unique=True)  # E.164, e.g. +9198XXXXXXXX
    send_time = Column(String, default="07:00")  # HH:MM local time for the daily message
    # Stored per household for the Preferences UI, but a Caspian connection
    # is one channel for the whole deployment today (CASPIAN_CHANNEL in
    # app/config.py) - per-household channel routing isn't wired up yet.
    preferred_channel = Column(String, default="sms")  # "sms" | "whatsapp"
    lead_hours = Column(Integer, default=12)  # hours before a meal to notify the cook (display/storage only for now)

    city = Column(String, default="")  # free text, display only
    # Indian state/UT, must match RegionCuisineMap.state - powers regional
    # cuisine weighting in the planner when preferred_cuisines is empty.
    state = Column(String, default="")

    diet_type = Column(String, default="veg")  # veg | non-veg | eggetarian | jain | vegan
    allergies = Column(JSON, default=list)  # ["peanut", "dairy"]
    disliked_ingredients = Column(JSON, default=list)  # ["bitter gourd"]
    preferred_cuisines = Column(JSON, default=list)  # ["punjabi", "south-indian"]
    spice_level = Column(String, default="medium")  # mild | medium | hot
    family_size = Column(Integer, default=4)
    kids_count = Column(Integer, default=0)
    notes = Column(Text, default="")  # free-text prefs fed straight into the LLM prompt

    active = Column(Boolean, default=True)
    # The code the family relays to their cook - the cook's first message
    # to the bot/number, whatever it says, must be exactly this code. Once
    # matched, caspian_conversation_id is filled in and this stops being
    # needed for that household. Unique so a stray/guessed code can't link
    # to the wrong household.
    link_code = Column(String, unique=True, index=True, default=generate_link_code)
    # Filled in once the cook's first message has matched link_code above.
    caspian_connection_id = Column(String, nullable=True)
    caspian_conversation_id = Column(String, nullable=True)

    meal_plans = relationship("MealPlan", back_populates="household")


class Recipe(Base):
    """One dish in the Indian recipe universe. A meal slot is usually a
    combo of 2-4 of these (e.g. dal + sabzi + rice + roti for lunch)."""

    __tablename__ = "recipes"

    id = Column(String, primary_key=True)  # slug, e.g. "dal_tadka"
    name = Column(String, nullable=False)
    region = Column(String, default="")  # north | south | west | east | pan-india
    cuisine_style = Column(String, default="")  # punjabi, tamil, gujarati, bengali, ...
    meal_types = Column(JSON, default=list)  # ["breakfast"], ["lunch", "dinner"], ...
    diet = Column(String, default="veg")  # veg | non-veg | egg
    spice_level = Column(String, default="medium")
    prep_time_min = Column(Integer, default=30)
    # protein-heavy | carb-heavy | vegetable-based | mixed - used by the planner
    # to avoid the same category landing in back-to-back meal slots.
    main_ingredient_category = Column(String, default="mixed")
    # summer | monsoon | winter | all-season - split out from `tags` so the
    # planner can filter on it directly instead of string-matching a free list.
    season_tags = Column(JSON, default=list)
    tags = Column(JSON, default=list)  # ["jain-friendly", "fasting-friendly", "kid-friendly"]
    # Ingredients scaled to 1 serving: [{"item": "poha", "qty": 60, "unit": "g"}, ...].
    # unit is one of: g, ml, pc, cup, tbsp, tsp - spices/liquids/grains normalize
    # to volume units (cup/tbsp/tsp), whole items ("1 onion") stay pc, a few
    # things that don't map sensibly to a kitchen measure (e.g. paneer by weight)
    # stay g/ml. See app/messaging/formatter.py for how these render in messages.
    ingredients = Column(JSON, default=list)


class RegionCuisineMap(Base):
    """Maps an Indian state/UT to the cuisines locally popular there, so a
    household's location can bias recipe suggestions even when their explicit
    preferences don't mention a cuisine. Hand-authored (this is well-known
    domestic knowledge, not something that needs an external dataset) -
    weight is relative preference strength within the state, highest first."""

    __tablename__ = "region_cuisine_map"

    id = Column(Integer, primary_key=True)
    state = Column(String, nullable=False, index=True)  # e.g. "Kerala", "Punjab"
    cuisine_style = Column(String, nullable=False)  # matches Recipe.cuisine_style
    weight = Column(Float, default=1.0)  # higher = more strongly associated with the state


class MealPlan(Base):
    """A generated weekly or monthly chart for one household."""

    __tablename__ = "meal_plans"

    id = Column(Integer, primary_key=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    period_type = Column(String, nullable=False)  # "week" | "month"
    period_start = Column(Date, nullable=False)
    status = Column(String, default="active")  # draft | active | superseded
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    household = relationship("Household", back_populates="meal_plans")
    items = relationship("MealPlanItem", back_populates="meal_plan")


class MealPlanItem(Base):
    """One meal slot on one day: which dishes, for how many people."""

    __tablename__ = "meal_plan_items"

    id = Column(Integer, primary_key=True)
    meal_plan_id = Column(Integer, ForeignKey("meal_plans.id"), nullable=False)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    date = Column(Date, nullable=False)
    meal_slot = Column(String, nullable=False)  # breakfast | lunch | snack | dinner
    dish_recipe_ids = Column(JSON, default=list)  # ["dal_tadka", "jeera_rice", "roti"]
    portion_servings = Column(Float, default=4.0)
    note = Column(String, default="")  # e.g. "no onion today - fasting"

    sent_at = Column(DateTime, nullable=True)
    delivery_status = Column(String, default="pending")  # pending | sent | failed

    meal_plan = relationship("MealPlan", back_populates="items")


class Feedback(Base):
    """A cook's WhatsApp/SMS reply, plus what we understood it to mean."""

    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True)
    household_id = Column(Integer, ForeignKey("households.id"), nullable=False)
    meal_plan_item_id = Column(Integer, ForeignKey("meal_plan_items.id"), nullable=True)
    conversation_id = Column(String, nullable=True)
    raw_text = Column(Text, nullable=False)
    parsed_intent = Column(JSON, default=dict)  # {"type": "dislike", "recipe_id": "...", ...}
    created_at = Column(DateTime, default=dt.datetime.utcnow)
