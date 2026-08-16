import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_db
from app.messaging.handler import send_owner_welcome_email
from app.models import AppState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/welcome")
def send_welcome_email(db=Depends(get_db), user: dict = Depends(get_current_user)):
    user_id = user["id"]
    email = user.get("email")
    key = f"welcome_email_sent:{user_id}"

    existing = db.get(AppState, key)
    if existing and existing.value == "sent":
        return {"sent": False, "alreadySent": True}

    if not email:
        return {"sent": False, "alreadySent": False}

    try:
        send_owner_welcome_email(email)
    except Exception:
        logger.exception("Failed to send welcome email to user %s", user_id)
        raise

    if existing is None:
        existing = AppState(key=key, value="sent")
        db.add(existing)
    else:
        existing.value = "sent"
    db.commit()
    return {"sent": True, "alreadySent": False}
