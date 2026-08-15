import os
from dotenv import load_dotenv

load_dotenv()

CASPIAN_API_KEY = os.environ.get("CASPIAN_API_KEY", "")

# Which LLM backs the meal-plan generator and the "Ask AI" free-text parser.
# "gemini" (default): Google AI Studio's free tier - no card, no expiry, see
# app/meal_planner/llm_client.py. "anthropic": Claude, if ANTHROPIC_API_KEY
# is set and cost isn't a concern. Neither key set -> generator.py's callers
# fall back to the rule-based path (same pattern as app/web/mock.py).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./caspian_meals.db")
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata")


def llm_configured() -> bool:
    """True once whichever provider LLM_PROVIDER points at has a key set."""
    if LLM_PROVIDER == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    return bool(GEMINI_API_KEY)

# Meal slots sent each day, in order.
MEAL_SLOTS = ["breakfast", "lunch", "snack", "dinner"]
