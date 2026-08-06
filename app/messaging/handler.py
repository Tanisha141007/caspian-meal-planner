"""Caspian wiring: one on_message handler for every connected channel, plus
the outbound send used by the daily scheduler job. This is the ONLY file
that should need to change when WhatsApp goes live on Caspian - swap
connect_phone(provider="twilio", ...) for connect_whatsapp(...) in
connect_channel() below; the handler and formatter are channel-agnostic."""

import datetime as dt
import os

from caspian_sdk import CommClient

from app.config import CASPIAN_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
from app.db import get_session
from app.meal_planner.generator import interpret_cook_reply
from app.messaging.formatter import format_daily_message
from app.models import Feedback, Household, MealPlanItem

_client = None
_phone_connection = None


def get_client() -> CommClient:
    global _client
    if _client is None:
        _client = CommClient(api_key=CASPIAN_API_KEY) if CASPIAN_API_KEY else CommClient()
    return _client


def connect_channel():
    """The one line that names the channel - everything else (handler,
    formatter, scheduler) is channel-agnostic.

    CASPIAN_CHANNEL=sms (default): bring-your-own Twilio number. Confirmed
    working against Caspian's public docs.

    CASPIAN_CHANNEL=whatsapp: the installed caspian-sdk already exposes
    connect_whatsapp() / start_whatsapp_onboarding(), which POSTs to a real
    /v1/connections/whatsapp/onboarding-session endpoint and is billed like
    the other paid channels (X, iMessage) - even though the public docs
    site still lists WhatsApp as "coming soon". It may or may not be
    enabled for your account yet; this path is here so trying it is a
    one-env-var change, not a code change. See scripts/start_whatsapp_onboarding.py.
    """
    global _phone_connection
    channel = os.environ.get("CASPIAN_CHANNEL", "sms").lower()

    if channel == "whatsapp":
        _phone_connection = get_client().connect_whatsapp()
        return _phone_connection

    _phone_connection = get_client().connect_phone(
        provider="twilio",
        account_sid=TWILIO_ACCOUNT_SID,
        auth_token=TWILIO_AUTH_TOKEN,
        from_number=TWILIO_FROM_NUMBER,
    )
    return _phone_connection


def _extract_phone(message) -> str:
    # NOTE: confirm this against a real inbound payload once Twilio is wired
    # up - Caspian's docs describe `sender` as a channel-specific identity
    # object but don't pin the exact keys for the phone channel.
    sender = getattr(message, "sender", None) or {}
    if isinstance(sender, dict):
        return sender.get("address") or sender.get("phone") or sender.get("id") or ""
    return str(sender)


def _household_for_phone(session, phone: str):
    return session.query(Household).filter(Household.cook_phone == phone).first()


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
        phone = _extract_phone(message)
        session = get_session()
        try:
            household = _household_for_phone(session, phone)
            if household is None:
                message.reply(
                    "Thanks for texting! This number isn't linked to a household yet - "
                    "ask the family to add you."
                )
                return

            # Remember the thread so the daily push can reuse send_message()
            # instead of cold-starting a new conversation every day.
            if household.caspian_conversation_id != message.conversation_id:
                household.caspian_conversation_id = message.conversation_id
                session.commit()

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
    conversation if the cook has texted before; otherwise cold-starts one
    via initiate() (requires the connection's "initiate" capability)."""
    client = get_client()
    text = format_daily_message(household, dt.date.today(), slot_items, recipe_cache)

    if household.caspian_conversation_id:
        client.send_message(household.caspian_conversation_id, text=text)
        return text

    if _phone_connection is None:
        raise RuntimeError("connect_channel() must run before the first send")

    result = client.initiate(_phone_connection["id"], recipient=household.cook_phone, text=text)
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
