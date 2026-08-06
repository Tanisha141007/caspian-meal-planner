import datetime as dt

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


class Household(Base):
    """One family whose cook we message. Maps 1:1 to a phone number today,
    a WhatsApp identity once Caspian ships connect_whatsapp()."""

    __tablename__ = "households"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    cook_name = Column(String, nullable=False)
    cook_phone = Column(String, nullable=False, unique=True)  # E.164, e.g. +9198XXXXXXXX
    send_time = Column(String, default="07:00")  # HH:MM local time for the daily message

    diet_type = Column(String, default="veg")  # veg | non-veg | eggetarian | jain | vegan
    allergies = Column(JSON, default=list)  # ["peanut", "dairy"]
    disliked_ingredients = Column(JSON, default=list)  # ["bitter gourd"]
    preferred_cuisines = Column(JSON, default=list)  # ["punjabi", "south-indian"]
    spice_level = Column(String, default="medium")  # mild | medium | hot
    family_size = Column(Integer, default=4)
    kids_count = Column(Integer, default=0)
    notes = Column(Text, default="")  # free-text prefs fed straight into the LLM prompt

    active = Column(Boolean, default=True)
    # Filled in once Caspian's SMS connection exists / the cook has texted at least once.
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
    tags = Column(JSON, default=list)  # ["jain-friendly", "fasting-friendly", "kid-friendly"]
    # Ingredients scaled to 1 serving: [{"item": "poha", "qty": 60, "unit": "g"}, ...]
    ingredients = Column(JSON, default=list)


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
