"""Caspian wiring: one on_message handler for every connected channel, plus
the outbound send used by the daily scheduler job.

Households are matched to an inbound conversation by Household.link_code,
not by phone number - not every channel exposes a stable, known-in-advance
identity the way a phone number does (Telegram's sender has no phone number
at all unless the bot explicitly requests contact sharing), so "the cook's
first message must be exactly this code" is the one mechanism that works
uniformly across every channel Caspian supports."""

import datetime as dt
import os

from caspian_sdk import CommClient

from app.config import (
    CASPIAN_API_KEY,
    TELEGRAM_BOT_TOKEN,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_FROM_NUMBER,
)
from app.db import get_session
from app.meal_planner.generator import interpret_cook_reply
from app.messaging.formatter import format_daily_message
from app.models import Feedback, Household, MealPlanItem

_client = None
_connection = None


def get_client() -> CommClient:
    global _client
    if _client is None:
        _client = CommClient(api_key=CASPIAN_API_KEY) if CASPIAN_API_KEY else CommClient()
    return _client


def connect_channel():
    """The one line that names the channel - everything else (handler,
    formatter, scheduler) is channel-agnostic.

    CASPIAN_CHANNEL=telegram (current default for this deployment): a free
    bot via @BotFather, no card ever. Can't cold-start a conversation
    (Bot API-wide restriction) - see Household.link_code.

    CASPIAN_CHANNEL=sms: bring-your-own Twilio/Telnyx number. Confirmed
    working against Caspian's docs, but both providers gate real (non-
    template, non-trial) SMS behind adding billing - not free the way
    Telegram is.

    CASPIAN_CHANNEL=whatsapp: the installed caspian-sdk already exposes
    connect_whatsapp() / start_whatsapp_onboarding() - not yet live on
    Caspian's gateway as of this session (confirmed via their own
    SKILL.md and a live client.channels() call). One-env-var change to
    try later, see scripts/start_whatsapp_onboarding.py.
    """
    global _connection
    channel = os.environ.get("CASPIAN_CHANNEL", "telegram").lower()

    if channel == "whatsapp":
        _connection = get_client().connect_whatsapp()
    elif channel == "telegram":
        _connection = get_client().connect_telegram(bot_token=TELEGRAM_BOT_TOKEN)
    else:
        _connection = get_client().connect_phone(
            provider="twilio",
            account_sid=TWILIO_ACCOUNT_SID,
            auth_token=TWILIO_AUTH_TOKEN,
            from_number=TWILIO_FROM_NUMBER,
        )
    return _connection


_ready = False


def ensure_ready():
    """Idempotent connect_channel() + register_handler() - the one thing
    every entry point that needs to send/receive (the API's startup, the
    internal poll-messages job, ad-hoc scripts) should call instead of
    invoking connect_channel() directly, so a channel only ever gets
    connected once per process regardless of how many places call this."""
    global _ready
    if not _ready:
        connect_channel()
        register_handler()
        _ready = True


def _household_for_conversation(session, conversation_id: str):
    return session.query(Household).filter(Household.caspian_conversation_id == conversation_id).first()


def _household_for_link_code(session, text: str):
    code = (text or "").strip().upper()
    if not code:
        return None
    return (
        session.query(Household)
        .filter(Household.link_code == code, Household.caspian_conversation_id.is_(None))
        .first()
    )


def _ack_for_intent(intent: dict) -> str:
    return {
        "dislike": "Got it, noted - won't repeat that dish soon.",
        "swap_request": "Noted, will factor that into the next plan.",
        "ingredient_issue": "Thanks for the heads up on the ingredient - noted for next time.",
        "confirmation": "Great, thanks!",
    }.get(intent.get("type"), "Got your message, thanks!")


def register_handler():
    client = get_client()

    @client.on_message
    def handle(message):
        session = get_session()
        try:
            household = _household_for_conversation(session, message.conversation_id)

            if household is None:
                household = _household_for_link_code(session, message.text)
                if household is None:
                    message.reply(
                        "Hi! I don't recognize this yet - ask the family for your link "
                        "code and send it to me to get started."
                    )
                    return
                household.caspian_conversation_id = message.conversation_id
                session.commit()
                message.reply(
                    f"You're linked, {household.cook_name}! I'll send {household.name}'s "
                    "meals here as they're planned."
                )
                return

            todays_items = (
                session.query(MealPlanItem)
                .filter(MealPlanItem.household_id == household.id, MealPlanItem.date == dt.date.today())
                .all()
            )
            todays_recipe_ids = [rid for it in todays_items for rid in (it.dish_recipe_ids or [])]

            intent = interpret_cook_reply(message.text or "", todays_recipe_ids)

            session.add(
                Feedback(
                    household_id=household.id,
                    conversation_id=message.conversation_id,
                    raw_text=message.text or "",
                    parsed_intent=intent,
                )
            )
            session.commit()
            message.reply(_ack_for_intent(intent))
        finally:
            session.close()

    return handle


def send_daily_message(household: Household, slot_items: dict, recipe_cache: dict) -> str:
    """slot_items: {meal_slot: MealPlanItem} for today. Reuses the known
    conversation if the cook has already linked; otherwise cold-starts one
    via initiate() *only* if this connection actually supports it (Telegram
    doesn't - platform-wide restriction, not a Caspian limitation)."""
    client = get_client()
    text = format_daily_message(household, dt.date.today(), slot_items, recipe_cache)

    if household.caspian_conversation_id:
        client.send_message(household.caspian_conversation_id, text=text)
        return text

    if _connection is None:
        raise RuntimeError("connect_channel() must run before the first send")

    if "initiate" not in (_connection.get("capabilities") or []):
        raise RuntimeError(
            f"{household.cook_name} hasn't linked yet - ask them to message the bot/number "
            f"with the code {household.link_code!r} first (this channel can't cold-start a conversation)."
        )

    result = client.initiate(_connection["id"], recipient=household.cook_phone, text=text)
    conv_id = result.get("conversation_id") if isinstance(result, dict) else None
    if conv_id:
        session = get_session()
        try:
            db_household = session.get(Household, household.id)
            db_household.caspian_conversation_id = conv_id
            session.commit()
        finally:
            session.close()
    return text
