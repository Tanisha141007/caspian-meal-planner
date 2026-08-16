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
# "-latest" alias, not a pinned version: Google retires specific model
# versions over time (confirmed live: gemini-2.5-flash 404s for new keys as
# of Aug 2026, "no longer available to new users") - the alias auto-tracks
# whatever their current model is, so this doesn't need revisiting every
# time they rotate models. "flash-lite" over plain "flash": hit a real
# 429 RESOURCE_EXHAUSTED on flash-latest's free tier (5 requests/minute on
# the model it currently points to, gemini-3.7-flash) under completely
# ordinary use, not a stress test - lite variants are provisioned for
# higher-volume/cheaper use and are the better fit for an app that calls
# the LLM on every plan generation and every cook reply.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")

# Telegram bot token (from @BotFather) - free, no card, but the bot can't
# cold-start a conversation (platform-wide Bot API restriction, not
# Caspian's) - the cook must message it first. See Household.link_code.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./caspian_meals.db")
APP_TIMEZONE = os.environ.get("APP_TIMEZONE", "Asia/Kolkata")

# Comma-separated origins app/api/main.py's CORS middleware allows - the
# deployed mealtime-harmony frontend (Cloudflare) plus local dev ports.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        # 8080: mealtime-harmony's actual `vite dev` port (confirmed live),
        # 5173/3000/8787: common Vite/Cloudflare dev port fallbacks
        "CORS_ORIGINS", "http://localhost:8080,http://localhost:3000,http://localhost:5173,http://localhost:8787"
    ).split(",")
    if o.strip()
]

# Supabase project (M3: auth). Empty until configured - app/api/deps.py's
# auth dependency refuses all requests until SUPABASE_URL is set, rather
# than silently running open. Verification is against the project's public
# JWKS (see deps.py), not a shared secret - no separate secret to configure.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")


def llm_configured() -> bool:
    """True once whichever provider LLM_PROVIDER points at has a key set."""
    if LLM_PROVIDER == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    return bool(GEMINI_API_KEY)

# Meal slots sent each day, in order.
MEAL_SLOTS = ["breakfast", "lunch", "snack", "dinner"]
