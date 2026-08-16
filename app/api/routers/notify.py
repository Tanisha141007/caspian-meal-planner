import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db, get_owned_household
from app.api.schemas import NotifyCookRequest
from app.config import CASPIAN_API_KEY
from app.messaging.handler import ensure_ready, send_daily_message
from app.models import Household, MealPlanItem, Recipe

router = APIRouter(prefix="/api/households/{household_id}/notify-cook", tags=["notify"])


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
    if body.slot:
        items = [it for it in items if it.meal_slot == body.slot]
    if not items:
        what = f"{body.slot} on {date}" if body.slot else str(date)
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No planned meals for {what}")

    recipe_cache = {r.id: r for r in db.query(Recipe).all()}
    slot_items = {it.meal_slot: it for it in items}

    try:
        ensure_ready()
        text = send_daily_message(household, slot_items, recipe_cache, date=date)
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
