"""Preview / send the weekly family email on demand.

Same builder the Monday cron uses (app/messaging/weekly_email.py), so GET here
shows exactly what Monday will send - which is the only practical way to check
the mail without waiting a week or moving the server clock.
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_db, get_owned_household
from app.api.schemas import WeeklyEmailRequest
from app.api.serializers import serialize_recipe
from app.config import CASPIAN_API_KEY
from app.messaging.handler import send_owner_email
from app.messaging.weekly_email import build_weekly_email, this_monday
from app.models import Household

router = APIRouter(prefix="/api/households/{household_id}/weekly-email", tags=["weekly-email"])

_NO_PLAN = "No active meal plan for that week yet - generate one before mailing it"


@router.get("/preview")
def preview_weekly_email(
    week_start: dt.date | None = None,
    household: Household = Depends(get_owned_household),
    db=Depends(get_db),
):
    """Renders without sending. `suggestions` comes back in the same shape
    Discover's rows use (serialize_recipe), so the frontend can show the same
    cards it already renders for "add to plan"."""
    email = build_weekly_email(db, household, week_start or this_monday())
    return {
        "weekStart": str(email["week_start"]),
        "to": household.owner_email or "",
        "daysPlanned": email["days_planned"],
        "text": email["text"],
        "blocks": email["blocks"],
        "suggestions": [serialize_recipe(r) for r in email["suggestions"]],
        "shoppingList": [
            {"name": i["item"], "qty": i["qty"], "unit": i["unit"]} for i in email["shopping_list"]
        ],
    }


@router.post("/send")
def send_weekly_email(
    body: WeeklyEmailRequest, household: Household = Depends(get_owned_household), db=Depends(get_db)
):
    """Sends now, off-schedule. Unlike the cron job this ignores
    weekly_email_enabled - an explicit request to send is the family asking
    for this one mail, not a change to their standing preference."""
    if not CASPIAN_API_KEY:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Caspian isn't configured yet (CASPIAN_API_KEY unset) - nothing sent"
        )
    if not household.owner_email:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "No owner_email on this household - set one before sending"
        )

    email = build_weekly_email(db, household, body.week_start or this_monday())
    if not email["days_planned"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_PLAN)

    try:
        send_owner_email(household, email["text"], email["blocks"])
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Caspian email send failed: {e}") from e

    return {
        "sent": True,
        "to": household.owner_email,
        "weekStart": str(email["week_start"]),
        "message_preview": email["text"],
    }
