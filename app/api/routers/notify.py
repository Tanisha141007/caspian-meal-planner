import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db, get_owned_household
from app.api.schemas import NotifyCookRequest
from app.config import CASPIAN_API_KEY
from app.messaging.handler import connect_channel, send_daily_message
from app.models import Household, MealPlanItem, Recipe

router = APIRouter(prefix="/api/households/{household_id}/notify-cook", tags=["notify"])

# connect_channel() opens one Caspian connection per process (see
# app/messaging/handler.py) - the API process does this lazily on first use
# rather than at import time, so the module imports fine with no
# CASPIAN_API_KEY set (every other route still works; this one 503s).
_channel_connected = False


def _ensure_channel_connected():
    global _channel_connected
    if not _channel_connected:
        connect_channel()
        _channel_connected = True


@router.post("")
def notify_cook(
    body: NotifyCookRequest, household: Household = Depends(get_owned_household), db=Depends(get_db)
):
    if not CASPIAN_API_KEY:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Caspian isn't configured yet (CASPIAN_API_KEY unset) - nothing sent"
        )

    date = body.date or dt.date.today()
    items = (
        db.query(MealPlanItem)
        .filter(MealPlanItem.household_id == household.id, MealPlanItem.date == date)
        .all()
    )
    if not items:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No planned meals for {date}")

    recipe_cache = {r.id: r for r in db.query(Recipe).all()}
    slot_items = {it.meal_slot: it for it in items}

    try:
        _ensure_channel_connected()
        text = send_daily_message(household, slot_items, recipe_cache)
    except Exception as e:
        for it in items:
            it.delivery_status = "failed"
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Caspian send failed: {e}") from e

    for it in items:
        it.sent_at = dt.datetime.utcnow()
        it.delivery_status = "sent"
    db.commit()

    return {"sent": True, "message_preview": text}
