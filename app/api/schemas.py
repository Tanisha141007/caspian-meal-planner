"""Pydantic request bodies for app/api/routers/*. Response bodies are plain
dicts from app/api/serializers.py - no separate response models to keep in
sync, FastAPI just serializes whatever the serializer returns."""

import datetime as dt

from pydantic import BaseModel, Field, field_validator

DIET_TYPES = ("veg", "vegan", "jain", "eggetarian", "non-veg")
SPICE_LEVELS = ("mild", "medium", "hot")
CHANNELS = ("sms", "whatsapp")
MEAL_SLOTS = ("breakfast", "lunch", "snack", "dinner")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


class HouseholdCreate(BaseModel):
    name: str
    flat_no: str = ""
    building: str = ""
    cook_name: str
    cook_phone: str
    city: str = ""
    state: str = ""
    diet_type: str = Field(default="veg", pattern="|".join(DIET_TYPES))
    family_size: int = Field(default=4, ge=1, le=20)
    kids_count: int = Field(default=0, ge=0)
    spice_level: str = Field(default="medium", pattern="|".join(SPICE_LEVELS))
    allergies: list[str] = []
    disliked_ingredients: list[str] = []
    preferred_cuisines: list[str] = []
    notes: str = ""
    preferred_channel: str = Field(default="sms", pattern="|".join(CHANNELS))
    lead_hours: int = Field(default=12, ge=1, le=48)
    notify_me: bool = False
    notify_meals: list[str] = Field(default_factory=lambda: ["breakfast", "lunch", "snack", "dinner"])
    send_time: str = Field(default="07:00", pattern=r"^\d{2}:\d{2}$")
    cook_message_schedule: dict[str, list[dict]] = Field(default_factory=dict)

    @field_validator("notify_meals")
    @classmethod
    def valid_notify_meals(cls, value: list[str]) -> list[str]:
        invalid = [slot for slot in value if slot not in MEAL_SLOTS]
        if invalid:
            raise ValueError(f"Invalid meal slot(s): {', '.join(invalid)}")
        return value

    @field_validator("cook_message_schedule")
    @classmethod
    def valid_cook_message_schedule(cls, value: dict[str, list[dict]]) -> dict[str, list[dict]]:
        return _valid_cook_message_schedule(value)


class HouseholdUpdate(BaseModel):
    name: str | None = None
    flat_no: str | None = None
    building: str | None = None
    cook_name: str | None = None
    cook_phone: str | None = None
    city: str | None = None
    state: str | None = None
    diet_type: str | None = Field(default=None, pattern="|".join(DIET_TYPES))
    family_size: int | None = Field(default=None, ge=1, le=20)
    kids_count: int | None = Field(default=None, ge=0)
    spice_level: str | None = Field(default=None, pattern="|".join(SPICE_LEVELS))
    allergies: list[str] | None = None
    disliked_ingredients: list[str] | None = None
    preferred_cuisines: list[str] | None = None
    notes: str | None = None
    preferred_channel: str | None = Field(default=None, pattern="|".join(CHANNELS))
    lead_hours: int | None = Field(default=None, ge=1, le=48)
    notify_me: bool | None = None
    notify_meals: list[str] | None = None
    send_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    cook_message_schedule: dict[str, list[dict]] | None = None

    @field_validator("notify_meals")
    @classmethod
    def valid_notify_meals(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        invalid = [slot for slot in value if slot not in MEAL_SLOTS]
        if invalid:
            raise ValueError(f"Invalid meal slot(s): {', '.join(invalid)}")
        return value

    @field_validator("cook_message_schedule")
    @classmethod
    def valid_cook_message_schedule(cls, value: dict[str, list[dict]] | None) -> dict[str, list[dict]] | None:
        if value is None:
            return value
        return _valid_cook_message_schedule(value)


def _valid_cook_message_schedule(value: dict[str, list[dict]]) -> dict[str, list[dict]]:
    for day, entries in value.items():
        if day not in DAYS:
            raise ValueError(f"Invalid day: {day}")
        if not isinstance(entries, list):
            raise ValueError(f"Schedule for {day} must be a list")
        for entry in entries:
            time = entry.get("time", "")
            if not isinstance(time, str) or len(time.split(":")) != 2:
                raise ValueError(f"Invalid time for {day}")
            meals = entry.get("meals", [])
            invalid = [slot for slot in meals if slot not in MEAL_SLOTS]
            if invalid:
                raise ValueError(f"Invalid meal slot(s): {', '.join(invalid)}")
    return value


class GenerateWeekRequest(BaseModel):
    week_start: dt.date | None = None  # defaults to this Monday


class AssignRequest(BaseModel):
    date: dt.date
    slot: str
    recipe_id: str


class SwapRequest(BaseModel):
    date: dt.date
    slot: str
    hint: str = ""


class AskAIRequest(BaseModel):
    message: str


class NotifyCookRequest(BaseModel):
    date: dt.date | None = None  # defaults to today
    # If set, sends only this one meal slot (e.g. the Planner tab's "Notify
    # now" targeting whatever meal is next up) instead of every planned
    # slot on `date`.
    slot: str | None = None
