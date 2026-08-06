import os
from dotenv import load_dotenv

load_dotenv()

CASPIAN_API_KEY = os.environ.get("CASPIAN_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./caspian_meals.db")
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata")

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

# Meal slots sent each day, in order.
MEAL_SLOTS = ["breakfast", "lunch", "snack", "dinner"]
