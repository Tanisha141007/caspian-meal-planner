"""Pydantic request bodies for app/api/routers/*. Response bodies are plain
dicts from app/api/serializers.py - no separate response models to keep in
sync, FastAPI just serializes whatever the serializer returns."""

import datetime as dt

from pydantic import BaseModel, EmailStr, Field

DIET_TYPES = ("veg", "vegan", "jain", "eggetarian", "non-veg")
SPICE_LEVELS = ("mild", "medium", "hot")
CHANNELS = ("sms", "whatsapp")


class HouseholdCreate(BaseModel):
    name: str
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
    # Where the Monday chart goes. Omit it and the signed-in user's own email
    # (from the Supabase token) is used - see routers/households.py.
    owner_email: EmailStr | None = None
    weekly_email_enabled: bool = True


class HouseholdUpdate(BaseModel):
    name: str | None = None
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
    owner_email: EmailStr | None = None
    weekly_email_enabled: bool | None = None


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


class WeeklyEmailRequest(BaseModel):
    week_start: dt.date | None = None  # defaults to the current week's Monday
