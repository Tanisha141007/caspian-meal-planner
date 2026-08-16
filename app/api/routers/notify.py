import datetime as dt
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db, get_owned_household
from app.api.schemas import NotifyCookRequest
from app.config import APP_TIMEZONE, CASPIAN_API_KEY, MEAL_SLOTS
from app.messaging.handler import ensure_ready, send_daily_message
from app.models import Household, MealPlanItem, Recipe

router = APIRouter(prefix="/api/households/{household_id}/notify-cook", tags=["notify"])
WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _legacy_schedule_entry(household: Household) -> dict:
    return {
        "enabled": True,
        "time": household.send_time or "07:00",
        "meals": household.notify_meals or list(MEAL_SLOTS),
    }


def _schedule_entries_for(household: Household, day_key: str) -> list[dict]:
    schedule = household.cook_message_schedule or {}
    entries = schedule.get(day_key) or [_legacy_schedule_entry(household)]
    return [entry for entry in entries if entry.get("enabled", True) and entry.get("meals")]


def _time_for(entry: dict) -> dt.time | None:
    try:
        hour, minute = (int(part) for part in (entry.get("time") or "07:00").split(":"))
    except ValueError:
        return None
    return dt.time(hour=hour, minute=minute)


def _planned_items_for(db, household_id: int, date: dt.date) -> dict[str, MealPlanItem]:
    items = (
        db.query(MealPlanItem)
        .filter(MealPlanItem.household_id == household_id, MealPlanItem.date == date)
        .all()
    )
    return {item.meal_slot: item for item in items}


def _next_scheduled_item(db, household: Household) -> tuple[dt.date, MealPlanItem] | None:
    now = dt.datetime.now(ZoneInfo(APP_TIMEZONE))
    slot_rank = {slot: idx for idx, slot in enumerate(MEAL_SLOTS)}

    for offset in range(7):
        date = now.date() + dt.timedelta(days=offset)
        day_key = WEEKDAY_KEYS[date.weekday()]
        planned_items = _planned_items_for(db, household.id, date)
        if not planned_items:
            continue

        candidates = []
        for entry in _schedule_entries_for(household, day_key):
            entry_time = _time_for(entry)
            if entry_time is None:
                continue
            scheduled_at = dt.datetime.combine(date, entry_time, tzinfo=now.tzinfo)
            if scheduled_at < now:
                continue
            for slot in entry.get("meals") or []:
                item = planned_items.get(slot)
                if item is not None:
                    candidates.append((scheduled_at, slot_rank.get(slot, 99), item))

        if candidates:
            _, _, item = sorted(candidates, key=lambda candidate: (candidate[0], candidate[1]))[0]
            return date, item
    return None


@router.post("")
def notify_cook(
    body: NotifyCookRequest, household: Household = Depends(get_owned_household), db=Depends(get_db)
):
    if not CASPIAN_API_KEY:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Caspian isn't configured yet (CASPIAN_API_KEY unset) - nothing sent"
        )

    if body.slot:
        date = body.date or dt.date.today()
        slot_item = (
            db.query(MealPlanItem)
            .filter(
                MealPlanItem.household_id == household.id,
                MealPlanItem.date == date,
                MealPlanItem.meal_slot == body.slot,
            )
            .first()
        )
    else:
        next_item = _next_scheduled_item(db, household)
        date, slot_item = next_item if next_item else (body.date or dt.date.today(), None)

    if slot_item is None:
        what = f"{body.slot} on {date}" if body.slot else "the next scheduled meal"
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No planned meals for {what}")

    recipe_cache = {r.id: r for r in db.query(Recipe).all()}
    slot_items = {slot_item.meal_slot: slot_item}

    try:
        ensure_ready()
        text = send_daily_message(household, slot_items, recipe_cache, date=date)
    except Exception as e:
        slot_item.delivery_status = "failed"
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Caspian send failed: {e}") from e

    slot_item.sent_at = dt.datetime.utcnow()
    slot_item.delivery_status = "sent"
    db.commit()

    return {"sent": True, "message_preview": text}
